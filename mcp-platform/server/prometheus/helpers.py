from itertools import count

import anyio
from mcp.server.mcpserver import Context

from constants import Metric
from prometheus.backend import QueryDone


def query_progress_reporter(ctx: Context, total_queries: int) -> QueryDone:
    """A QueryDone callback that sends MCP progress ("2 of 3: error_rate queried in 0.4s").

    The backend runs in a worker thread (anyio.to_thread), so each report is handed back
    to the event loop with anyio.from_thread. Without a progress token from the client,
    report_progress does nothing."""
    finished = count(1)

    def report(metric: Metric, seconds: float) -> None:
        anyio.from_thread.run(ctx.report_progress, next(finished), total_queries, f"{metric} queried in {seconds:.1f}s")

    return report
