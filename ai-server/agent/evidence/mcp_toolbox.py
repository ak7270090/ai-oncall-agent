import json
from typing import Any

from langchain_core.messages import BaseMessage, ToolMessage
from mcp import Client
from mcp.types import Tool

from agent.models import Evidence
from constants import Step
from mcp_client.tools import result_text


class MCPToolbox:
    """Calls MCP tools by name for the fixed investigation steps.
    Failures are returned as evidence, never raised: a failed check is information too."""

    def __init__(self, mcp_client: Client, tools: list[Tool]):
        self._client = mcp_client
        self._names = {tool.name for tool in tools}

    def has(self, name: str) -> bool:
        return name in self._names

    async def call(self, name: str, arguments: dict[str, Any], step: Step) -> Evidence:
        try:
            result = await self._client.call_tool(name, arguments)
        except Exception as error:
            return Evidence(source=name, arguments=arguments, error=f"MCP call failed: {error}", step=step)
        text = result_text(result)
        if result.is_error:
            return Evidence(source=name, arguments=arguments, error=text, step=step)
        return Evidence(source=name, arguments=arguments, result=parse_tool_output(text), step=step)


def parse_tool_output(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def evidence_from_tool_messages(messages: list[BaseMessage], requested_calls: dict[str, dict]) -> list[Evidence]:
    """Turn the results of tool calls the LLM requested (ToolMessages) into Evidence."""
    evidence = []
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        call = requested_calls.get(message.tool_call_id, {})
        content = message.content if isinstance(message.content, str) else json.dumps(message.content)
        is_error = message.status == "error"
        evidence.append(Evidence(
            source=call.get("name", message.name or "unknown"),
            arguments=call.get("args", {}),
            result=None if is_error else parse_tool_output(content),
            error=content if is_error else None,
            step=Step.RUN_REQUESTED_TOOLS,
        ))
    return evidence
