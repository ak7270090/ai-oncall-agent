from langchain_core.tools import StructuredTool, ToolException
from mcp import Client
from mcp.types import CallToolResult, TextContent, Tool

from mcp_client.progress import ToolProgressCallback, progress_callback_for


def extract_result_text(result: CallToolResult) -> str:
    return "\n".join(block.text for block in result.content if isinstance(block, TextContent))


async def list_all_tools(mcp_client: Client) -> list[Tool]:
    tools: list[Tool] = []
    cursor = None
    while True:
        page = await mcp_client.list_tools(cursor=cursor)
        tools.extend(page.tools)
        cursor = page.next_cursor
        if not cursor:
            return tools


def to_langchain_tool(mcp_client: Client, tool: Tool, on_progress: ToolProgressCallback | None = None) -> StructuredTool:
    async def call_mcp_tool(**arguments) -> str:
        result = await mcp_client.call_tool(
            tool.name, arguments, progress_callback=progress_callback_for(tool.name, on_progress))
        if result.is_error:
            raise ToolException(extract_result_text(result))
        return extract_result_text(result)

    return StructuredTool.from_function(
        coroutine=call_mcp_tool,
        name=tool.name,
        description=tool.description or "",
        args_schema=tool.input_schema,
        handle_tool_error=True,
    )

