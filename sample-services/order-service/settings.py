from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "order-service"
    app_version: str = "dev"
    server_host: str = "0.0.0.0"
    server_port: int = 8080

    user_service_url: str = "http://localhost:8081"
    payment_service_url: str = "http://localhost:8082"
    downstream_timeout_seconds: float = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()
