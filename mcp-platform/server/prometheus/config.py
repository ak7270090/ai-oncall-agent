from functools import lru_cache
from pathlib import Path

from base_server import BaseServerSettings
from config import McpSettings, ServerIdentity


class PrometheusServerIdentity(ServerIdentity):
    name: str = "oncall-prometheus"
    port: int = 9001
    public_url: str = "http://127.0.0.1:9001/mcp"
    audit_log_path: Path = Path("logs/audit-prometheus.jsonl")


class PrometheusSettings(McpSettings):
    prometheus_server: PrometheusServerIdentity = PrometheusServerIdentity()
    prometheus_url: str = "http://127.0.0.1:9090"
    prometheus_timeout_seconds: float = 10
    # PromQL rate() window and range-query step for metric history.
    metrics_rate_window: str = "30s"
    metrics_step_seconds: int = 60


class PrometheusServerSettings(BaseServerSettings, PrometheusSettings):
    """Everything the Prometheus MCP server reads."""


@lru_cache
def get_prometheus_settings() -> PrometheusServerSettings:
    return PrometheusServerSettings()
