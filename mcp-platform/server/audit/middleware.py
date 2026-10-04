"""Records every tool call as server middleware (MCPServer(middleware=[…])). Listed first
(outermost), so it also records calls the role check refuses."""

from collections.abc import Mapping
from time import monotonic
from typing import Any

from mcp.server.context import HandlerResult
from mcp.shared.exceptions import MCPError
from mcp_types.methods import is_input_required

from audit.constants import ELICITATION_METHOD, TRACEPARENT_KEY, AuditEvent, AuditOutcome
from audit.log import AuditLog
from auth.constants import ACCESS_DENIED_ERROR_CODE
from auth.roles import get_caller

CALL_TOOL = "tools/call"
OPERATION_AUDIT_FIELDS = ("done", "detail", "approval", "approval_reason", "requested_by", "approved_by")


class AuditMiddleware:
    """Records every tool call: who (person and agent), tool, arguments, outcome, the
    approval of write tools, and the trace id. A first round that asks for input is
    recorded as `approval_requested` (a human's approval) or `sampling_requested` (the
    client's LLM, e.g. a log summary)."""

    def __init__(self, audit_log: AuditLog, write_tools: frozenset[str]):
        self._audit_log = audit_log
        self._write_tools = write_tools

    async def __call__(self, ctx: Any, call_next: Any) -> HandlerResult:
        if ctx.method != CALL_TOOL:
            return await call_next(ctx)
        params, caller = to_mapping(ctx.params), get_caller()
        tool = params.get("name")
        entry = {"user": caller.user, "client": caller.client, "tool": tool,
                 "arguments": params.get("arguments"), "trace_id": extract_trace_id(params)}
        started = monotonic()
        try:
            result = await call_next(ctx)
        except MCPError as error:
            refused = error.code == ACCESS_DENIED_ERROR_CODE
            self._audit_log.record(event=AuditEvent.REFUSED if refused else AuditEvent.TOOL_CALL, **entry,
                                   outcome=AuditOutcome.REFUSED if refused else AuditOutcome.ERROR,
                                   error=error.message, duration_ms=_elapsed_ms(started))
            raise
        mapping = to_mapping(result)
        if is_input_required(mapping):
            questions = extract_questions(mapping)
            if questions:
                self._audit_log.record(event=AuditEvent.APPROVAL_REQUESTED, **entry, questions=questions)
            else:
                self._audit_log.record(event=AuditEvent.SAMPLING_REQUESTED, **entry)
            return result
        failed = bool(mapping.get("isError"))
        details: dict[str, Any] = {}
        if failed:
            details["error"] = " ".join(c.get("text", "") for c in mapping.get("content", []))
        elif tool in self._write_tools:
            outcome = mapping.get("structuredContent") or {}
            details = {key: outcome.get(key) for key in OPERATION_AUDIT_FIELDS}
        self._audit_log.record(event=AuditEvent.TOOL_CALL, **entry,
                               outcome=AuditOutcome.ERROR if failed else AuditOutcome.OK,
                               **details, duration_ms=_elapsed_ms(started))
        return result


def to_mapping(value: Any) -> Mapping[str, Any]:
    """Request params and results as the middleware gets them: plain mappings, or models."""
    if isinstance(value, Mapping):
        return value
    return value.model_dump(by_alias=True, exclude_none=True) if hasattr(value, "model_dump") else {}


def extract_trace_id(params: Mapping[str, Any]) -> str | None:
    """Trace id from the W3C traceparent the client put in the request's `_meta`
    (`00-<trace id>-<span id>-<flags>`), i.e. the caller's Langfuse trace."""
    traceparent = (params.get("_meta") or {}).get(TRACEPARENT_KEY)
    parts = traceparent.split("-") if isinstance(traceparent, str) else []
    return parts[1] if len(parts) == 4 else None


def extract_questions(result: Mapping[str, Any]) -> list[str]:
    """Questions an `input_required` interim result asks the human (approvals); sampling
    requests to the client's LLM have none."""
    return [request.get("params", {}).get("message", "") for request in (result.get("inputRequests") or {}).values()
            if request.get("method") == ELICITATION_METHOD]


def _elapsed_ms(started: float) -> int:
    return round((monotonic() - started) * 1000)
