import logging

import pytest
from fastapi.testclient import TestClient

from config import Settings, get_settings
from investigation.evidence.mcp_toolbox import MCPToolbox
from investigation.service import run_investigation
from investigation.workflow.graph import build_investigation_graph
from llm.dependencies import get_model_router
from llm.model_router import ModelRouter
from main import app
from mcp_client.dependencies import get_mcp_connector
from mcp_client.langchain_tools import list_all_resource_templates, list_all_tools, to_langchain_tool
from mcp_client.tool_policy import split_read_only
from tests.fakes import (
    PAYMENT_DOWN,
    build_fake_mcp_server,
    fake_connector,
    scripted_model,
)


async def investigate(settings: Settings, **server_options):
    server = build_fake_mcp_server(PAYMENT_DOWN, **server_options)
    async with fake_connector(server)() as mcp_client:
        tools = await list_all_tools(mcp_client)
        toolbox = MCPToolbox(mcp_client, tools, resource_templates=await list_all_resource_templates(mcp_client))
        graph = build_investigation_graph(ModelRouter.single(scripted_model()), toolbox,
                                          [to_langchain_tool(mcp_client, t) for t in tools], settings)
        return await run_investigation(graph, "Checkout is failing", settings.max_follow_up_rounds)


def knowledge(result) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for e in result.evidence:
        if e.source in ("runbook", "topology"):
            found.setdefault(e.source, []).append(e.arguments["uri"])
    return found


@pytest.mark.anyio
async def test_service_map_and_runbooks_of_flagged_services_become_evidence():
    result = await investigate(Settings(_env_file=None))
    assert knowledge(result) == {"topology": ["topology://shop"], "runbook": ["runbook://payment-service"]}
    [runbook] = [e for e in result.evidence if e.source == "runbook"]
    assert "payments-db" in runbook.result
    # order-service is flagged too but has no runbook: noted, not kept as evidence
    assert any("no runbook for runbook://order-service" in note for note in result.notes)


@pytest.mark.anyio
@pytest.mark.parametrize("settings, server_options", [
    (Settings(_env_file=None, use_service_knowledge=False), {}),
    (Settings(_env_file=None), {"with_knowledge": False}),
])
async def test_no_knowledge_when_switched_off_or_not_offered(settings, server_options):
    result = await investigate(settings, **server_options)
    assert knowledge(result) == {}
    assert not any("runbook" in note for note in result.notes)


@pytest.mark.anyio
async def test_only_read_only_tools_are_kept():
    async with fake_connector(build_fake_mcp_server(PAYMENT_DOWN, with_write_tool=True))() as mcp_client:
        allowed, refused = split_read_only(await list_all_tools(mcp_client))
    assert [t.name for t in refused] == ["delete_pod"]
    assert "delete_pod" not in {t.name for t in allowed} and "list_pods" in {t.name for t in allowed}


def test_api_lists_annotations_and_keeps_write_tools_from_the_agent(caplog):
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    app.dependency_overrides[get_model_router] = lambda: ModelRouter.single(scripted_model())
    app.dependency_overrides[get_mcp_connector] = lambda: fake_connector(
        build_fake_mcp_server(PAYMENT_DOWN, with_write_tool=True))
    try:
        client = TestClient(app)
        tools = {t["name"]: t for t in client.get("/tools").json()["tools"]}
        with caplog.at_level(logging.WARNING):
            assert client.post("/investigate", json={"question": "Checkout is failing"}).status_code == 200
    finally:
        app.dependency_overrides.clear()
    assert tools["delete_pod"]["read_only"] is False and tools["delete_pod"]["destructive"] is True
    assert tools["list_pods"]["read_only"] is True
    assert "delete_pod" in caplog.text
