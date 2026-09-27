from dataclasses import asdict

from fastapi import APIRouter

from agent import build_investigation_graph, run_investigation
from api.dependencies import ChatModelDep, MCPConnectorDep, SettingsDep
from api.schemas import (
    InvestigateRequest,
    InvestigateResponse,
    StatusResponse,
    ToolDescription,
    ToolsResponse,
)
from mcp_client import list_all_tools, load_langchain_tools

router = APIRouter()


@router.get("/health", response_model=StatusResponse)
async def health() -> StatusResponse:
    return StatusResponse(status="ok")


@router.get("/ready", response_model=StatusResponse)
async def ready(open_mcp: MCPConnectorDep) -> StatusResponse:
    async with open_mcp() as mcp_client:
        await list_all_tools(mcp_client)
    return StatusResponse(status="ready")


@router.get("/tools", response_model=ToolsResponse)
async def list_tools(open_mcp: MCPConnectorDep) -> ToolsResponse:
    async with open_mcp() as mcp_client:
        tools = await list_all_tools(mcp_client)
    return ToolsResponse(tools=[
        ToolDescription(name=t.name, description=t.description or "", input_schema=t.input_schema)
        for t in tools
    ])


@router.post("/investigate", response_model=InvestigateResponse)
async def investigate(
    request: InvestigateRequest,
    settings: SettingsDep,
    chat_model: ChatModelDep,
    open_mcp: MCPConnectorDep,
) -> InvestigateResponse:
    async with open_mcp() as mcp_client:
        tools = await load_langchain_tools(mcp_client)
        graph = build_investigation_graph(chat_model, tools)
        result = await run_investigation(graph, request.question, settings.max_agent_steps)
    return InvestigateResponse.model_validate(asdict(result))
