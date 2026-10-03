from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from mcp import Client

from actions import ActionRegistry
from agent import ModelRouter, create_model_router
from config import Settings, get_settings
from mcp_client import connect_to_mcp
from tracing import InvestigationTracer, create_tracer

# Opens an MCP session; optionally with sampling / elicitation callbacks.
MCPConnector = Callable[..., AbstractAsyncContextManager[Client]]


@lru_cache
def get_action_registry() -> ActionRegistry:
    return ActionRegistry(get_settings().approval_timeout_seconds)


@lru_cache
def get_model_router() -> ModelRouter:
    return create_model_router(get_settings())


def get_tracer(settings: Annotated[Settings, Depends(get_settings)]) -> InvestigationTracer:
    # Langfuse keeps one client per public key, so this is cheap after the first call.
    return create_tracer(settings)


def get_mcp_connector(settings: Annotated[Settings, Depends(get_settings)]) -> MCPConnector:
    return lambda sampling_callback=None, elicitation_callback=None: connect_to_mcp(
        settings.mcp_server_url, settings.mcp_timeout_seconds, sampling_callback, elicitation_callback)


SettingsDep = Annotated[Settings, Depends(get_settings)]
ModelRouterDep = Annotated[ModelRouter, Depends(get_model_router)]
MCPConnectorDep = Annotated[MCPConnector, Depends(get_mcp_connector)]
TracerDep = Annotated[InvestigationTracer, Depends(get_tracer)]


@dataclass(frozen=True)
class InvestigationDependencies:
    """Everything an investigation endpoint needs, resolved once per request."""

    settings: Settings
    models: ModelRouter
    open_mcp: MCPConnector
    tracer: InvestigationTracer


def get_investigation_dependencies(
    settings: SettingsDep, models: ModelRouterDep, open_mcp: MCPConnectorDep, tracer: TracerDep
) -> InvestigationDependencies:
    return InvestigationDependencies(settings, models, open_mcp, tracer)


InvestigationDependenciesDep = Annotated[InvestigationDependencies, Depends(get_investigation_dependencies)]
ActionRegistryDep = Annotated[ActionRegistry, Depends(get_action_registry)]
