"""The Prometheus MCP server (prometheus/server.py) on the fake backend."""

import pytest
from mcp import Client

from config import Settings
from prometheus.server import build_prometheus_server

PROMETHEUS_TOOLS = {"get_service_overview", "get_metrics"}

pytestmark = pytest.mark.anyio


def fake_settings(**overrides) -> Settings:
    return Settings(_env_file=None, backend="fake", **overrides)


async def call(client, tool: str, arguments: dict | None = None) -> dict:
    result = await client.call_tool(tool, arguments or {})
    assert not result.is_error, result.content
    return result.structured_content


async def call_error(client, tool: str, arguments: dict) -> str:
    result = await client.call_tool(tool, arguments)
    assert result.is_error
    return result.content[0].text


@pytest.fixture
async def client():
    async with Client(build_prometheus_server(fake_settings())) as mcp_client:
        yield mcp_client


async def test_serves_only_metric_tools_and_no_resources(client):
    names = {t.name for t in (await client.list_tools()).tools}
    templates = (await client.list_resource_templates()).resource_templates
    assert names == PROMETHEUS_TOOLS and not templates


async def test_needs_no_kubernetes_credentials():
    settings = Settings(_env_file=None, backend="kubernetes", kubeconfig_path="no/such/kubeconfig",
                        operator_kubeconfig_path="no/such/kubeconfig")
    async with Client(build_prometheus_server(settings)) as mcp_client:
        names = {t.name for t in (await mcp_client.list_tools()).tools}
    assert names == PROMETHEUS_TOOLS


async def test_every_tool_is_described_and_has_output_schema(client):
    for tool in (await client.list_tools()).tools:
        assert tool.description, tool.name
        assert tool.output_schema, tool.name


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


async def test_metric_history_is_summarised_for_the_model(client):
    series = await call(client, "get_metrics", {"service": "payment-service", "metric": "error_rate"})
    assert (series["latest"], series["max"]) == (1.0, 1.0)
    assert series["min"] == 0.002


async def test_metric_summary_is_part_of_the_output_schema(client):
    tools = {t.name: t for t in (await client.list_tools()).tools}
    assert {"latest", "min", "max"} <= tools["get_metrics"].output_schema["properties"].keys()


async def test_service_overview_reports_progress_per_query(client):
    updates = []

    async def on_progress(progress, total, message):
        updates.append((progress, total, message))

    result = await client.call_tool("get_service_overview", {}, progress_callback=on_progress)
    assert not result.is_error
    assert [(progress, total) for progress, total, _ in updates] == [(1, 3), (2, 3), (3, 3)]
    assert updates[0][2].startswith("request_rate queried in")
