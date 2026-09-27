from collections.abc import Callable

from cluster import ClusterBackend
from config import Settings
from tools.kubernetes import build_kubernetes_tools
from tools.observability import FAKE_OBSERVABILITY_TOOLS


def build_tools(backend: ClusterBackend, settings: Settings) -> list[Callable]:
    tools = build_kubernetes_tools(backend, settings)
    if settings.backend == "fake":
        tools.extend(FAKE_OBSERVABILITY_TOOLS)
    return tools


__all__ = ["build_tools"]
