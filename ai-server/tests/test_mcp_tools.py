import pytest
from langchain_core.messages import ToolMessage

from mcp_client import load_langchain_tools
from tests.fakes import build_fake_mcp_server, fake_connector

pytestmark = pytest.mark.anyio


@pytest.fixture
async def tools_by_name():
    async with fake_connector(build_fake_mcp_server())() as mcp_client:
        yield {tool.name: tool for tool in await load_langchain_tools(mcp_client)}


async def test_mcp_tools_become_langchain_tools(tools_by_name):
    assert set(tools_by_name) == {"get_pod_status", "get_logs"}
    assert tools_by_name["get_pod_status"].description == "Pod status for a service."
    assert "service" in tools_by_name["get_pod_status"].args


async def test_tool_call_goes_through_mcp(tools_by_name):
    output = await tools_by_name["get_pod_status"].ainvoke({"service": "payment-service"})
    assert "CrashLoopBackOff" in output


async def test_mcp_tool_error_becomes_error_tool_message(tools_by_name):
    tool_call = {"name": "get_logs", "args": {"service": "x"}, "id": "c1", "type": "tool_call"}
    message = await tools_by_name["get_logs"].ainvoke(tool_call)
    assert isinstance(message, ToolMessage)
    assert message.status == "error"
    assert "no logs for x" in message.content
