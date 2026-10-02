from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "user-service"
    app_version: str = "dev"
    server_host: str = "0.0.0.0"
    server_port: int = 8080

    # Fault injection for the Phase 9 incidents; "none" in normal operation.
    fault_mode: Literal["none", "cpu"] = "none"
    fault_cpu_milliseconds: int = 800


@lru_cache
def get_settings() -> Settings:
    return Settings()
