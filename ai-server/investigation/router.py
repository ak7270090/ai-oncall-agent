"""POST /investigate and /investigate/stream: run one investigation over the MCP servers."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Annotated

from fastapi import APIRouter, Header
from fastapi.sse import EventSourceResponse, ServerSentEvent

from auth.constants import WRITE_SCOPES
from errors import describe_error
from investigation.constants import StreamEvent
from investigation.dependencies import InvestigationDependencies, InvestigationDependenciesDep
from investigation.events import ErrorEvent, InvestigationEvents
from investigation.evidence.mcp_toolbox import MCPToolbox
from investigation.schemas import EvidenceResponse, InvestigateRequest, InvestigateResponse
from investigation.service import run_investigation
from investigation.workflow.graph import build_investigation_graph
from llm.sampling import SamplingResponder
from mcp_client.constants import McpOperation
from mcp_client.langchain_tools import list_all_resource_templates, list_all_tools, to_langchain_tool
from mcp_client.tool_policy import split_read_only
from tracing import TraceLabels

logger = logging.getLogger(__name__)
router = APIRouter(tags=["investigation"])

TraceparentHeader = Annotated[str | None, Header(description="W3C traceparent: record the trace inside the caller's")]


@router.post("/investigate", response_model=InvestigateResponse)
async def investigate(
    request: InvestigateRequest, dependencies: InvestigationDependenciesDep, traceparent: TraceparentHeader = None,
) -> InvestigateResponse:
    return await _run_investigation(request, dependencies, traceparent)


@router.post("/investigate/stream", response_class=EventSourceResponse)
async def investigate_stream(
    request: InvestigateRequest, dependencies: InvestigationDependenciesDep, traceparent: TraceparentHeader = None,
) -> AsyncIterator[ServerSentEvent]:
    """The same investigation as POST /investigate, as Server-Sent Events while it runs:
    `step`, `tool`, `progress`, `llm` and `note` events, then `report` (the
    InvestigateResponse) or `error`. Closing the connection cancels the investigation."""
    events = InvestigationEvents()
    investigation = asyncio.create_task(_run_investigation(request, dependencies, traceparent, events))
    try:
        async for event in events.until_finished(investigation):
            yield event
        try:
            yield ServerSentEvent(event=StreamEvent.REPORT, data=investigation.result())
        except Exception as error:
            status_code, detail = describe_error(error)
            yield ServerSentEvent(event=StreamEvent.ERROR, data=ErrorEvent(status_code=status_code, detail=detail))
    finally:
        # Reached early when the client disconnects: stop the graph and its MCP calls.
        if not investigation.done():
            logger.warning("Stream closed by the client; cancelling the investigation")
            investigation.cancel()
            with suppress(asyncio.CancelledError):
                await investigation


async def _list_operations(dependencies: InvestigationDependencies) -> list[str]:
    """Write tools the report may propose. The investigation's own token can only read
    (the MCP server hides write tools from it), so they are listed with a write-scoped
    one, in a separate short session."""
    async with dependencies.open_mcp(scopes=WRITE_SCOPES) as mcp_client:
        return [t.name for t in await list_all_tools(mcp_client) if t.name in set(McpOperation)]


async def _run_investigation(
    request: InvestigateRequest, dependencies: InvestigationDependencies, traceparent: str | None,
    events: InvestigationEvents | None = None,
) -> InvestigateResponse:
    settings = dependencies.settings
    on_progress = events.on_tool_progress if events else None
    sampling = SamplingResponder(dependencies.models, settings.max_samplings_per_investigation)
    operations = await _list_operations(dependencies)
    async with dependencies.open_mcp(sampling) as mcp_client:
        tools, refused = split_read_only(await list_all_tools(mcp_client))
        if unknown := [t.name for t in refused if t.name not in set(McpOperation)]:
            logger.warning("Not giving the agent tools without a read-only annotation: %s", ", ".join(unknown))
        graph = build_investigation_graph(
            dependencies.models,
            MCPToolbox(mcp_client, tools, on_progress, await list_all_resource_templates(mcp_client)),
            [to_langchain_tool(mcp_client, tool, on_progress) for tool in tools],
            settings,
            operations,
        )
        result = await run_investigation(
            graph, request.question, settings.max_follow_up_rounds, dependencies.tracer,
            TraceLabels(tuple(request.trace_tags), traceparent, dependencies.user),
            [events.callback_handler()] if events else (), sampling,
        )
    return InvestigateResponse(
        answer=result.answer,
        report=result.report,
        scope=result.scope,
        namespace=result.namespace,
        evidence=[
            EvidenceResponse(step=e.step, source=e.source, arguments=e.arguments, error=e.error,
                             result=e.result if request.include_evidence_results else None)
            for e in result.evidence
        ],
        notes=result.notes,
        steps=result.steps,
        llm_calls=result.llm_calls,
        follow_up_limit_reached=result.follow_up_limit_reached,
        llm_model=settings.llm_model,
        trace_id=result.trace_id,
        trace_url=result.trace_url,
    )
