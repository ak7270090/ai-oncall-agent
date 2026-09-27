from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "payment-service"
    app_version: str = "dev"
    server_host: str = "0.0.0.0"
    server_port: int = 8080

    payment_provider: str = "fakepay"
    # Required: the pod fails to start without it, like a real service missing its Secret.
    payment_api_key: SecretStr

    db_host: str = "payments-db"
    db_port: int = 5432
    db_name: str = "payments"
    db_user: str = "payments"
    db_password: SecretStr
    db_connect_timeout_seconds: int = 2

    # Fault injection for the Phase 9 incident scenarios; "none" in normal operation.
    fault_mode: Literal["none", "error", "latency"] = "none"
    fault_latency_seconds: float = 3


@lru_cache
def get_settings() -> Settings:
    return Settings()
