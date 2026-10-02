from collections.abc import Callable

from cluster import ClusterBackend
from observability import MetricsBackend

from config import Settings
from tools.kubernetes import build_kubernetes_tools
from tools.observability import build_observability_tools


def build_tools(cluster: ClusterBackend, metrics: MetricsBackend, settings: Settings) -> list[Callable]:
    return [*build_kubernetes_tools(cluster, settings), *build_observability_tools(metrics, settings)]


__all__ = ["build_tools"]
