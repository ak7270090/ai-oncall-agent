from collections.abc import Callable
from typing import Annotated

from pydantic import Field

from config import Settings
from observability import MetricsBackend
from observability.models import MetricSeries, ServiceOverview
from observability.queries import UNITS, Metric
from tools.guards import NAME_PATTERN, namespace_guard

DEFAULT_HISTORY_MINUTES = 15
MAX_HISTORY_MINUTES = 120


def build_observability_tools(backend: MetricsBackend, settings: Settings) -> list[Callable]:
    Namespace, require_allowed = namespace_guard(settings)
    ServiceName = Annotated[str, Field(pattern=NAME_PATTERN, description="Service name, e.g. payment-service")]

    def get_service_overview(namespace: Namespace = settings.default_namespace) -> ServiceOverview:
        """Current request rate, error rate (share of 5xx) and p99 latency for every
        service in the namespace. Start here to see which service is unhealthy.
        Only services with running, scraped pods appear: a service missing here may have
        no pods at all (check list_deployments / list_pods)."""
        require_allowed(namespace)
        return ServiceOverview(
            namespace=namespace, window=settings.metrics_rate_window, services=backend.service_overview(namespace)
        )

    def get_metrics(
        service: ServiceName,
        metric: Metric,
        namespace: Namespace = settings.default_namespace,
        minutes: Annotated[int, Field(ge=1, le=MAX_HISTORY_MINUTES, description="How far back to look")] = DEFAULT_HISTORY_MINUTES,
    ) -> MetricSeries:
        """History of one metric for a service, one sample per step, oldest first. Use it to
        see when a problem started (e.g. error_rate jumping after a deploy).
        Metrics: request_rate (req/s), error_rate (0-1 share of 5xx), error_count (5xx per
        window), latency_p99_ms, cpu_cores and memory_mb (both per pod; compare
        with the limits from get_pod_status), cpu_throttled_ratio (share of time the
        container was held at its CPU limit: high values mean CPU-starved even when
        average cpu_cores looks low). Empty samples = no data."""
        require_allowed(namespace)
        return MetricSeries(
            namespace=namespace,
            service=service,
            metric=metric,
            unit=UNITS[metric],
            step_seconds=settings.metrics_step_seconds,
            samples=backend.metric_history(namespace, service, metric, minutes),
        )

    return [get_service_overview, get_metrics]
