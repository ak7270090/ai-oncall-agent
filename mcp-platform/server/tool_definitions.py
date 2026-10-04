from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any

from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import Field

from config import ServerSettings


@dataclass(frozen=True)
class ToolDefinition:
    """A tool function plus its annotations: hints to clients about what the tool does."""

    function: Callable
    annotations: ToolAnnotations


# Reads the cluster or Prometheus, changes nothing, same answer when repeated soon after;
# talks to systems outside the server (open world).
READ_ONLY_TOOL = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True,
                                 open_world_hint=True)


def change_tool(idempotent: bool) -> ToolAnnotations:
    """Annotations of a tool that changes the cluster (MCP clients ask before calling these)."""
    return ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=idempotent,
                           open_world_hint=True)


def namespace_guard(settings: ServerSettings) -> tuple[Any, Callable[[str], None]]:
    """Annotated type for a `namespace` tool argument plus the allowlist check."""
    allowed = ", ".join(settings.allowed_namespaces)
    namespace_type = Annotated[str, Field(description=f"Kubernetes namespace (allowed: {allowed})")]

    def require_allowed(namespace: str) -> None:
        if namespace not in settings.allowed_namespaces:
            raise ToolError(f"Namespace '{namespace}' is not allowed. Allowed: {allowed}")

    return namespace_type, require_allowed

