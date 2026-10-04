"""On-call MCP server. Configure with MCP_* environment variables (see config/settings.py)."""

import logging

from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

from access import AccessPolicy, AuditLog, AuditMiddleware, AuthorizationMiddleware, SignedTokenVerifier
from cluster import ClusterBackend, ClusterOperations, create_backend, create_operations
from config import Settings, get_settings
from constants import HEALTH_STATUS_OK, Scope
from observability import MetricsBackend, create_metrics_backend
from resources import build_completion_handler, build_resources
from tools import build_tools
from tools.operations import build_operation_tools

logger = logging.getLogger(__name__)


def create_server(
    settings: Settings, cluster: ClusterBackend | None = None, metrics: MetricsBackend | None = None,
    operations: ClusterOperations | None = None,
) -> MCPServer:
    """Without MCP_AUTH_SIGNING_KEY anyone who reaches the server may call every tool;
    every call is still audited."""
    policy = AccessPolicy(settings.user_roles, settings.role_write_tools) if settings.auth_signing_key else None
    middleware = [AuditMiddleware(AuditLog(settings.audit_log_path))]
    if policy:
        middleware.append(AuthorizationMiddleware(policy))
    server = MCPServer(settings.server_name, version=settings.server_version, log_level=settings.log_level,
                       middleware=middleware, **build_auth(settings))
    cluster = cluster or create_backend(settings)
    tools = build_tools(cluster, metrics or create_metrics_backend(settings), settings)
    if settings.enable_write_tools:
        tools += build_operation_tools(cluster, operations or create_operations(settings), settings, policy)
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


def build_auth(settings: Settings) -> dict:
    """MCPServer arguments for bearer-token authentication (Phase 19): every HTTP request
    needs a valid token with scope k8s:read, else 401 pointing to the protected resource
    metadata (/.well-known/oauth-protected-resource/mcp)."""
    if not settings.auth_signing_key:
        logger.warning("MCP_AUTH_SIGNING_KEY is not set: no authentication, anyone may call the tools")
        return {}
    return {
        "token_verifier": SignedTokenVerifier(settings.auth_signing_key.get_secret_value(),
                                              settings.auth_issuer_url, settings.auth_audience),
        "auth": AuthSettings(issuer_url=settings.auth_issuer_url, resource_server_url=settings.public_url,
                             required_scopes=[Scope.READ],
                             validate_token_resource=False),  # SignedTokenVerifier checks the audience
    }


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
