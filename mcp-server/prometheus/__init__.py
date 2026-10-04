"""The Prometheus tool set (MCP_TOOLSETS=prometheus): service overview and metric
history (tools.py), read from Prometheus (prometheus_backend.py, PromQL in queries.py)
or from the canned incident (fake_backend.py, MCP_BACKEND=fake)."""

from config import Settings
from prometheus.backend import MetricsBackend, MetricsError
from prometheus.fake_backend import FakeMetricsBackend
from prometheus.prometheus_backend import PrometheusBackend
from prometheus.tools import build_prometheus_tools


def create_metrics_backend(settings: Settings) -> MetricsBackend:
    if settings.backend == "fake":
        return FakeMetricsBackend()
    return PrometheusBackend(
        settings.prometheus_url,
        settings.prometheus_timeout_seconds,
        settings.metrics_rate_window,
        settings.metrics_step_seconds,
    )


__all__ = [
    "FakeMetricsBackend",
    "MetricsBackend",
    "MetricsError",
    "PrometheusBackend",
    "build_prometheus_tools",
    "create_metrics_backend",
]
