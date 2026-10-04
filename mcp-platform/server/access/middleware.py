"""Server middleware (MCPServer(middleware=[…])): runs around every request before the
SDK validates it, so a refused tool never runs.

AuditMiddleware is listed first (outermost) so it also records refusals."""

from time import monotonic
from typing import Any

from mcp.server.context import HandlerResult
from mcp.shared.exceptions import MCPError
from mcp_types.methods import is_input_required

from access.audit_log import AuditLog
from access.constants import ACCESS_DENIED_ERROR_CODE, AuditEvent, AuditOutcome
from access.mcp_messages import extract_questions, extract_trace_id, to_mapping
from access.policy import AccessPolicy, get_caller

CALL_TOOL = "tools/call"
OPERATION_AUDIT_FIELDS = ("done", "detail", "approval", "approval_reason", "requested_by", "approved_by")


class AuthorizationMiddleware:
    """Refuses tool calls the caller's role doesn't allow."""

    def __init__(self, policy: AccessPolicy):
        self._policy = policy

    async def __call__(self, ctx: Any, call_next: Any) -> HandlerResult:
        if ctx.method == CALL_TOOL:
            refusal = self._policy.refusal_for_call(get_caller(), to_mapping(ctx.params).get("name"))
            if refusal:
                raise MCPError(code=ACCESS_DENIED_ERROR_CODE, message=f"Access denied: {refusal}")
        return await call_next(ctx)


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


def _elapsed_ms(started: float) -> int:
    return round((monotonic() - started) * 1000)
