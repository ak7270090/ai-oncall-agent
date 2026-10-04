"""Who may call and approve which tool (Phase 20).

Kubernetes RBAC limits what the MCP server's ServiceAccounts may do; it can't tell
which person asked. This policy can: every known user has a role, every role may call
the read-only tools, and each role lists the write tools it may call (and approve).
An approval must come from someone other than the requester (four eyes)."""

from dataclasses import dataclass

from constants import WRITE_TOOLS, Scope


@dataclass(frozen=True)
class Caller:
    user: str
    client: str
    scopes: tuple[str, ...]


class AccessPolicy:
    def __init__(self, user_roles: dict[str, str], role_write_tools: dict[str, list[str]]):
        self._user_roles = user_roles
        self._role_write_tools = {role: frozenset(tools) for role, tools in role_write_tools.items()}

    def refusal_for_call(self, caller: Caller, tool: str) -> str | None:
        """Why `caller` may not call `tool`, or None when allowed."""
        if tool in WRITE_TOOLS and Scope.WRITE not in caller.scopes:
            return f"the token lacks scope {Scope.WRITE}, needed for {tool}"
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
        if tool in WRITE_TOOLS and tool not in self._role_write_tools[role]:
            return f"role {role} may not {verb} {tool}"
        return None
