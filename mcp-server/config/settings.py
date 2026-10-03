from functools import lru_cache
from pathlib import Path
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
    # Write tools (restart / scale / roll back a Deployment), each asking a human for
    # approval (MCP elicitation). Off by default; they use the separate `mcp-operator`
    # ServiceAccount (`make mcp-kubeconfig` writes its kubeconfig).
    enable_write_tools: bool = False
    operator_kubeconfig_path: str = ".kube/operator-config"
    max_replicas: int = 5
    allowed_namespaces: list[str] = ["shop"]
    default_namespace: str = "shop"

    prometheus_url: str = "http://127.0.0.1:9090"
    prometheus_timeout_seconds: float = 10
    metrics_rate_window: str = "30s"
    metrics_step_seconds: int = 60

    # get_pod_logs(summarize=true): summarize only logs at least this long; limit the
    # summary's length; reuse fetched lines this long (the sampling retry must see the same).
    log_summary_min_lines: int = 40
    log_summary_max_tokens: int = 500
    log_cache_seconds: float = 30

    # Team knowledge published as MCP resources: runbooks/<service>.md and
    # topology/<namespace>.json (default: mcp-server/knowledge).
    knowledge_dir: Path = Path(__file__).resolve().parents[1] / "knowledge"
    # Most values returned for one completion request.
    max_completion_values: int = 100


@lru_cache
def get_settings() -> Settings:
    return Settings()
