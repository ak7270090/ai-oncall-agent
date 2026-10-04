"""Liveness, readiness and the MCP tools on offer: /health, /ready, /tools."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from auth.constants import WRITE_SCOPES
from auth.dependencies import CurrentUserDep
from constants import HEALTH_STATUS_OK, READY_STATUS
from mcp_client.dependencies import MCPConnectorDep, ServiceMCPConnectorDep
from mcp_client.langchain_tools import list_all_tools
from mcp_client.tool_policy import is_read_only

router = APIRouter(tags=["health"])


class StatusResponse(BaseModel):
    status: str


class ToolDescription(BaseModel):
    name: str
    description: str
    input_schema: dict
    read_only: bool = Field(description="Annotated read-only by the MCP server; only these are given to the agent")
    destructive: bool | None = Field(default=None, description="The server's destructiveHint, if set")


class ToolsResponse(BaseModel):
    tools: list[ToolDescription]


@router.get("/health", response_model=StatusResponse)
async def health() -> StatusResponse:
    return StatusResponse(status=HEALTH_STATUS_OK)


@router.get("/ready", response_model=StatusResponse)
async def ready(open_mcp: ServiceMCPConnectorDep) -> StatusResponse:
    async with open_mcp() as mcp_client:
        await list_all_tools(mcp_client)
    return StatusResponse(status=READY_STATUS)


@router.get("/tools", response_model=ToolsResponse)
async def list_tools(open_mcp: MCPConnectorDep, _: CurrentUserDep) -> ToolsResponse:
    """Every tool, write tools included (listed with a write-scoped token)."""
    async with open_mcp(scopes=WRITE_SCOPES) as mcp_client:
        tools = await list_all_tools(mcp_client)
    return ToolsResponse(tools=[
        ToolDescription(name=t.name, description=t.description or "", input_schema=t.input_schema,
                        read_only=is_read_only(t),
                        destructive=t.annotations.destructive_hint if t.annotations else None)
        for t in tools
    ])
