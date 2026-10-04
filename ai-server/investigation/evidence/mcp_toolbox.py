import json
from typing import Any

from langchain_core.callbacks import AsyncCallbackManager
from langchain_core.messages import BaseMessage, ToolMessage
from langchain_core.runnables import ensure_config
from langchain_core.tools import ToolException
from mcp import Client
from mcp.types import Tool

from investigation.constants import Step
from investigation.models import Evidence
from mcp_client.constants import SUMMARIZE_ARGUMENT, McpResource
from mcp_client.langchain_tools import extract_result_text
from mcp_client.progress import ToolProgressCallback, progress_callback_for

JSON_MIME_TYPE = "application/json"


class MCPToolbox:
    """Calls MCP tools by name for the fixed investigation steps.
    Failures are returned as evidence, never raised: a failed check is information too."""

    def __init__(self, mcp_client: Client, tools: list[Tool], on_progress: ToolProgressCallback | None = None,
                 resource_templates: list[str] | None = None):
        self._client = mcp_client
        self._names = {tool.name for tool in tools}
        self._on_progress = on_progress
        self._resource_templates = set(resource_templates or [])

    def has(self, name: str) -> bool:
        return name in self._names

    def offers(self, template: McpResource) -> bool:
        return template in self._resource_templates

    async def call(self, name: str, arguments: dict[str, Any], step: Step) -> Evidence:
        run = await self._start_run(name, arguments, step)
        evidence = await self._call_untraced(name, arguments, step)
        if evidence.error and arguments.get(SUMMARIZE_ARGUMENT):
            # A summary is optional (it needs the client's LLM): retry for the raw lines.
            evidence = await self._call_untraced(name, {**arguments, SUMMARIZE_ARGUMENT: False}, step)
        return await self._finish_run(run, evidence)

    async def read_resource(self, template: McpResource, step: Step, **parameters: str) -> Evidence:
        """Read an MCP resource (e.g. runbook://payment-service) as evidence, source = its
        scheme ("runbook"). Never raises, like call()."""
        uri = template.format(**parameters)
        source = uri.split("://", 1)[0]
        run = await self._start_run(f"read {source}", {"uri": uri}, step)
        try:
            contents = (await self._client.read_resource(uri)).contents[0]
        except Exception as error:
            return await self._finish_run(run, Evidence(source=source, arguments={"uri": uri}, error=str(error), step=step))
        text = getattr(contents, "text", "")
        value = parse_tool_output(text) if contents.mime_type == JSON_MIME_TYPE else text
        return await self._finish_run(run, Evidence(source=source, arguments={"uri": uri}, result=value, step=step))

    async def _start_run(self, name: str, inputs: dict[str, Any], step: Step):
        # Report the call as a LangChain tool run of the current graph step, so tracing
        # callbacks (Langfuse) and the live stream show it under that step, like the
        # tools the LLM requests.
        callbacks = AsyncCallbackManager.configure(
            inheritable_callbacks=ensure_config().get("callbacks"), local_metadata={"step": step})
        return await callbacks.on_tool_start({"name": name}, json.dumps(inputs), inputs=inputs, name=name)

    @staticmethod
    async def _finish_run(run, evidence: Evidence) -> Evidence:
        if evidence.error:
            await run.on_tool_error(ToolException(evidence.error))
        else:
            await run.on_tool_end(evidence.result)
        return evidence

    async def _call_untraced(self, name: str, arguments: dict[str, Any], step: Step) -> Evidence:
        try:
            result = await self._client.call_tool(
                name, arguments, progress_callback=progress_callback_for(name, self._on_progress))
        except Exception as error:
            return Evidence(source=name, arguments=arguments, error=f"MCP call failed: {error}", step=step)
        text = extract_result_text(result)
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
