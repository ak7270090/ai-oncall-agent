from typing import Protocol

from mcp.server.mcpserver.exceptions import ToolError

from observability.models import MetricSample, ServiceHealth
from observability.queries import Metric


class MetricsError(ToolError):
    """An anticipated metrics failure; its message is shown to the model."""


class MetricsBackend(Protocol):
    def metric_history(self, namespace: str, service: str, metric: Metric, minutes: int) -> list[MetricSample]: ...

    def service_overview(self, namespace: str) -> list[ServiceHealth]: ...
