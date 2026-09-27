import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

REQUIRED_SECRETS = {"PAYMENT_API_KEY": "test-key", "DB_PASSWORD": "test-db-password"}


class MemoryStore:
    def __init__(self):
        self.saved: list[tuple] = []

    def save(self, *payment) -> None:
        self.saved.append(payment)


class DownStore:
    def save(self, *payment) -> None:
        from store import DatabaseUnavailable
        raise DatabaseUnavailable("database unavailable: payments-db:5432 (connection refused)")


@pytest.fixture
def app_module(monkeypatch):
    for name, value in REQUIRED_SECRETS.items():
        monkeypatch.setenv(name, value)
    import main
    yield main
    main.app.dependency_overrides.clear()
    main.settings.fault_mode = "none"


def client_with(app_module, store) -> TestClient:
    app_module.app.dependency_overrides[app_module.get_store] = lambda: store
    return TestClient(app_module.app, raise_server_exceptions=False)


def test_payment_is_approved_and_stored(app_module):
    store = MemoryStore()
    body = client_with(app_module, store).post("/payments", json={"order_id": "o-1", "amount": 25.0}).json()
    assert body["status"] == "approved"
    assert store.saved[0][1:] == ("o-1", 25.0, "fakepay")


def test_non_positive_amount_rejected(app_module):
    assert client_with(app_module, MemoryStore()).post("/payments", json={"order_id": "o", "amount": 0}).status_code == 422


def test_database_outage_is_503_and_logged(app_module, caplog):
    response = client_with(app_module, DownStore()).post("/payments", json={"order_id": "o-1", "amount": 5.0})
    assert response.status_code == 503
    assert any("database unavailable: payments-db:5432" in r.message for r in caplog.records)


def test_error_fault_simulates_regression(app_module):
    app_module.settings.fault_mode = "error"
    assert client_with(app_module, MemoryStore()).post("/payments", json={"order_id": "o", "amount": 5.0}).status_code == 500


def test_latency_fault_delays_payments(app_module, monkeypatch):
    slept = []
    monkeypatch.setattr(app_module.time, "sleep", slept.append)
    app_module.settings.fault_mode = "latency"
    client_with(app_module, MemoryStore()).post("/payments", json={"order_id": "o", "amount": 5.0})
    assert slept == [app_module.settings.fault_latency_seconds]


@pytest.mark.parametrize("missing", sorted(REQUIRED_SECRETS))
def test_missing_secret_fails_startup(monkeypatch, missing):
    for name, value in REQUIRED_SECRETS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv(missing)
    from settings import Settings
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_payments_are_counted_in_metrics(app_module):
    client = client_with(app_module, MemoryStore())
    client.post("/payments", json={"order_id": "o-1", "amount": 5.0})
    assert 'http_requests_total{handler="/payments",method="POST",status="2xx"}' in client.get("/metrics").text
