"""Phase 22: one AI server, several MCP servers (directly or behind a gateway)."""

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from mcp_client.connection import MCPUnavailableError, connect_to_mcp_servers
from mcp_client.langchain_tools import extract_result_text
from mcp_client.server_group import DuplicateToolError

pytestmark = pytest.mark.anyio

READ_ONLY = ToolAnnotations(read_only_hint=True)
TIMEOUT_SECONDS = 10


def kubernetes_server() -> MCPServer:
    server = MCPServer("k8s")

    @server.tool(annotations=READ_ONLY)
    def list_pods() -> str:
        """Pods."""
        return "pods from k8s"

    @server.resource("runbook://{service}")
    def runbook(service: str) -> str:
        return f"runbook of {service} from k8s"

    return server


def prometheus_server() -> MCPServer:
    server = MCPServer("prometheus")

    @server.tool(annotations=READ_ONLY)
    def get_metrics() -> str:
        """Metrics."""
        return "metrics from prometheus"

    return server


def gateway_like_server() -> MCPServer:
    """One server whose tools and resources carry the target names, as agentgateway lists them."""
    server = MCPServer("gateway")

    @server.tool(name="k8s_list_pods", annotations=READ_ONLY)
    def list_pods() -> str:
        """Pods."""
        return "pods via gateway"

    @server.tool(name="prometheus_get_metrics", annotations=READ_ONLY)
    def get_metrics() -> str:
        """Metrics."""
        return "metrics via gateway"

    @server.resource("k8s+runbook://{service}")
    def runbook(service: str) -> str:
        return f"runbook of {service} via gateway"

    return server


async def test_tools_of_all_servers_are_merged_and_routed_to_their_owner():
    servers = {"k8s": kubernetes_server(), "prometheus": prometheus_server()}
    async with connect_to_mcp_servers(servers, TIMEOUT_SECONDS) as group:
        names = {tool.name for tool in (await group.list_tools()).tools}
        pods = extract_result_text(await group.call_tool("list_pods", {}))
        metrics = extract_result_text(await group.call_tool("get_metrics", {}))
        templates = [t.uri_template for t in (await group.list_resource_templates()).resource_templates]
        runbook = (await group.read_resource("runbook://payment-service")).contents[0].text
    assert names == {"list_pods", "get_metrics"}
    assert (pods, metrics) == ("pods from k8s", "metrics from prometheus")
    assert templates == ["runbook://{service}"] and runbook == "runbook of payment-service from k8s"


async def test_gateway_names_are_mapped_back_so_the_agent_keeps_the_servers_names():
    async with connect_to_mcp_servers({"gateway": gateway_like_server()}, TIMEOUT_SECONDS,
                                      gateway_targets=["k8s", "prometheus"]) as group:
        names = {tool.name for tool in (await group.list_tools()).tools}
        metrics = extract_result_text(await group.call_tool("get_metrics", {}))
        templates = [t.uri_template for t in (await group.list_resource_templates()).resource_templates]
        runbook = (await group.read_resource("runbook://payment-service")).contents[0].text
    assert names == {"list_pods", "get_metrics"} and metrics == "metrics via gateway"
    assert templates == ["runbook://{service}"] and runbook == "runbook of payment-service via gateway"


async def test_same_tool_on_two_servers_is_refused():
    with pytest.raises(DuplicateToolError, match="'list_pods' is offered by both MCP servers 'a' and 'b'"):
        async with connect_to_mcp_servers({"a": kubernetes_server(), "b": kubernetes_server()}, TIMEOUT_SECONDS):
            pass


async def test_unreachable_server_is_named():
    servers = {"k8s": kubernetes_server(), "prometheus": "http://127.0.0.1:9/mcp"}
    with pytest.raises(MCPUnavailableError, match="127.0.0.1:9/mcp"):
        async with connect_to_mcp_servers(servers, TIMEOUT_SECONDS):
            pass
