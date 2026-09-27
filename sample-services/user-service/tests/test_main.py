from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health_reports_service_and_version():
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["service"] == "user-service"


def test_get_existing_user():
    assert client.get("/users/1").json()["name"] == "Asha Rao"


def test_unknown_user_is_404():
    assert client.get("/users/999").status_code == 404


def test_requests_are_counted_in_metrics():
    client.get("/users/1")
    metrics = client.get("/metrics").text
    assert 'http_requests_total{handler="/users/{user_id}",method="GET",status="2xx"}' in metrics
    assert "http_request_duration_seconds_bucket" in metrics
    assert 'handler="/health"' not in metrics
