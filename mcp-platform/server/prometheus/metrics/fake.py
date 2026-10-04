"""Fake metrics (MCP_BACKEND=fake): the same canned incident as the fake cluster
(k8s/cluster/fake.py): payment-service failing since 09:42, order-service failing
downstream, user-service healthy."""

from datetime import datetime, timedelta, timezone

from prometheus.constants import SERVICE_OVERVIEW_METRICS, Metric
from prometheus.metrics.access import QueryDone
from prometheus.models import MetricSample, ServiceHealth

SAMPLE_STEP = timedelta(minutes=1)
NAMESPACE = "shop"
# Last 5 one-minute samples (oldest first) per service per metric; see queries.py for units.
METRICS_END_TIME = datetime(2026, 9, 27, 10, 0, tzinfo=timezone.utc)
METRICS: dict[str, dict[Metric, list[float]]] = {
    "payment-service": {
        Metric.CPU_THROTTLED_RATIO: [0.0, 0.0, 0.0, 0.0, 0.0],
        Metric.REQUEST_RATE: [42.0, 44.0, 43.0, 41.0, 40.0],
        Metric.ERROR_RATE: [0.002, 0.003, 0.41, 0.97, 1.0],
        Metric.ERROR_COUNT: [0, 0, 25, 58, 60],
        Metric.LATENCY_P99_MS: [120, 118, 2400, 5000, 5000],
        Metric.CPU_CORES: [0.35, 0.33, 0.05, 0.02, 0.02],
        Metric.MEMORY_MB: [310, 305, 90, 88, 85],
    },
    "order-service": {
        Metric.CPU_THROTTLED_RATIO: [0.0, 0.01, 0.02, 0.02, 0.01],
        Metric.REQUEST_RATE: [38.0, 40.0, 39.0, 37.0, 38.0],
        Metric.ERROR_RATE: [0.001, 0.002, 0.18, 0.46, 0.51],
        Metric.ERROR_COUNT: [0, 0, 7, 17, 19],
        Metric.LATENCY_P99_MS: [95, 97, 1800, 3100, 3050],
        Metric.CPU_CORES: [0.22, 0.24, 0.26, 0.25, 0.25],
        Metric.MEMORY_MB: [260, 262, 270, 275, 274],
    },
    "user-service": {
        Metric.CPU_THROTTLED_RATIO: [0.0, 0.0, 0.0, 0.0, 0.0],
        Metric.REQUEST_RATE: [65.0, 66.0, 64.0, 67.0, 65.0],
        Metric.ERROR_RATE: [0.001, 0.0, 0.001, 0.0, 0.001],
        Metric.ERROR_COUNT: [0, 0, 0, 0, 0],
        Metric.LATENCY_P99_MS: [30, 28, 31, 29, 30],
        Metric.CPU_CORES: [0.12, 0.11, 0.13, 0.12, 0.12],
        Metric.MEMORY_MB: [180, 181, 180, 182, 181],
    },
}


class FakeMetricsReader:
    """Serves the canned incident's metrics; same behavior contract as PrometheusReader."""

    def metric_history(self, namespace: str, service: str, metric: Metric, minutes: int) -> list[MetricSample]:
        if namespace != NAMESPACE:
            return []
        values = METRICS.get(service, {}).get(metric, [])
        first = METRICS_END_TIME - SAMPLE_STEP * (len(values) - 1)
        return [MetricSample(time=first + SAMPLE_STEP * i, value=v) for i, v in enumerate(values)]

    def service_overview(self, namespace: str, on_query_done: QueryDone | None = None) -> list[ServiceHealth]:
        if namespace != NAMESPACE:
            return []
        for metric in SERVICE_OVERVIEW_METRICS:
            if on_query_done:
                on_query_done(metric, 0.0)
        return [
            ServiceHealth(
                service=service,
                request_rate_per_second=metrics[Metric.REQUEST_RATE][-1],
                error_rate=metrics[Metric.ERROR_RATE][-1],
                latency_p99_ms=metrics[Metric.LATENCY_P99_MS][-1],
            )
            for service, metrics in sorted(METRICS.items())
        ]
