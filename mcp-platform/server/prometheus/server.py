"""The Prometheus MCP server: `python -m prometheus.server` (port MCP_PROMETHEUS_SERVER__PORT,
9001). It needs no Kubernetes credentials."""

from mcp.server.mcpserver import MCPServer

from auth.roles import build_access_policy
from base_server import add_tools, build_mcp_server, run_mcp_server
from prometheus.config import PrometheusServerSettings, get_prometheus_settings
from prometheus.metrics.access import MetricsReader
from prometheus.metrics.fake import FakeMetricsReader
from prometheus.metrics.prometheus_api import PrometheusReader
from prometheus.tools import build_prometheus_tools


def create_metrics_reader(settings: PrometheusServerSettings) -> MetricsReader:
    if settings.backend == "fake":
        return FakeMetricsReader()
    return PrometheusReader(settings.prometheus_url, settings.prometheus_timeout_seconds,
                             settings.metrics_rate_window, settings.metrics_step_seconds)


def build_prometheus_server(settings: PrometheusServerSettings, reader: MetricsReader | None = None) -> MCPServer:
    server = build_mcp_server(settings, settings.prometheus_server, build_access_policy(settings, frozenset()))
    add_tools(server, build_prometheus_tools(reader or create_metrics_reader(settings), settings))
    return server


def main() -> None:
    settings = get_prometheus_settings()
    run_mcp_server(build_prometheus_server(settings), settings, settings.prometheus_server)


if __name__ == "__main__":
    main()
