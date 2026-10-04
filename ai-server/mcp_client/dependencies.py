from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends
from mcp import Client

from auth.constants import AGENT_CLIENT_ID, READ_SCOPES
from auth.dependencies import CurrentUserDep
from auth.tokens import McpTokenAuth, McpTokenIssuer
from config import Settings, SettingsDep
from mcp_client.connection import connect_to_mcp_servers
from mcp_client.constants import GATEWAY_NAME

# Opens an MCP session for the signed-in user: optional sampling / elicitation callbacks,
# and the token scopes (default: read only).
MCPConnector = Callable[..., AbstractAsyncContextManager[Client]]


@lru_cache
def load_token_issuer(private_key_path: Path, issuer: str, audience: str, ttl_seconds: float) -> McpTokenIssuer:
    return McpTokenIssuer.from_key_file(private_key_path, issuer, audience, ttl_seconds)


def build_mcp_connector(settings: Settings, user: str) -> MCPConnector:
    issuer = (load_token_issuer(settings.mcp_token_private_key_path, settings.mcp_token_issuer,
                                settings.mcp_token_audience, settings.mcp_token_ttl_seconds)
              if settings.mcp_token_private_key_path else None)

    def open_mcp(sampling_callback=None, elicitation_callback=None, scopes: tuple[str, ...] = READ_SCOPES):
        auth = McpTokenAuth(issuer, user, scopes) if issuer else None
        return connect_to_mcp_servers({GATEWAY_NAME: settings.mcp_gateway_url}, settings.mcp_timeout_seconds,
                                      sampling_callback, elicitation_callback, auth, settings.mcp_gateway_targets)

    return open_mcp


def get_mcp_connector(settings: SettingsDep, user: CurrentUserDep) -> MCPConnector:
    return build_mcp_connector(settings, user)


def get_service_mcp_connector(settings: SettingsDep) -> MCPConnector:
    """For the AI server's own checks (/ready): signed as the agent, not a person."""
    return build_mcp_connector(settings, AGENT_CLIENT_ID)


MCPConnectorDep = Annotated[MCPConnector, Depends(get_mcp_connector)]
ServiceMCPConnectorDep = Annotated[MCPConnector, Depends(get_service_mcp_connector)]
