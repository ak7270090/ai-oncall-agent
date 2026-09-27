from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_title: str = "AI On-Call Server"
    server_host: str = "127.0.0.1"
    server_port: int = 8000

    mcp_server_url: str = "http://127.0.0.1:9000/mcp"
    mcp_timeout_seconds: float = 30

    llm_model: str = "openai:gpt-5.4-mini"
    llm_api_key: SecretStr | None = None
    llm_timeout_seconds: float = 120
    llm_max_retries: int = 2

    max_question_length: int = 2000

    # Investigation graph
    default_namespace: str = "shop"
    error_rate_threshold: float = 0.05
    latency_threshold_ms: float = 1000
    max_pods_to_inspect: int = 3
    max_services_to_inspect: int = 3
    log_lines: int = 50
    max_follow_up_rounds: int = 2


@lru_cache
def get_settings() -> Settings:
    return Settings()
