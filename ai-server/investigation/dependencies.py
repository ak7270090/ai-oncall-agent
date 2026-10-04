from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from auth.dependencies import CurrentUserDep
from config import Settings, SettingsDep
from llm.dependencies import ModelRouterDep
from llm.model_router import ModelRouter
from mcp_client.dependencies import MCPConnector, MCPConnectorDep
from tracing import InvestigationTracer, TracerDep


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
