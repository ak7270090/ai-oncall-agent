import psycopg
import pytest

from settings import Settings
from store import CREATE_TABLE, DatabaseUnavailable, PostgresPaymentStore


class RecordingConnection:
    def __init__(self, log: list):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.log.append(sql)


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setenv("PAYMENT_API_KEY", "k")
    monkeypatch.setenv("DB_PASSWORD", "p")
    return PostgresPaymentStore(Settings(_env_file=None))


def test_schema_is_ensured_on_every_connection_so_an_emptied_db_recovers(store, monkeypatch):
    executed: list = []
    monkeypatch.setattr(psycopg, "connect", lambda **kwargs: RecordingConnection(executed))
    store.save("p1", "o1", 5.0, "fakepay")
    store.save("p2", "o2", 5.0, "fakepay")
    assert executed.count(CREATE_TABLE) == 2


def test_connection_failure_becomes_database_unavailable(store, monkeypatch):
    def refuse(**kwargs):
        raise psycopg.OperationalError("connection refused")
    monkeypatch.setattr(psycopg, "connect", refuse)
    with pytest.raises(DatabaseUnavailable, match="database unavailable: payments-db:5432"):
        store.save("p1", "o1", 5.0, "fakepay")
