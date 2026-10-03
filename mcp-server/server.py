"""On-call MCP server. Configure with MCP_* environment variables (see config/settings.py)."""

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

from cluster import ClusterBackend, ClusterOperations, create_backend, create_operations
from config import Settings, get_settings
from constants import HEALTH_STATUS_OK
from observability import MetricsBackend, create_metrics_backend
from resources import build_completion_handler, build_resources
from tools import build_tools
from tools.operations import build_operation_tools


def create_server(
    settings: Settings, cluster: ClusterBackend | None = None, metrics: MetricsBackend | None = None,
    operations: ClusterOperations | None = None,
) -> MCPServer:
    server = MCPServer(settings.server_name, version=settings.server_version, log_level=settings.log_level)
    cluster = cluster or create_backend(settings)
    tools = build_tools(cluster, metrics or create_metrics_backend(settings), settings)
    if settings.enable_write_tools:
        tools += build_operation_tools(cluster, operations or create_operations(settings), settings)
    for tool in tools:
        server.add_tool(tool.function, annotations=tool.annotations)
    for resource in build_resources(cluster, settings):
        server.resource(resource.uri, name=resource.name, description=resource.description,
                        mime_type=resource.mime_type)(resource.read)
    server.completion()(build_completion_handler(cluster, settings))

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
