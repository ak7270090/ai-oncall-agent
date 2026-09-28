import httpx2
import pytest
from fastapi.testclient import TestClient

from main import app, get_http_client, settings

PAYMENT_ID = "pay-123"


def downstream(user_status: int = 200, payment_status: int = 200, fail_payment: bool = False):
    def handle(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.startswith("/users/"):
            return httpx2.Response(user_status, json={"id": 1} if user_status == 200 else {"detail": "user 1 not found"})
        if fail_payment:
            raise httpx2.ConnectError("connection refused", request=request)
        return httpx2.Response(payment_status, json={"payment_id": PAYMENT_ID})
    return httpx2.AsyncClient(transport=httpx2.MockTransport(handle))


@pytest.fixture
def use_downstream():
    def install(**behaviour):
        app.dependency_overrides[get_http_client] = lambda: downstream(**behaviour)
        return TestClient(app)
    yield install
    app.dependency_overrides.clear()


def test_order_confirmed_when_user_and_payment_succeed(use_downstream):
    response = use_downstream().post("/orders", json={"user_id": 1, "amount": 10})
    assert response.status_code == 201
    assert response.json()["payment_id"] == PAYMENT_ID


def test_unknown_user_is_404(use_downstream):
    response = use_downstream(user_status=404).post("/orders", json={"user_id": 1, "amount": 10})
    assert response.status_code == 404


def test_payment_unreachable_is_502(use_downstream):
    response = use_downstream(fail_payment=True).post("/orders", json={"user_id": 1, "amount": 10})
    assert response.status_code == 502
    assert settings.payment_service_url in response.json()["detail"]


def test_payment_error_is_502(use_downstream):
    response = use_downstream(payment_status=500).post("/orders", json={"user_id": 1, "amount": 10})
    assert response.status_code == 502


def test_upstream_failures_counted_as_5xx(use_downstream):
    client = use_downstream(fail_payment=True)
    client.post("/orders", json={"user_id": 1, "amount": 10})
    assert 'http_requests_total{handler="/orders",method="POST",status="5xx"}' in client.get("/metrics").text


def test_upstream_failure_is_logged_with_the_failing_url(use_downstream, caplog):
    use_downstream(fail_payment=True).post("/orders", json={"user_id": 1, "amount": 10})
    assert any("upstream unavailable" in r.message and "/payments" in r.message for r in caplog.records)


def test_slow_upstream_call_is_logged_with_its_url(use_downstream, caplog, monkeypatch):
    monkeypatch.setattr(settings, "slow_call_warning_seconds", 0)
    use_downstream().post("/orders", json={"user_id": 1, "amount": 10})
    assert any("slow upstream call: POST" in r.message and "/payments" in r.message for r in caplog.records)


def test_probe_and_scrape_requests_are_kept_out_of_the_access_log():
    import logging
    from main import ProbeAccessLogFilter
    def record(message: str) -> logging.LogRecord:
        return logging.LogRecord("uvicorn.access", logging.INFO, "", 0, message, None, None)
    probe_filter = ProbeAccessLogFilter()
    assert not probe_filter.filter(record('10.0.0.1 - "GET /health HTTP/1.1" 200'))
    assert not probe_filter.filter(record('10.0.0.1 - "GET /metrics HTTP/1.1" 200'))
    assert probe_filter.filter(record('10.0.0.1 - "POST /orders HTTP/1.1" 201'))
