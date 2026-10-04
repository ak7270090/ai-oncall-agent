"""Against the kind cluster's Prometheus (`make cluster-up`); skipped when unreachable.
The traffic generator provides load, so request metrics exist within ~1 minute."""

import time

import pytest

from prometheus.config import PrometheusServerSettings
from prometheus.metrics.access import MetricsError
from prometheus.metrics.prometheus_api import PrometheusReader

SETTINGS = PrometheusServerSettings(_env_file=None)
NAMESPACE = SETTINGS.default_namespace
SAMPLE_SERVICES = {"user-service", "payment-service", "order-service"}
DATA_WAIT_SECONDS = 120
POLL_SECONDS = 5


def _backend() -> PrometheusReader:
    return PrometheusReader(SETTINGS.prometheus_url, 3, SETTINGS.metrics_rate_window, SETTINGS.metrics_step_seconds)


def _prometheus_reachable() -> bool:
    try:
        _backend().service_overview(NAMESPACE)
    except MetricsError:
        return False
    return True


pytestmark = pytest.mark.skipif(not _prometheus_reachable(), reason="Prometheus not reachable (make cluster-up)")


@pytest.fixture(scope="module")
def overview():
    deadline = time.monotonic() + DATA_WAIT_SECONDS
    while True:
        services = {s.service: s for s in _backend().service_overview(NAMESPACE)}
        if SAMPLE_SERVICES <= services.keys() or time.monotonic() > deadline:
            return services
        time.sleep(POLL_SECONDS)


def test_all_services_report_traffic(overview):
    assert SAMPLE_SERVICES <= overview.keys()
    assert all(overview[s].request_rate_per_second for s in SAMPLE_SERVICES)


def test_healthy_services_have_low_error_rate(overview):
    assert all(overview[s].error_rate is not None and overview[s].error_rate < 0.05 for s in SAMPLE_SERVICES)


def test_latency_and_resource_history_available(overview):
    backend = _backend()
    for metric in ("latency_p99_ms", "cpu_cores", "memory_mb"):
        samples = backend.metric_history(NAMESPACE, "order-service", metric, minutes=5)
        assert any(s.value is not None for s in samples), metric
