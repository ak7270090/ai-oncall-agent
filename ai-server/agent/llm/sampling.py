"""Answers MCP sampling requests: the MCP server asks this client's LLM for a completion
(e.g. a log summary). The ModelRouter picks the model from the request's preferences;
the server never sees an API key or chooses a provider."""

import logging
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from mcp_types import (
    INTERNAL_ERROR,
    INVALID_REQUEST,
    CreateMessageRequestParams,
    CreateMessageResult,
    ErrorData,
    TextContent,
)

from agent.llm.model_router import ModelRouter
from constants import APPROX_CHARS_PER_TOKEN

logger = logging.getLogger(__name__)

DEFAULT_SAMPLING_TASK = "mcp_sampling"


def to_langchain_messages(params: CreateMessageRequestParams) -> list[BaseMessage]:
    messages: list[BaseMessage] = [SystemMessage(params.system_prompt)] if params.system_prompt else []
    for message in params.messages:
        blocks = message.content if isinstance(message.content, list) else [message.content]
        text = "\n".join(block.text for block in blocks if isinstance(block, TextContent))
        messages.append(AIMessage(text) if message.role == "assistant" else HumanMessage(text))
    return messages


class SamplingResponder:
    """The `sampling_callback` of one investigation's MCP connection."""

    def __init__(self, models: ModelRouter, max_requests: int):
        self._models = models
        self._remaining = max_requests
        self._callbacks: list[BaseCallbackHandler] = []

    def attach_callbacks(self, callbacks: list[BaseCallbackHandler]) -> None:
        """Tracing / live-event callbacks of the investigation, so sampling calls show up there.
        Sampling arrives on the MCP session's own task, outside the graph's context."""
        self._callbacks = callbacks

    async def __call__(self, context: Any, params: CreateMessageRequestParams) -> CreateMessageResult | ErrorData:
        if self._remaining <= 0:
            return ErrorData(code=INVALID_REQUEST, message="Sampling limit for this investigation reached")
        self._remaining -= 1
        tier = self._models.tier_for_preferences(params.model_preferences)
        task = (params.metadata or {}).get("task", DEFAULT_SAMPLING_TASK)
        try:
            reply = await self._models.model(tier).ainvoke(
                to_langchain_messages(params),
                config={"callbacks": self._callbacks, "run_name": task, "metadata": {"purpose": task}},
            )
        except Exception as error:
            logger.warning("Sampling request %s failed: %s", task, error)
            return ErrorData(code=INTERNAL_ERROR, message="The client's LLM could not answer the sampling request")
        text = reply.text[: params.max_tokens * APPROX_CHARS_PER_TOKEN]
        return CreateMessageResult(role="assistant", content=TextContent(type="text", text=text),
                                   model=self._models.name(tier), stop_reason="endTurn")
