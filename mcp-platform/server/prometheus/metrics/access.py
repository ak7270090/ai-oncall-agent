"""How the Prometheus MCP server reads metrics: the MetricsReader interface; the real one
is prometheus_api.py (PromQL in queries.py), the fake one fake.py (MCP_BACKEND=fake)."""

from collections.abc import Callable
from typing import Protocol

from mcp.server.mcpserver.exceptions import ToolError

from prometheus.constants import Metric
from prometheus.models import MetricSample, ServiceHealth


class MetricsError(ToolError):
    """An anticipated metrics failure; its message is shown to the model."""


# Called after each query of a call that runs several (e.g. to report progress):
# the metric just queried and how long the query took, in seconds.
QueryDone = Callable[[Metric, float], None]


class MetricsReader(Protocol):
    def metric_history(self, namespace: str, service: str, metric: Metric, minutes: int) -> list[MetricSample]: ...

    def service_overview(self, namespace: str, on_query_done: QueryDone | None = None) -> list[ServiceHealth]: ...
