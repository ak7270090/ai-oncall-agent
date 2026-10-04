import httpx2
import pytest

from prometheus.metrics.access import MetricsError
from prometheus.metrics.prometheus_api import PrometheusReader
from prometheus.metrics.queries import build_query

BASE_URL = "http://prometheus.test"


def reader_answering(handler) -> PrometheusReader:
    http_client = httpx2.Client(base_url=BASE_URL, transport=httpx2.MockTransport(handler))
    return PrometheusReader(BASE_URL, timeout_seconds=1, rate_window="1m", step_seconds=60, http_client=http_client)


def success(result: list[dict]) -> httpx2.Response:
    return httpx2.Response(200, json={"status": "success", "data": {"resultType": "matrix", "result": result}})


def test_history_parses_samples_and_nan_as_none():
    seen = {}

    def handler(request):
        seen.update(path=request.url.path, query=request.url.params["query"], step=request.url.params["step"])
        return success([{"metric": {}, "values": [[1700000000, "0.25"], [1700000060, "NaN"]]}])

    samples = reader_answering(handler).metric_history("shop", "payment-service", "error_rate", minutes=5)
    assert [s.value for s in samples] == [0.25, None]
    assert seen["path"] == "/api/v1/query_range"
    assert seen["step"] == "60"
    assert 'service="payment-service"' in seen["query"]


def test_no_series_means_no_samples():
    assert reader_answering(lambda r: success([])).metric_history("shop", "x", "request_rate", 5) == []


def test_overview_merges_metrics_per_service_and_defaults_missing_errors_to_zero():
    def handler(request):
        query = request.url.params["query"]
        if "histogram_quantile" in query:
            return success([{"metric": {"service": "order-service"}, "value": [0, "120.5"]}])
        if 'status="5xx"' in query:
            return success([{"metric": {"service": "order-service"}, "value": [0, "0.1"]}])
        return success([
            {"metric": {"service": "order-service"}, "value": [0, "2"]},
            {"metric": {"service": "user-service"}, "value": [0, "3"]},
        ])

    overview = {s.service: s for s in reader_answering(handler).service_overview("shop")}
    assert (overview["order-service"].error_rate, overview["order-service"].latency_p99_ms) == (0.1, 120.5)
    assert overview["user-service"].error_rate == 0.0


def test_query_error_is_reported():
    def handler(request):
        return httpx2.Response(400, json={"status": "error", "error": "parse error"})
    with pytest.raises(MetricsError, match="parse error"):
        reader_answering(handler).service_overview("shop")


def test_unreachable_prometheus_is_reported():
    def handler(request):
        raise httpx2.ConnectError("refused", request=request)
    with pytest.raises(MetricsError, match="unreachable"):
        reader_answering(handler).metric_history("shop", "x", "cpu_cores", 5)


@pytest.mark.parametrize(("metric", "expected_fragment"), [
    ("request_rate", "sum(rate(http_requests_total{"),
    ("error_rate", 'status="5xx"'),
    ("error_count", "increase("),
    ("latency_p99_ms", "histogram_quantile(0.99, sum by (le)"),
    ("cpu_cores", "avg(rate(process_cpu_seconds_total"),
    ("cpu_throttled_ratio", 'container_cpu_cfs_throttled_periods_total{namespace="shop",container="svc"}'),
    ("memory_mb", "avg(process_resident_memory_bytes"),
])
def test_queries_use_expected_promql(metric, expected_fragment):
    assert expected_fragment in build_query(metric, "shop", "svc", "1m")


def test_grouped_latency_keeps_service_and_le():
    assert "sum by (service, le)" in build_query("latency_p99_ms", "shop", None, "1m", group_by=("service",))


def test_service_overview_reports_each_query():
    finished = []
    reader_answering(lambda r: success([])).service_overview("shop", lambda metric, seconds: finished.append(metric))
    assert finished == ["request_rate", "error_rate", "latency_p99_ms"]
