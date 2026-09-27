from data import fake_cluster
from data.fake_cluster import Metric, Service

SAMPLE_INTERVAL = "1m"


def get_metrics(service: Service, metric: Metric) -> dict:
    """Get the last 5 one-minute samples (oldest first) of a metric for a service.

    Metrics: error_rate (0-1 ratio of failed requests), latency_p99_ms, cpu_cores,
    memory_mb, request_rate (req/s).
    """
    series = fake_cluster.METRICS[service][metric]
    return {
        "service": service,
        "metric": metric,
        "unit": series["unit"],
        "interval": SAMPLE_INTERVAL,
        "samples": series["samples"],
    }


# Synthetic until Phase 7 (Prometheus): only offered with the fake backend so the
# agent never mixes invented metrics with a real cluster.
FAKE_OBSERVABILITY_TOOLS = (get_metrics,)
