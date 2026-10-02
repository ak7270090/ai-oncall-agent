"""On-call MCP server. Configure with MCP_* environment variables (see config/settings.py)."""

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

from cluster import ClusterBackend, create_backend
from config import Settings, get_settings
from constants import HEALTH_STATUS_OK
from observability import MetricsBackend, create_metrics_backend
from tools import build_tools


def create_server(
    settings: Settings, cluster: ClusterBackend | None = None, metrics: MetricsBackend | None = None
) -> MCPServer:
    server = MCPServer(settings.server_name, version=settings.server_version, log_level=settings.log_level)
    tools = build_tools(cluster or create_backend(settings), metrics or create_metrics_backend(settings), settings)
    for tool in tools:
        server.add_tool(tool)

    @server.custom_route("/health", methods=["GET"])
    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": HEALTH_STATUS_OK})

    return server


def build_transport_security(settings: Settings) -> TransportSecuritySettings | None:
    if not settings.allowed_hosts:
        return None
    return TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=settings.allowed_hosts)


mcp = create_server(get_settings())


def main() -> None:
    settings = get_settings()
    if settings.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(
            transport="streamable-http",
            host=settings.host,
            port=settings.port,
            streamable_http_path=settings.path,
            transport_security=build_transport_security(settings),
        )


if __name__ == "__main__":
    main()
