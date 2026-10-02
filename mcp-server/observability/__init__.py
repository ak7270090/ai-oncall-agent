from config import Settings
from observability.backend import MetricsBackend, MetricsError
from fake.metrics_backend import FakeMetricsBackend
from observability.prometheus_backend import PrometheusBackend


def create_metrics_backend(settings: Settings) -> MetricsBackend:
    if settings.backend == "fake":
        return FakeMetricsBackend()
    return PrometheusBackend(
        settings.prometheus_url,
        settings.prometheus_timeout_seconds,
        settings.metrics_rate_window,
        settings.metrics_step_seconds,
    )


__all__ = ["FakeMetricsBackend", "MetricsBackend", "MetricsError", "PrometheusBackend", "create_metrics_backend"]
