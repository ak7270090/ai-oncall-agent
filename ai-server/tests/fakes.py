"""Stand-ins for the LLM and the MCP server. Nothing is imported from mcp-server/."""

from itertools import count

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from mcp_client import connect_to_mcp

TEST_MCP_TIMEOUT_SECONDS = 5
_call_ids = count()


def build_fake_mcp_server() -> MCPServer:
    server = MCPServer("fake-mcp-server")

    @server.tool()
    def get_pod_status(service: str) -> dict:
        """Pod status for a service."""
        return {"service": service, "status": "CrashLoopBackOff"}

    @server.tool()
    def get_logs(service: str) -> dict:
        """Recent logs for a service."""
        raise ToolError(f"no logs for {service}")

    return server


def fake_connector(server: MCPServer):
    return lambda: connect_to_mcp(server, TEST_MCP_TIMEOUT_SECONDS)


def tool_call_message(*calls: tuple[str, dict]) -> AIMessage:
    return AIMessage(content="", tool_calls=[
        {"name": name, "args": args, "id": f"call_{next(_call_ids)}", "type": "tool_call"}
        for name, args in calls
    ])


class ScriptedChatModel(GenericFakeChatModel):
    """Replies with the given messages in order; tool binding is a no-op."""

    def bind_tools(self, tools, **kwargs):
        return self


def scripted_model(*replies: AIMessage | str) -> ScriptedChatModel:
    return ScriptedChatModel(messages=iter(replies))


def endless_tool_calls_model() -> ScriptedChatModel:
    def forever():
        while True:
            yield tool_call_message(("get_pod_status", {"service": "payment-service"}))
    return ScriptedChatModel(messages=forever())
