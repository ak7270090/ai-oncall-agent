"""Who may call and approve which tool (Phase 20).

Kubernetes RBAC limits what the MCP server's ServiceAccounts may do; it can't tell
which person asked. Roles can: every known user has a role, every role may call the
read-only tools, and each role lists the write tools it may call (and approve). An
approval must come from someone other than the requester (four eyes).

Which tools a token's scope may reach is the gateway's job (Phase 22); roles decide by
person only. AuthorizationMiddleware enforces them before a tool runs."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.context import HandlerResult
from mcp.shared.exceptions import MCPError

from auth.config import AccessSettings
from auth.constants import ACCESS_DENIED_ERROR_CODE, ANONYMOUS_USER

CALL_TOOL = "tools/call"


@dataclass(frozen=True)
class Caller:
    user: str
    client: str


def get_caller() -> Caller:
    """Who sent the current request: the bearer token's person and agent. Anonymous
    without a token (stdio, in-process, or authentication off)."""
    token = get_access_token()
    if token is None:
        return Caller(user=ANONYMOUS_USER, client=ANONYMOUS_USER)
    return Caller(user=token.subject or token.client_id, client=token.client_id)


class AccessPolicy:
    def __init__(self, user_roles: dict[str, str], role_write_tools: dict[str, list[str]], write_tools: frozenset[str]):
        self._user_roles = user_roles
        self._role_write_tools = {role: frozenset(tools) for role, tools in role_write_tools.items()}
        self._write_tools = write_tools

    def refusal_for_call(self, caller: Caller, tool: str) -> str | None:
        """Why `caller` may not call `tool`, or None when allowed."""
        return self._refusal_for_role(caller.user, tool, "call")

    def refusal_for_approval(self, requester: str, approver: str, tool: str) -> str | None:
        """Why `approver` may not approve `requester`'s call of `tool`, or None when allowed."""
        if approver == requester:
            return f"{approver} requested this change and can't also approve it"
        return self._refusal_for_role(approver, tool, "approve")

    def _refusal_for_role(self, user: str, tool: str, verb: str) -> str | None:
        role = self._user_roles.get(user)
        if role not in self._role_write_tools:
            return f"user {user} has no role"
        if tool in self._write_tools and tool not in self._role_write_tools[role]:
            return f"role {role} may not {verb} {tool}"
        return None


def build_access_policy(settings: AccessSettings, write_tools: frozenset[str]) -> AccessPolicy | None:
    """The roles policy, or None while authentication is off (no person to check)."""
    if not settings.auth_jwks_path:
        return None
    return AccessPolicy(settings.user_roles, settings.role_write_tools, write_tools)


class AuthorizationMiddleware:
    """Server middleware (MCPServer(middleware=[…])): refuses tool calls the caller's role
    doesn't allow, before the SDK even validates the request."""

    def __init__(self, policy: AccessPolicy):
        self._policy = policy

    async def __call__(self, ctx: Any, call_next: Any) -> HandlerResult:
        if ctx.method == CALL_TOOL:
            params = ctx.params if isinstance(ctx.params, Mapping) else {}
            refusal = self._policy.refusal_for_call(get_caller(), params.get("name"))
            if refusal:
                raise MCPError(code=ACCESS_DENIED_ERROR_CODE, message=f"Access denied: {refusal}")
        return await call_next(ctx)
