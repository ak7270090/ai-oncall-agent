import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("PAYMENT_API_KEY", "test-key")
    from main import app
    return TestClient(app)


def test_payment_is_approved(client):
    body = client.post("/payments", json={"order_id": "o-1", "amount": 25.0}).json()
    assert body["status"] == "approved"
    assert body["order_id"] == "o-1"
    assert body["provider"] == "fakepay"


def test_non_positive_amount_rejected(client):
    assert client.post("/payments", json={"order_id": "o-1", "amount": 0}).status_code == 422


def test_missing_api_key_fails_startup(monkeypatch):
    monkeypatch.delenv("PAYMENT_API_KEY", raising=False)
    from settings import Settings
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_payments_are_counted_in_metrics(client):
    client.post("/payments", json={"order_id": "o-1", "amount": 5.0})
    assert 'http_requests_total{handler="/payments",method="POST",status="2xx"}' in client.get("/metrics").text
