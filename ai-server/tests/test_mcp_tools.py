import pytest
from langchain_core.messages import ToolMessage

from mcp_client import list_all_tools, to_langchain_tool
from tests.fakes import PAYMENT_CRASHLOOP, build_fake_mcp_server, fake_connector

pytestmark = pytest.mark.anyio


@pytest.fixture
async def tools_by_name():
    async with fake_connector(build_fake_mcp_server(PAYMENT_CRASHLOOP))() as mcp_client:
        yield {tool.name: to_langchain_tool(mcp_client, tool) for tool in await list_all_tools(mcp_client)}


async def test_mcp_tools_become_langchain_tools(tools_by_name):
    assert {"list_pods", "get_pod_logs", "get_metrics"} <= set(tools_by_name)
    assert tools_by_name["get_pod_logs"].description == "Pod logs."
    assert "pod" in tools_by_name["get_pod_logs"].args


async def test_tool_call_goes_through_mcp(tools_by_name):
    output = await tools_by_name["list_pods"].ainvoke({"app": "payment-service"})
    assert "CrashLoopBackOff" in output


async def test_mcp_tool_error_becomes_error_tool_message(tools_by_name):
    tool_call = {"name": "get_pod_logs", "args": {"pod": "order-service-a", "previous": True},
                 "id": "c1", "type": "tool_call"}
    message = await tools_by_name["get_pod_logs"].ainvoke(tool_call)
    assert isinstance(message, ToolMessage)
    assert message.status == "error"
    assert "no previous" in message.content
