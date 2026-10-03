from cluster import ClusterBackend
from config import Settings
from observability import MetricsBackend
from tools.helpers import ToolDefinition
from tools.kubernetes import build_kubernetes_tools
from tools.observability import build_observability_tools


def build_tools(cluster: ClusterBackend, metrics: MetricsBackend, settings: Settings) -> list[ToolDefinition]:
    return [*build_kubernetes_tools(cluster, settings), *build_observability_tools(metrics, settings)]


__all__ = ["ToolDefinition", "build_tools"]
