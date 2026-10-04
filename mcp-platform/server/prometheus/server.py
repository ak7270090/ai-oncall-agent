"""The Prometheus MCP server: `python -m prometheus.server` (port MCP_PROMETHEUS_SERVER__PORT,
9001). It needs no Kubernetes credentials."""

from mcp.server.mcpserver import MCPServer

from access.policy import build_access_policy
from base_server import add_tools, build_mcp_server, run_mcp_server
from config import Settings, get_settings
from prometheus.backend import MetricsBackend
from prometheus.fake_backend import FakeMetricsBackend
from prometheus.prometheus_backend import PrometheusBackend
from prometheus.tools import build_prometheus_tools


def create_metrics_backend(settings: Settings) -> MetricsBackend:
    if settings.backend == "fake":
        return FakeMetricsBackend()
    return PrometheusBackend(settings.prometheus_url, settings.prometheus_timeout_seconds,
                             settings.metrics_rate_window, settings.metrics_step_seconds)


def build_prometheus_server(settings: Settings, metrics: MetricsBackend | None = None) -> MCPServer:
    server = build_mcp_server(settings, settings.prometheus_server, build_access_policy(settings, frozenset()))
    add_tools(server, build_prometheus_tools(metrics or create_metrics_backend(settings), settings))
    return server


def main() -> None:
    settings = get_settings()
    run_mcp_server(build_prometheus_server(settings), settings, settings.prometheus_server)


if __name__ == "__main__":
    main()
