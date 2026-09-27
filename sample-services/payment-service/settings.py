from functools import lru_cache

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
