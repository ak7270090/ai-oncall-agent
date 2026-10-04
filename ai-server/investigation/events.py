"""Live events of one investigation, for POST /investigate/stream (Server-Sent Events).

Three sources publish into one InvestigationEvents channel:
- LangChain callbacks (InvestigationEventHandler): graph steps, tool calls (the fixed
  steps' MCP calls report themselves as LangChain tool runs), LLM calls, step notes;
- MCP progress notifications from the MCP server (on_tool_progress);
- the end of the investigation (the report or an error), added by the route.
"""

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from fastapi.sse import ServerSentEvent
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.outputs import LLMResult
from pydantic import BaseModel

from investigation.constants import CALL_ID_LENGTH, MAX_STREAMED_ERROR_LENGTH, EventStatus, Step, StreamEvent

STEP_NAMES = {step.value for step in Step}


class StepEvent(BaseModel):
    step: str
    status: EventStatus
    seconds: float | None = None


class ToolEvent(BaseModel):
    tool: str
    call_id: str  # pairs a call's "started" with its "finished"/"failed"
    status: EventStatus
    step: str | None = None
    arguments: dict[str, Any] | None = None
    seconds: float | None = None
    error: str | None = None


class ProgressEvent(BaseModel):
    tool: str
    progress: float
    total: float | None = None
    message: str | None = None


class LlmEvent(BaseModel):
    call_id: str
    step: str | None
    status: EventStatus
    model: str | None = None
    purpose: str | None = None  # e.g. summarize_pod_logs, for MCP sampling requests
    seconds: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class NoteEvent(BaseModel):
    note: str


class ErrorEvent(BaseModel):
    status_code: int
    detail: str


class InvestigationEvents:
    def __init__(self):
        self._queue: asyncio.Queue[ServerSentEvent | None] = asyncio.Queue()

    def publish(self, event: StreamEvent, data: BaseModel) -> None:
        self._queue.put_nowait(ServerSentEvent(event=event, data=data.model_dump(mode="json", exclude_none=True)))

    async def on_tool_progress(self, tool: str, progress: float, total: float | None, message: str | None) -> None:
        self.publish(StreamEvent.PROGRESS, ProgressEvent(tool=tool, progress=progress, total=total, message=message))

    def callback_handler(self) -> "InvestigationEventHandler":
        return InvestigationEventHandler(self)

    async def until_finished(self, investigation: asyncio.Task) -> AsyncIterator[ServerSentEvent]:
        """Yield events as they're published, until `investigation` ends (any way)."""
        investigation.add_done_callback(lambda _: self._queue.put_nowait(None))
        while (event := await self._queue.get()) is not None:
            yield event


class InvestigationEventHandler(AsyncCallbackHandler):
    """Turns LangChain/LangGraph callbacks into stream events."""

    def __init__(self, events: InvestigationEvents):
        self._events = events
        self._started: dict[UUID, tuple[str, str | None, float]] = {}  # run -> name, step, start

    async def on_chain_start(self, serialized: dict[str, Any] | None, inputs: Any, *, run_id: UUID,
                             metadata: dict[str, Any] | None = None, **kwargs: Any) -> None:
        name = kwargs.get("name")
        # Only the graph's own steps, not the runnables inside them.
        if name in STEP_NAMES and (metadata or {}).get("langgraph_node") == name:
            self._started[run_id] = (name, name, time.monotonic())
            self._events.publish(StreamEvent.STEP, StepEvent(step=name, status=EventStatus.STARTED))

    async def on_chain_end(self, outputs: Any, *, run_id: UUID, **kwargs: Any) -> None:
        if run_id not in self._started:
            return
        step, _, seconds = self._finish(run_id)
        self._events.publish(StreamEvent.STEP, StepEvent(step=step, status=EventStatus.FINISHED, seconds=seconds))
        for note in outputs.get("notes", []) if isinstance(outputs, dict) else []:
            self._events.publish(StreamEvent.NOTE, NoteEvent(note=note))

    async def on_chain_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        if run_id in self._started:
            step, _, seconds = self._finish(run_id)
            self._events.publish(StreamEvent.STEP, StepEvent(step=step, status=EventStatus.FAILED, seconds=seconds))

    async def on_tool_start(self, serialized: dict[str, Any] | None, input_str: str, *, run_id: UUID,
                            metadata: dict[str, Any] | None = None, inputs: dict[str, Any] | None = None,
                            **kwargs: Any) -> None:
        tool, step = kwargs.get("name") or (serialized or {}).get("name", "unknown"), _step_of(metadata)
        self._started[run_id] = (tool, step, time.monotonic())
        self._events.publish(StreamEvent.TOOL, ToolEvent(
            tool=tool, call_id=_call_id(run_id), status=EventStatus.STARTED, step=step, arguments=inputs))

    async def on_tool_end(self, output: Any, *, run_id: UUID, metadata: dict[str, Any] | None = None,
                          **kwargs: Any) -> None:
        if run_id in self._started:
            tool, step, seconds = self._finish(run_id)
            self._events.publish(StreamEvent.TOOL, ToolEvent(
                tool=tool, call_id=_call_id(run_id), status=EventStatus.FINISHED, step=step, seconds=seconds))

    async def on_tool_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        if run_id in self._started:
            tool, step, seconds = self._finish(run_id)
            self._events.publish(StreamEvent.TOOL, ToolEvent(
                tool=tool, call_id=_call_id(run_id), status=EventStatus.FAILED, step=step, seconds=seconds,
                error=str(error)[:MAX_STREAMED_ERROR_LENGTH]))

    async def on_chat_model_start(self, serialized: dict[str, Any] | None, messages: Any, *, run_id: UUID,
                                  metadata: dict[str, Any] | None = None, **kwargs: Any) -> None:
        step, metadata = _step_of(metadata), metadata or {}
        self._started[run_id] = ("llm", step, time.monotonic())
        self._events.publish(StreamEvent.LLM, LlmEvent(
            call_id=_call_id(run_id), step=step, status=EventStatus.STARTED,
            model=metadata.get("ls_model_name"), purpose=metadata.get("purpose")))

    async def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        if run_id not in self._started:
            return
        _, step, seconds = self._finish(run_id)
        usage = _token_usage(response)
        self._events.publish(StreamEvent.LLM, LlmEvent(
            call_id=_call_id(run_id), step=step, status=EventStatus.FINISHED, seconds=seconds,
            input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens")))

    def _finish(self, run_id: UUID) -> tuple[str, str | None, float]:
        name, step, started = self._started.pop(run_id)
        return name, step, round(time.monotonic() - started, 2)


def _call_id(run_id: UUID) -> str:
    return run_id.hex[-CALL_ID_LENGTH:]  # the random end: run ids start with a timestamp


def _step_of(metadata: dict[str, Any] | None) -> str | None:
    metadata = metadata or {}
    return metadata.get("step") or metadata.get("langgraph_node")


def _token_usage(response: LLMResult) -> dict[str, int]:
    for generations in response.generations:
        for generation in generations:
            usage = getattr(getattr(generation, "message", None), "usage_metadata", None)
            if usage:
                return usage
    return {}
