import json

import pytest
from mcp import Client
from starlette.testclient import TestClient

from config import Settings
from server import create_server, transport_security

EXPECTED_TOOLS = {"list_deployments", "get_pod_status", "get_logs", "get_metrics"}

pytestmark = pytest.mark.anyio


@pytest.fixture
def server():
    return create_server(Settings(_env_file=None))


@pytest.fixture
async def client(server):
    async with Client(server) as mcp_client:
        yield mcp_client


def tool_payload(result) -> dict:
    assert not result.is_error, result.content
    return json.loads(result.content[0].text)


def test_health_route(server):
    with TestClient(server.streamable_http_app()) as http:
        assert http.get("/health").json() == {"status": "ok"}


def test_transport_security_uses_sdk_default_without_allowed_hosts():
    assert transport_security(Settings(_env_file=None)) is None


def test_transport_security_enforces_allowed_hosts():
    security = transport_security(Settings(_env_file=None, allowed_hosts=["mcp-server:*"]))
    assert security.enable_dns_rebinding_protection
    assert security.allowed_hosts == ["mcp-server:*"]


def test_foreign_host_header_rejected(server):
    app = server.streamable_http_app(
        transport_security=transport_security(Settings(_env_file=None, allowed_hosts=["mcp-server:*"]))
    )
    with TestClient(app) as http:
        response = http.post("/mcp", headers={"Host": "evil.example:9000"}, json={})
    assert response.status_code == 421


async def test_tools_are_discoverable(client):
    result = await client.list_tools()
    assert {t.name for t in result.tools} == EXPECTED_TOOLS
    for tool in result.tools:
        assert tool.description, f"{tool.name} needs a description the LLM can read"


async def test_service_arg_is_an_enum_in_the_schema(client):
    tools = {t.name: t for t in (await client.list_tools()).tools}
    service_schema = tools["get_pod_status"].input_schema["properties"]["service"]
    assert set(service_schema["enum"]) == {"payment-service", "order-service", "user-service"}
    assert tools["get_pod_status"].input_schema["required"] == ["service"]


async def test_list_deployments(client):
    data = tool_payload(await client.call_tool("list_deployments", {}))
    assert {d["name"] for d in data["deployments"]} == {
        "payment-service", "order-service", "user-service"
    }


async def test_list_deployments_unknown_namespace_is_empty(client):
    data = tool_payload(await client.call_tool("list_deployments", {"namespace": "nope"}))
    assert data["deployments"] == []


async def test_get_pod_status_shows_crashloop(client):
    data = tool_payload(await client.call_tool("get_pod_status", {"service": "payment-service"}))
    assert all(p["status"] == "CrashLoopBackOff" for p in data["pods"])


async def test_get_logs_respects_lines(client):
    data = tool_payload(await client.call_tool("get_logs", {"service": "payment-service", "lines": 3}))
    assert len(data["lines"]) == 3
    assert "exit code 1" in data["lines"][-1]


async def test_get_metrics(client):
    data = tool_payload(await client.call_tool(
        "get_metrics", {"service": "payment-service", "metric": "error_rate"}
    ))
    assert data["unit"] == "ratio"
    assert len(data["samples"]) == 5


async def test_unknown_service_is_a_tool_error(client):
    result = await client.call_tool("get_pod_status", {"service": "billing-service"})
    assert result.is_error


async def test_out_of_range_lines_is_a_tool_error(client):
    result = await client.call_tool("get_logs", {"service": "user-service", "lines": 0})
    assert result.is_error
    assert "lines" in result.content[0].text


async def test_lines_bounds_are_in_the_schema(client):
    tools = {t.name: t for t in (await client.list_tools()).tools}
    lines = tools["get_logs"].input_schema["properties"]["lines"]
    assert (lines["minimum"], lines["maximum"]) == (1, 200)
