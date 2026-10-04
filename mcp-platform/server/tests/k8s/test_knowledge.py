import json

import pytest
from mcp import Client
from mcp.shared.exceptions import MCPError
from mcp_types import ResourceTemplateReference

from k8s.config import K8sServerSettings
from k8s.server import build_k8s_server
from prometheus.config import PrometheusServerSettings
from prometheus.server import build_prometheus_server

pytestmark = pytest.mark.anyio
READ_ONLY_TOOLS = {"list_pods", "get_pod_status", "get_pod_logs", "list_deployments", "get_deployment",
                   "list_events", "get_service_overview", "get_metrics"}
SETTINGS = K8sServerSettings(_env_file=None, backend="fake")


@pytest.fixture
async def client():
    async with Client(build_k8s_server(K8sServerSettings(_env_file=None, backend="fake"))) as mcp_client:
        yield mcp_client


async def read(client, uri: str) -> str:
    return (await client.read_resource(uri)).contents[0].text


async def test_resource_templates_are_listed(client):
    templates = {t.uri_template: t.mime_type for t in (await client.list_resource_templates()).resource_templates}
    assert templates == {"runbook://{service}": "text/markdown", "topology://{namespace}": "application/json",
                         "k8s://{namespace}/deployments/{name}": "application/json"}


async def test_runbook_and_topology_hold_the_team_knowledge(client):
    assert "payments-db" in await read(client, "runbook://payment-service")
    topology = json.loads(await read(client, "topology://shop"))
    assert topology["payment-service"]["calls"] == ["payments-db"]


async def test_deployment_spec_names_env_vars_but_never_their_values(client):
    spec = json.loads(await read(client, "k8s://shop/deployments/payment-service"))
    container = spec["containers"][0]
    assert container["env_names"] == ["DB_HOST", "DB_PASSWORD", "FAULT_MODE"]
    assert container["env_from"] == ["configMap/payment-service-config", "secret/payment-service-secrets"]
    assert container["cpu_limit"] == "250m"
    assert "value" not in json.dumps(spec).lower()


@pytest.mark.parametrize("uri, message", [
    ("runbook://traffic-generator", "No runbook for 'traffic-generator'"),
    ("topology://kube-system", "not allowed"),
    ("k8s://kube-system/deployments/coredns", "not allowed"),
    ("runbook://..%2Fsecrets", "Unknown resource"),  # the SDK rejects path traversal itself
    ("runbook://Payment_Service", "Invalid service"),
])
async def test_unknown_or_forbidden_resources_are_refused(client, uri, message):
    with pytest.raises(MCPError, match=message):
        await read(client, uri)


@pytest.mark.parametrize("template, argument, typed, context, expected", [
    ("runbook://{service}", "service", "pay", None, ["payment-service", "payments-db"]),
    ("topology://{namespace}", "namespace", "", None, ["shop"]),
    ("k8s://{namespace}/deployments/{name}", "name", "pay", {"namespace": "shop"}, ["payment-service"]),
    ("k8s://{namespace}/deployments/{name}", "name", "", {"namespace": "kube-system"}, []),
])
async def test_resource_arguments_are_completed(client, template, argument, typed, context, expected):
    reference = ResourceTemplateReference(type="ref/resource", uri=template)
    result = await client.complete(reference, {"name": argument, "value": typed}, context)
    assert result.completion.values == expected


async def test_every_tool_is_annotated_read_only():
    tools = []
    for server in (build_k8s_server(SETTINGS),
                   build_prometheus_server(PrometheusServerSettings(_env_file=None, backend="fake"))):
        async with Client(server) as mcp_client:
            tools += (await mcp_client.list_tools()).tools
    assert {t.name for t in tools} == READ_ONLY_TOOLS
    for tool in tools:
        assert tool.annotations.read_only_hint is True and tool.annotations.destructive_hint is False
