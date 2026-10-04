"""Phase 22: one codebase, two MCP servers (Kubernetes, Prometheus)."""

import pytest
from mcp import Client

from config import Settings
from constants import WRITE_TOOLS, Toolset
from server import create_server

pytestmark = pytest.mark.anyio

KUBERNETES_TOOLS = {"list_pods", "get_pod_status", "get_pod_logs", "list_deployments", "get_deployment", "list_events"}
PROMETHEUS_TOOLS = {"get_service_overview", "get_metrics"}


async def served(settings: Settings) -> tuple[set[str], int]:
    async with Client(create_server(settings)) as client:
        tools = {tool.name for tool in (await client.list_tools()).tools}
        templates = (await client.list_resource_templates()).resource_templates
    return tools, len(templates)


@pytest.mark.parametrize("toolsets, expected_tools, has_resources", [
    ([Toolset.KUBERNETES], KUBERNETES_TOOLS | WRITE_TOOLS, True),
    ([Toolset.PROMETHEUS], PROMETHEUS_TOOLS, False),
    ([Toolset.KUBERNETES, Toolset.PROMETHEUS], KUBERNETES_TOOLS | PROMETHEUS_TOOLS | WRITE_TOOLS, True),
])
async def test_each_toolset_serves_only_its_tools(toolsets, expected_tools, has_resources):
    settings = Settings(_env_file=None, backend="fake", toolsets=toolsets, enable_write_tools=True)
    tools, templates = await served(settings)
    assert tools == expected_tools
    assert (templates > 0) is has_resources


async def test_prometheus_server_needs_no_kubernetes_credentials():
    settings = Settings(_env_file=None, backend="kubernetes", toolsets=[Toolset.PROMETHEUS],
                        kubeconfig_path="no/such/kubeconfig", operator_kubeconfig_path="no/such/kubeconfig")
    tools, _ = await served(settings)
    assert tools == PROMETHEUS_TOOLS
