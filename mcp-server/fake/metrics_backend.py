from datetime import timedelta

from constants import Metric
from fake import incident_data
from observability.models import MetricSample, ServiceHealth

SAMPLE_STEP = timedelta(minutes=1)


class FakeMetricsBackend:
    """Serves the canned incident's metrics; same behavior contract as PrometheusBackend."""

    def metric_history(self, namespace: str, service: str, metric: Metric, minutes: int) -> list[MetricSample]:
        if namespace != incident_data.NAMESPACE:
            return []
        values = incident_data.METRICS.get(service, {}).get(metric, [])
        first = incident_data.METRICS_END_TIME - SAMPLE_STEP * (len(values) - 1)
        return [MetricSample(time=first + SAMPLE_STEP * i, value=v) for i, v in enumerate(values)]

    def service_overview(self, namespace: str) -> list[ServiceHealth]:
        if namespace != incident_data.NAMESPACE:
            return []
        return [
            ServiceHealth(
                service=service,
                request_rate_per_second=metrics["request_rate"][-1],
                error_rate=metrics["error_rate"][-1],
                latency_p99_ms=metrics["latency_p99_ms"][-1],
            )
            for service, metrics in sorted(incident_data.METRICS.items())
        ]
