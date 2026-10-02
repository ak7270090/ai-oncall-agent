from collections.abc import Callable
from typing import Annotated, Any

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from config import Settings


def namespace_guard(settings: Settings) -> tuple[Any, Callable[[str], None]]:
    """Annotated type for a `namespace` tool argument plus the allowlist check."""
    allowed = ", ".join(settings.allowed_namespaces)
    namespace_type = Annotated[str, Field(description=f"Kubernetes namespace (allowed: {allowed})")]

    def require_allowed(namespace: str) -> None:
        if namespace not in settings.allowed_namespaces:
            raise ToolError(f"Namespace '{namespace}' is not allowed. Allowed: {allowed}")

    return namespace_type, require_allowed
