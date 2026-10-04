from datetime import timedelta

import fake_incident
from prometheus.constants import SERVICE_OVERVIEW_METRICS, Metric
from prometheus.metrics.access import QueryDone
from prometheus.models import MetricSample, ServiceHealth

SAMPLE_STEP = timedelta(minutes=1)


class FakeMetricsReader:
    """Serves the canned incident's metrics; same behavior contract as PrometheusReader."""

    def metric_history(self, namespace: str, service: str, metric: Metric, minutes: int) -> list[MetricSample]:
        if namespace != fake_incident.NAMESPACE:
            return []
        values = fake_incident.METRICS.get(service, {}).get(metric, [])
        first = fake_incident.METRICS_END_TIME - SAMPLE_STEP * (len(values) - 1)
        return [MetricSample(time=first + SAMPLE_STEP * i, value=v) for i, v in enumerate(values)]

    def service_overview(self, namespace: str, on_query_done: QueryDone | None = None) -> list[ServiceHealth]:
        if namespace != fake_incident.NAMESPACE:
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
            for service, metrics in sorted(fake_incident.METRICS.items())
        ]
