"""Traces investigations in Langfuse: one trace per investigation, containing a span per
graph step, every LLM call (prompt, answer, model, token usage) and every MCP tool call.

Everything inside the trace comes from LangChain callbacks, received by Langfuse's
LangChain CallbackHandler. The fixed collection steps report their MCP calls through
the same callbacks (agent/evidence/mcp_toolbox.py), so nothing else depends on Langfuse.

Without Langfuse keys the tracer is disabled and does nothing."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langfuse import (
    Langfuse,
    LangfuseSpan,
    is_default_export_span,
    propagate_attributes,
)
from langfuse.langchain import CallbackHandler
from opentelemetry.sdk.trace import ReadableSpan

from config import Settings
from constants import INVESTIGATION_TRACE_NAME, MCP_SDK_TRACER_NAME

logger = logging.getLogger(__name__)


@dataclass
class InvestigationTrace:
    """Handle for one traced investigation; pass `callbacks` to the LangGraph run."""

    callbacks: list[BaseCallbackHandler] = field(default_factory=list)
    trace_id: str | None = None
    trace_url: str | None = None
    root_span: LangfuseSpan | None = None

    def record_outcome(self, output: Any, metadata: dict[str, Any]) -> None:
        if self.root_span is not None:
            self.root_span.update(output=output, metadata=metadata)


class InvestigationTracer:
    def __init__(self, client: Langfuse | None = None, public_key: str | None = None,
                 trace_metadata: dict[str, str] | None = None):
        self._client = client
        self._public_key = public_key
        self._trace_metadata = trace_metadata or {}

    @property
    def enabled(self) -> bool:
        return self._client is not None

    @contextmanager
    def trace_investigation(self, question: str) -> Iterator[InvestigationTrace]:
        if self._client is None:
            yield InvestigationTrace()
            return
        with (
            self._client.start_as_current_observation(
                name=INVESTIGATION_TRACE_NAME, as_type="agent", input={"question": question}) as root_span,
            propagate_attributes(trace_name=INVESTIGATION_TRACE_NAME, metadata=self._trace_metadata),
        ):
            trace_id = self._client.get_current_trace_id()
            yield InvestigationTrace(
                # Created inside the root span, so LangChain's spans nest under it.
                callbacks=[CallbackHandler(public_key=self._public_key)],
                trace_id=trace_id,
                trace_url=self._trace_url(trace_id),
                root_span=root_span,
            )

    def _trace_url(self, trace_id: str | None) -> str | None:
        # The first call asks Langfuse for the project id; an unreachable Langfuse must
        # not fail the investigation, it only loses the link.
        try:
            return self._client.get_trace_url(trace_id=trace_id)
        except Exception as error:
            logger.warning("Could not build the Langfuse trace URL: %s", error)
            return None

    def shutdown(self) -> None:
        """Send buffered spans; call once when the process stops."""
        if self._client is not None:
            self._client.shutdown()


DISABLED_TRACER = InvestigationTracer()


def should_export_span(span: ReadableSpan) -> bool:
    # The MCP SDK's own transport spans would duplicate every tool span at the trace root.
    scope = span.instrumentation_scope
    return is_default_export_span(span) and not (scope and scope.name == MCP_SDK_TRACER_NAME)


def create_tracer(settings: Settings) -> InvestigationTracer:
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return DISABLED_TRACER
    client = Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key.get_secret_value(),
        base_url=settings.langfuse_base_url,
        environment=settings.langfuse_environment,
        should_export_span=should_export_span,
    )
    return InvestigationTracer(client, settings.langfuse_public_key, {"llm_model": settings.llm_model})
