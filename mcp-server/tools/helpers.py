from collections.abc import Callable
from dataclasses import dataclass
from itertools import count
from typing import Annotated, Any

import anyio
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import Field

from config import Settings
from constants import Metric
from observability.backend import QueryDone


@dataclass(frozen=True)
class ToolDefinition:
    """A tool function plus its annotations: hints to clients about what the tool does."""

    function: Callable
    annotations: ToolAnnotations


# Reads the cluster or Prometheus, changes nothing, same answer when repeated soon after;
# talks to systems outside the server (open world).
READ_ONLY_TOOL = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True,
                                 open_world_hint=True)


def namespace_guard(settings: Settings) -> tuple[Any, Callable[[str], None]]:
    """Annotated type for a `namespace` tool argument plus the allowlist check."""
    allowed = ", ".join(settings.allowed_namespaces)
    namespace_type = Annotated[str, Field(description=f"Kubernetes namespace (allowed: {allowed})")]

    def require_allowed(namespace: str) -> None:
        if namespace not in settings.allowed_namespaces:
            raise ToolError(f"Namespace '{namespace}' is not allowed. Allowed: {allowed}")

    return namespace_type, require_allowed


def query_progress_reporter(ctx: Context, total_queries: int) -> QueryDone:
    """A QueryDone callback that sends MCP progress ("2 of 3: error_rate queried in 0.4s").

    The backend runs in a worker thread (anyio.to_thread), so each report is handed back
    to the event loop with anyio.from_thread. Without a progress token from the client,
    report_progress does nothing."""
    finished = count(1)

    def report(metric: Metric, seconds: float) -> None:
        anyio.from_thread.run(ctx.report_progress, next(finished), total_queries, f"{metric} queried in {seconds:.1f}s")

    return report
