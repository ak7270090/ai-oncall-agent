from fastapi import APIRouter

from agent import MCPToolbox, build_investigation_graph, run_investigation
from api.dependencies import ChatModelDep, MCPConnectorDep, SettingsDep, TracerDep
from api.schemas import (
    EvidenceResponse,
    InvestigateRequest,
    InvestigateResponse,
    StatusResponse,
    ToolDescription,
    ToolsResponse,
)
from constants import HEALTH_STATUS_OK, READY_STATUS
from mcp_client import list_all_tools, to_langchain_tool

router = APIRouter()


@router.get("/health", response_model=StatusResponse)
async def health() -> StatusResponse:
    return StatusResponse(status=HEALTH_STATUS_OK)


@router.get("/ready", response_model=StatusResponse)
async def ready(open_mcp: MCPConnectorDep) -> StatusResponse:
    async with open_mcp() as mcp_client:
        await list_all_tools(mcp_client)
    return StatusResponse(status=READY_STATUS)


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
    tracer: TracerDep,
) -> InvestigateResponse:
    async with open_mcp() as mcp_client:
        tools = await list_all_tools(mcp_client)
        graph = build_investigation_graph(
            chat_model,
            MCPToolbox(mcp_client, tools),
            [to_langchain_tool(mcp_client, tool) for tool in tools],
            settings,
        )
        result = await run_investigation(graph, request.question, settings.max_follow_up_rounds, tracer)
    return InvestigateResponse(
        answer=result.answer,
        report=result.report,
        scope=result.scope,
        namespace=result.namespace,
        evidence=[
            EvidenceResponse(step=e.step, source=e.source, arguments=e.arguments, error=e.error,
                             result=e.result if request.include_evidence_results else None)
            for e in result.evidence
        ],
        notes=result.notes,
        steps=result.steps,
        llm_calls=result.llm_calls,
        follow_up_limit_reached=result.follow_up_limit_reached,
        trace_id=result.trace_id,
        trace_url=result.trace_url,
    )
