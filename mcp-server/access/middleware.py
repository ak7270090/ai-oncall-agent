"""Server middleware (MCPServer(middleware=[…])): runs around every request before the
SDK validates it, so a refused tool never runs.

AuditMiddleware is listed first (outermost) so it also records refusals."""

from time import monotonic
from typing import Any

from mcp.server.context import HandlerResult
from mcp.shared.exceptions import MCPError
from mcp_types.methods import is_input_required

from access.audit_log import AuditLog
from access.helpers import elapsed_ms, extract_questions, extract_trace_id, get_caller, to_mapping
from access.policy import AccessPolicy
from constants import ACCESS_DENIED_ERROR_CODE, WRITE_TOOLS, AuditEvent, AuditOutcome, Scope

CALL_TOOL = "tools/call"
LIST_TOOLS = "tools/list"
OPERATION_AUDIT_FIELDS = ("done", "detail", "approval", "approval_reason", "requested_by", "approved_by")


class AuthorizationMiddleware:
    """Refuses tool calls the caller's role (or token scope) doesn't allow, and hides the
    write tools from tokens without k8s:write."""

    def __init__(self, policy: AccessPolicy):
        self._policy = policy

    async def __call__(self, ctx: Any, call_next: Any) -> HandlerResult:
        if ctx.method == CALL_TOOL:
            refusal = self._policy.refusal_for_call(get_caller(), to_mapping(ctx.params).get("name"))
            if refusal:
                raise MCPError(code=ACCESS_DENIED_ERROR_CODE, message=f"Access denied: {refusal}")
        result = await call_next(ctx)
        if ctx.method == LIST_TOOLS and Scope.WRITE not in get_caller().scopes:
            listing = dict(to_mapping(result))
            listing["tools"] = [tool for tool in listing.get("tools", [])
                                if to_mapping(tool).get("name") not in WRITE_TOOLS]
            return listing
        return result


class AuditMiddleware:
    """Records every tool call: who (person and agent), tool, arguments, outcome, the
    approval of write tools, and the trace id. A write tool's first round (the approval
    question) is recorded as `approval_requested`."""

    def __init__(self, audit_log: AuditLog):
        self._audit_log = audit_log

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
                                   error=error.message, duration_ms=elapsed_ms(started))
            raise
        mapping = to_mapping(result)
        if is_input_required(mapping):
            self._audit_log.record(event=AuditEvent.APPROVAL_REQUESTED, **entry, questions=extract_questions(mapping))
            return result
        failed = bool(mapping.get("isError"))
        details: dict[str, Any] = {}
        if failed:
            details["error"] = " ".join(c.get("text", "") for c in mapping.get("content", []))
        elif tool in WRITE_TOOLS:
            outcome = mapping.get("structuredContent") or {}
            details = {key: outcome.get(key) for key in OPERATION_AUDIT_FIELDS}
        self._audit_log.record(event=AuditEvent.TOOL_CALL, **entry,
                               outcome=AuditOutcome.ERROR if failed else AuditOutcome.OK,
                               **details, duration_ms=elapsed_ms(started))
        return result

