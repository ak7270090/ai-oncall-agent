from typing import Protocol

import psycopg

from settings import Settings

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS payments (
    payment_id TEXT PRIMARY KEY,
    order_id   TEXT NOT NULL,
    amount     NUMERIC(12, 2) NOT NULL,
    provider   TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""
INSERT_PAYMENT = "INSERT INTO payments (payment_id, order_id, amount, provider) VALUES (%s, %s, %s, %s)"


class DatabaseUnavailable(Exception):
    pass


class PaymentStore(Protocol):
    def save(self, payment_id: str, order_id: str, amount: float, provider: str) -> None: ...


class PostgresPaymentStore:
    """One short connection per payment: fine at demo traffic, and a DB outage
    surfaces immediately on the next request instead of in a stale pool. The schema
    is ensured on every connection so the service recovers when the database comes
    back empty (e.g. after a restart)."""

    def __init__(self, settings: Settings):
        self._address = f"{settings.db_host}:{settings.db_port}"
        self._connection_args = {
            "host": settings.db_host,
            "port": settings.db_port,
            "dbname": settings.db_name,
            "user": settings.db_user,
            "password": settings.db_password.get_secret_value(),
            "connect_timeout": settings.db_connect_timeout_seconds,
        }

    def save(self, payment_id: str, order_id: str, amount: float, provider: str) -> None:
        try:
            with psycopg.connect(**self._connection_args) as connection:
                connection.execute(CREATE_TABLE)
                connection.execute(INSERT_PAYMENT, (payment_id, order_id, amount, provider))
        except psycopg.OperationalError as error:
            raise DatabaseUnavailable(f"database unavailable: {self._address} ({error})".strip()) from error
