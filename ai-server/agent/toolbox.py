import json
from typing import Any

from mcp import Client
from mcp.types import Tool

from agent.models import Evidence
from mcp_client.tools import result_text


class MCPToolbox:
    """Calls MCP tools by name for the deterministic investigation steps.
    Failures are returned as evidence, never raised: a failed check is information too."""

    def __init__(self, mcp_client: Client, tools: list[Tool]):
        self._client = mcp_client
        self._names = {tool.name for tool in tools}

    def has(self, name: str) -> bool:
        return name in self._names

    async def call(self, name: str, arguments: dict[str, Any], step: str) -> Evidence:
        try:
            result = await self._client.call_tool(name, arguments)
        except Exception as error:
            return Evidence(source=name, arguments=arguments, error=f"MCP call failed: {error}", step=step)
        text = result_text(result)
        if result.is_error:
            return Evidence(source=name, arguments=arguments, error=text, step=step)
        return Evidence(source=name, arguments=arguments, result=_parse(text), step=step)


def _parse(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text
