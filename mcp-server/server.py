"""On-call MCP server. Configure with MCP_* environment variables (see config/settings.py)."""

from mcp.server.mcpserver import MCPServer
from starlette.requests import Request
from starlette.responses import JSONResponse

from config import Settings, get_settings
from tools import ALL_TOOLS


def create_server(settings: Settings) -> MCPServer:
    server = MCPServer(settings.server_name, version=settings.server_version, log_level=settings.log_level)
    for tool in ALL_TOOLS:
        server.add_tool(tool)

    @server.custom_route("/health", methods=["GET"])
    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    return server


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
        )


if __name__ == "__main__":
    main()
