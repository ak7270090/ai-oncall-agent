"""Which MCP tools the agent may use. Only tools the server annotates as read-only
(MCP tool annotations, `readOnlyHint`); a tool without annotations counts as unsafe.

Annotations are hints from the server, not security: Kubernetes RBAC (and later,
authorization) still decides what the MCP server can actually do."""

from mcp.types import Tool


def is_read_only(tool: Tool) -> bool:
    return bool(tool.annotations and tool.annotations.read_only_hint)


def split_read_only(tools: list[Tool]) -> tuple[list[Tool], list[Tool]]:
    """(tools the agent may use, tools it must not)."""
    return [t for t in tools if is_read_only(t)], [t for t in tools if not is_read_only(t)]
