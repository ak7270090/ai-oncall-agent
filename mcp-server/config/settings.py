from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MCP_", env_file=".env", extra="ignore")

    server_name: str = "oncall-mcp-server"
    server_version: str = "0.7.0"
    transport: Literal["streamable-http", "stdio"] = "streamable-http"
    host: str = "127.0.0.1"
    port: int = 9000
    path: str = "/mcp"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    # Host headers accepted when bound to a non-localhost address (DNS rebinding
    # protection). Empty = SDK default: protection on for localhost binds only.
    allowed_hosts: list[str] = []

    backend: Literal["kubernetes", "fake"] = "kubernetes"
    # Credentials of the read-only `mcp-server` ServiceAccount (`make mcp-kubeconfig`),
    # not the cluster-admin kubeconfig.
    kubeconfig_path: str = ".kube/config"
    kube_request_timeout_seconds: float = 10
    allowed_namespaces: list[str] = ["shop"]
    default_namespace: str = "shop"

    prometheus_url: str = "http://127.0.0.1:9090"
    prometheus_timeout_seconds: float = 10
    metrics_rate_window: str = "30s"
    metrics_step_seconds: int = 60


@lru_cache
def get_settings() -> Settings:
    return Settings()
