import secrets
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from mcp import Client

from actions import ActionRegistry
from agent import ModelRouter, create_model_router
from config import Settings, get_settings
from constants import AGENT_CLIENT_ID, ANONYMOUS_USER, API_KEY_HEADER, READ_SCOPES
from mcp_client import McpTokenAuth, McpTokenIssuer, connect_to_mcp
from tracing import InvestigationTracer, create_tracer

# Opens an MCP session for the signed-in user: optional sampling / elicitation callbacks,
# and the token scopes (default: read only).
MCPConnector = Callable[..., AbstractAsyncContextManager[Client]]
ApiKeyHeader = APIKeyHeader(name=API_KEY_HEADER, auto_error=False, description="Your API key")


@lru_cache
def get_action_registry() -> ActionRegistry:
    settings = get_settings()
    return ActionRegistry(settings.approval_timeout_seconds, require_second_person=bool(settings.api_keys))


@lru_cache
def get_model_router() -> ModelRouter:
    return create_model_router(get_settings())


def get_tracer(settings: Annotated[Settings, Depends(get_settings)]) -> InvestigationTracer:
    # Langfuse keeps one client per public key, so this is cheap after the first call.
    return create_tracer(settings)


def get_current_user(settings: Annotated[Settings, Depends(get_settings)],
                     api_key: Annotated[str | None, Security(ApiKeyHeader)] = None) -> str:
    """The person behind the request, from the X-API-Key header (Phase 19)."""
    if not settings.api_keys:
        return ANONYMOUS_USER
    for known_key, user in settings.api_keys.items():
        if api_key and secrets.compare_digest(api_key.encode(), known_key.encode()):
            return user
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Missing or unknown API key ({API_KEY_HEADER} header)")


def build_mcp_connector(settings: Settings, user: str) -> MCPConnector:
    issuer = (McpTokenIssuer(settings.mcp_token_signing_key.get_secret_value(), settings.mcp_token_issuer,
                             settings.mcp_token_audience, settings.mcp_token_ttl_seconds)
              if settings.mcp_token_signing_key else None)

    def open_mcp(sampling_callback=None, elicitation_callback=None, scopes: tuple[str, ...] = READ_SCOPES):
        auth = McpTokenAuth(issuer, user, scopes) if issuer else None
        return connect_to_mcp(settings.mcp_server_url, settings.mcp_timeout_seconds, sampling_callback,
                              elicitation_callback, auth)

    return open_mcp


CurrentUserDep = Annotated[str, Depends(get_current_user)]


def get_mcp_connector(settings: Annotated[Settings, Depends(get_settings)], user: CurrentUserDep) -> MCPConnector:
    return build_mcp_connector(settings, user)


def get_service_mcp_connector(settings: Annotated[Settings, Depends(get_settings)]) -> MCPConnector:
    """For the AI server's own checks (/ready): signed as the agent, not a person."""
    return build_mcp_connector(settings, AGENT_CLIENT_ID)


SettingsDep = Annotated[Settings, Depends(get_settings)]
ModelRouterDep = Annotated[ModelRouter, Depends(get_model_router)]
MCPConnectorDep = Annotated[MCPConnector, Depends(get_mcp_connector)]
ServiceMCPConnectorDep = Annotated[MCPConnector, Depends(get_service_mcp_connector)]
TracerDep = Annotated[InvestigationTracer, Depends(get_tracer)]


@dataclass(frozen=True)
class InvestigationDependencies:
    """Everything an investigation endpoint needs, resolved once per request."""

    settings: Settings
    models: ModelRouter
    open_mcp: MCPConnector
    tracer: InvestigationTracer
    user: str


def get_investigation_dependencies(
    settings: SettingsDep, models: ModelRouterDep, open_mcp: MCPConnectorDep, tracer: TracerDep, user: CurrentUserDep,
) -> InvestigationDependencies:
    return InvestigationDependencies(settings, models, open_mcp, tracer, user)


InvestigationDependenciesDep = Annotated[InvestigationDependencies, Depends(get_investigation_dependencies)]
ActionRegistryDep = Annotated[ActionRegistry, Depends(get_action_registry)]
