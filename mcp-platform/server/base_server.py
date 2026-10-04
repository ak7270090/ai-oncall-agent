"""What every MCP server here shares: token authentication, the audit and role middleware,
/health, and how it runs. Each server (k8s/server.py, prometheus/server.py) builds on it
and adds its own tools."""

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

from audit.log import AuditLog
from audit.middleware import AuditMiddleware
from auth.config import AccessSettings
from auth.roles import AccessPolicy, AuthorizationMiddleware
from auth.tokens import build_token_auth
from config import ServerIdentity, ServerSettings
from constants import HEALTH_STATUS_OK
from tool_definitions import ToolDefinition


class BaseServerSettings(ServerSettings, AccessSettings):
    """What every MCP server reads: the shared settings and authentication. Each server
    adds its own (k8s/config.py, prometheus/config.py)."""


def build_mcp_server(settings: BaseServerSettings, identity: ServerIdentity, policy: AccessPolicy | None,
                     write_tools: frozenset[str] = frozenset()) -> MCPServer:
    """An MCP server without tools: every call is audited; with authentication on, every
    request needs a valid token and every tool call a role that allows it."""
    middleware = [AuditMiddleware(AuditLog(identity.audit_log_path), write_tools)]
    if policy:
        middleware.append(AuthorizationMiddleware(policy))
    server = MCPServer(identity.name, version=settings.server_version, log_level=settings.log_level,
                       middleware=middleware, **build_token_auth(settings, identity.public_url))

    @server.custom_route("/health", methods=["GET"])
    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": HEALTH_STATUS_OK})

    return server


def add_tools(server: MCPServer, tools: list[ToolDefinition]) -> None:
    for tool in tools:
        server.add_tool(tool.function, annotations=tool.annotations)


def build_transport_security(settings: ServerSettings) -> TransportSecuritySettings | None:
    if not settings.allowed_hosts:
        return None
    return TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=settings.allowed_hosts)


def run_mcp_server(server: MCPServer, settings: ServerSettings, identity: ServerIdentity) -> None:
    if settings.transport == "stdio":
        server.run(transport="stdio")
        return
    server.run(transport="streamable-http", host=settings.host, port=identity.port, streamable_http_path=settings.path,
               transport_security=build_transport_security(settings))
