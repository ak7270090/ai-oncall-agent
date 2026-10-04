"""Traces investigations in Langfuse: one trace per investigation, containing a span per
graph step, every LLM call (prompt, answer, model, token usage) and every MCP tool call.

Everything inside the trace comes from LangChain callbacks, received by Langfuse's
LangChain CallbackHandler. The fixed collection steps report their MCP calls through
the same callbacks (agent/evidence/mcp_toolbox.py), so nothing else depends on Langfuse.

Without Langfuse keys the tracer is disabled and does nothing."""

import logging
import re
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
from langfuse.types import TraceContext
from opentelemetry import trace as otel_trace
from opentelemetry.sdk.trace import ReadableSpan

from config import Settings
from constants import ACTION_TRACE_NAME, INVESTIGATION_TRACE_NAME, MCP_SDK_TRACER_NAME, TRACEPARENT_PATTERN

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TraceLabels:
    """Optional tags for filtering traces in Langfuse (e.g. eval, incident:db-down), an
    optional W3C `traceparent` of the caller's span: the investigation is then recorded
    inside the caller's trace (an eval experiment item), and the signed-in user."""

    tags: tuple[str, ...] = ()
    traceparent: str | None = None
    user_id: str | None = None


NO_LABELS = TraceLabels()


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
    def trace_investigation(self, question: str, labels: TraceLabels = NO_LABELS) -> Iterator[InvestigationTrace]:
        if self._client is None:
            yield InvestigationTrace()
            return
        parent = _parse_traceparent(labels.traceparent)
        # Inside someone else's trace (an eval experiment), that trace keeps its own name.
        nested = parent is not None or otel_trace.get_current_span().get_span_context().is_valid
        with (
            self._client.start_as_current_observation(
                trace_context=parent, name=INVESTIGATION_TRACE_NAME, as_type="agent",
                input={"question": question}) as root_span,
            propagate_attributes(trace_name=None if nested else INVESTIGATION_TRACE_NAME, user_id=labels.user_id,
                                 metadata=self._trace_metadata, tags=list(labels.tags) or None),
        ):
            trace_id = self._client.get_current_trace_id()
            yield InvestigationTrace(
                # Created inside the root span, so LangChain's spans nest under it.
                callbacks=[CallbackHandler(public_key=self._public_key)],
                trace_id=trace_id,
                trace_url=self._trace_url(trace_id),
                root_span=root_span,
            )

    @contextmanager
    def trace_action(self, description: str, user_id: str) -> Iterator[InvestigationTrace]:
        """One trace per approved-or-not change (POST /actions). The MCP client sends its
        trace id along, so the MCP server's audit record points to it."""
        if self._client is None:
            yield InvestigationTrace()
            return
        with (
            self._client.start_as_current_observation(name=ACTION_TRACE_NAME, input={"action": description}) as root_span,
            propagate_attributes(trace_name=ACTION_TRACE_NAME, user_id=user_id, metadata=self._trace_metadata),
        ):
            trace_id = self._client.get_current_trace_id()
            yield InvestigationTrace(trace_id=trace_id, trace_url=self._trace_url(trace_id), root_span=root_span)

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

# Langfuse clients created in this process, so shutdown flushes exactly those (and a
# process that never traced has nothing to shut down).
_clients_in_use: list[Langfuse] = []


def shutdown_tracers() -> None:
    """Send buffered spans of every tracer created so far; call when the process stops."""
    while _clients_in_use:
        _clients_in_use.pop().shutdown()


def _parse_traceparent(traceparent: str | None) -> TraceContext | None:
    match = re.fullmatch(TRACEPARENT_PATTERN, traceparent.strip().lower()) if traceparent else None
    if match is None:
        return None
    return TraceContext(trace_id=match["trace_id"], parent_span_id=match["span_id"])


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
    if client not in _clients_in_use:
        _clients_in_use.append(client)
    return InvestigationTracer(client, settings.langfuse_public_key, {"llm_model": settings.llm_model})
