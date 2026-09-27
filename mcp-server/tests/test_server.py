import pytest
from mcp import Client
from starlette.testclient import TestClient

from config import Settings
from server import create_server, transport_security

KUBERNETES_TOOLS = {"list_pods", "get_pod_status", "get_pod_logs", "list_deployments", "get_deployment", "list_events"}
OBSERVABILITY_TOOLS = {"get_service_overview", "get_metrics"}
CRASHING_POD = "payment-service-7d9f8c6b5-2xkqp"

pytestmark = pytest.mark.anyio


def fake_settings(**overrides) -> Settings:
    return Settings(_env_file=None, backend="fake", **overrides)


@pytest.fixture
def server():
    return create_server(fake_settings())


@pytest.fixture
async def client(server):
    async with Client(server) as mcp_client:
        yield mcp_client


async def call(client, tool: str, arguments: dict | None = None) -> dict:
    result = await client.call_tool(tool, arguments or {})
    assert not result.is_error, result.content
    return result.structured_content


async def call_error(client, tool: str, arguments: dict) -> str:
    result = await client.call_tool(tool, arguments)
    assert result.is_error
    return result.content[0].text


def test_health_route(server):
    with TestClient(server.streamable_http_app()) as http:
        assert http.get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize("backend", ["fake", "kubernetes"])
async def test_both_backends_offer_the_same_tools(backend):
    async with Client(create_server(Settings(_env_file=None, backend=backend))) as mcp_client:
        names = {t.name for t in (await mcp_client.list_tools()).tools}
    assert names == KUBERNETES_TOOLS | OBSERVABILITY_TOOLS


async def test_every_tool_is_described_and_has_output_schema(client):
    for tool in (await client.list_tools()).tools:
        assert tool.description, tool.name
        assert tool.output_schema, tool.name


async def test_namespace_defaults_to_configured_namespace(client):
    tools = {t.name: t for t in (await client.list_tools()).tools}
    assert tools["list_pods"].input_schema["properties"]["namespace"]["default"] == "shop"


async def test_list_pods_shows_crashloop(client):
    pods = (await call(client, "list_pods", {"app": "payment-service"}))["pods"]
    assert {p["status"] for p in pods} == {"CrashLoopBackOff"}
    assert not any(p["ready"] for p in pods)


async def test_get_pod_status_explains_last_crash(client):
    pod = await call(client, "get_pod_status", {"pod": CRASHING_POD})
    container = pod["containers"][0]
    assert (container["reason"], container["last_exit_code"]) == ("CrashLoopBackOff", 1)


async def test_previous_logs_contain_the_crash(client):
    logs = await call(client, "get_pod_logs", {"pod": CRASHING_POD, "previous": True, "lines": 2})
    assert len(logs["lines"]) == 2
    assert "exit code 1" in logs["lines"][-1]


async def test_get_deployment_shows_rollout_history(client):
    deployment = await call(client, "get_deployment", {"name": "payment-service"})
    assert [r["revision"] for r in deployment["revisions"]] == [2, 1]
    assert deployment["revisions"][0]["ready_replicas"] == 0


async def test_list_deployments(client):
    names = {d["name"] for d in (await call(client, "list_deployments"))["deployments"]}
    assert names == {"payment-service", "order-service", "user-service"}


async def test_list_events_warnings_only(client):
    events = (await call(client, "list_events", {"limit": 5}))["events"]
    assert events and all(e["type"] == "Warning" for e in events)


async def test_namespace_outside_allowlist_rejected(client):
    message = await call_error(client, "list_pods", {"namespace": "kube-system"})
    assert "not allowed" in message


async def test_unknown_pod_is_a_tool_error(client):
    assert "Not found" in await call_error(client, "get_pod_status", {"pod": "nope"})


async def test_log_line_limit_enforced_by_schema(client):
    await call_error(client, "get_pod_logs", {"pod": CRASHING_POD, "lines": 0})


async def test_service_overview_flags_failing_services(client):
    services = {s["service"]: s for s in (await call(client, "get_service_overview"))["services"]}
    assert services["payment-service"]["error_rate"] == 1.0
    assert services["user-service"]["error_rate"] < 0.01


async def test_metric_history_shows_error_spike(client):
    series = await call(client, "get_metrics", {"service": "payment-service", "metric": "error_rate"})
    values = [s["value"] for s in series["samples"]]
    assert values[0] < 0.01 and values[-1] == 1.0
    assert series["unit"].startswith("ratio")


async def test_metric_names_are_an_enum(client):
    tools = {t.name: t for t in (await client.list_tools()).tools}
    assert "error_count" in tools["get_metrics"].input_schema["properties"]["metric"]["enum"]


async def test_service_name_that_could_inject_promql_is_rejected(client):
    await call_error(client, "get_metrics", {"service": 'x",namespace="kube-system', "metric": "error_rate"})


async def test_metrics_namespace_outside_allowlist_rejected(client):
    assert "not allowed" in await call_error(client, "get_service_overview", {"namespace": "kube-system"})


def test_transport_security_uses_sdk_default_without_allowed_hosts():
    assert transport_security(fake_settings()) is None


def test_transport_security_enforces_allowed_hosts():
    security = transport_security(fake_settings(allowed_hosts=["mcp-server:*"]))
    assert security.enable_dns_rebinding_protection
    assert security.allowed_hosts == ["mcp-server:*"]


def test_foreign_host_header_rejected(server):
    app = server.streamable_http_app(transport_security=transport_security(fake_settings(allowed_hosts=["mcp-server:*"])))
    with TestClient(app) as http:
        response = http.post("/mcp", headers={"Host": "evil.example:9000"}, json={})
    assert response.status_code == 421
