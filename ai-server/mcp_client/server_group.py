"""Several MCP servers seen as one client (Phase 22).

The AI server connects to each configured server (e.g. k8s and prometheus), merges their
tools and resource templates, and sends every call to the server that owns the tool or
resource. The rest of the AI server keeps using the servers' own names (`get_metrics`,
`runbook://payment-service`): a gateway that multiplexes several targets renames them
(`prometheus_get_metrics`, `k8s+runbook://payment-service`), and the names of its
targets are enough to map them back. Two servers offering the same name is a
configuration error, refused at start."""

from typing import Any

from mcp import Client
from mcp.types import (
    CallToolResult,
    ListResourceTemplatesResult,
    ListToolsResult,
    ReadResourceResult,
    ResourceTemplate,
    Tool,
)

from constants import GATEWAY_TOOL_SEPARATOR, GATEWAY_URI_SEPARATOR
from mcp_client.langchain_tools import list_all_resource_template_objects, list_all_tools

URI_TEMPLATE_VARIABLE_START = "{"


class DuplicateToolError(Exception):
    pass


class UnknownResourceError(Exception):
    pass


class McpServerGroup:
    """Duck-types the part of mcp.Client the AI server uses: list_tools,
    list_resource_templates, call_tool, read_resource."""

    def __init__(self, clients: dict[str, Client], gateway_targets: list[str] | None = None):
        self._clients = clients
        self._gateway_targets = gateway_targets or []
        self._tools: list[Tool] = []
        self._tool_routes: dict[str, tuple[Client, str]] = {}
        self._templates: list[ResourceTemplate] = []
        self._resource_routes: dict[str, tuple[Client, str]] = {}

    async def start(self) -> "McpServerGroup":
        """Discover every server's tools and resource templates."""
        owners: dict[str, str] = {}
        for server, client in self._clients.items():
            for tool in await list_all_tools(client):
                name, _ = self._without_gateway_prefix(tool.name, GATEWAY_TOOL_SEPARATOR)
                if name in owners:
                    raise DuplicateToolError(f"Tool {name!r} is offered by both MCP servers {owners[name]!r} "
                                             f"and {server!r}")
                owners[name] = server
                self._tools.append(tool.model_copy(update={"name": name}))
                self._tool_routes[name] = (client, tool.name)
            for template in await list_all_resource_template_objects(client):
                uri_template, gateway_prefix = self._without_gateway_prefix(template.uri_template, GATEWAY_URI_SEPARATOR)
                self._templates.append(template.model_copy(update={"uri_template": uri_template}))
                self._resource_routes[uri_template.split(URI_TEMPLATE_VARIABLE_START, 1)[0]] = (client, gateway_prefix)
        return self

    async def list_tools(self, cursor: str | None = None) -> ListToolsResult:
        return ListToolsResult(tools=self._tools)

    async def list_resource_templates(self, cursor: str | None = None) -> ListResourceTemplatesResult:
        return ListResourceTemplatesResult(resource_templates=self._templates)

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None, *args: Any,
                        **kwargs: Any) -> CallToolResult:
        client, server_name = self._tool_routes.get(name, (None, name))
        if client is None:  # unknown here: let the first server answer with its usual error
            client = next(iter(self._clients.values()))
        return await client.call_tool(server_name, arguments, *args, **kwargs)

    async def read_resource(self, uri: str) -> ReadResourceResult:
        prefixes = [prefix for prefix in self._resource_routes if uri.startswith(prefix)]
        if not prefixes:
            raise UnknownResourceError(f"No MCP server offers a resource like {uri}")
        client, gateway_prefix = self._resource_routes[max(prefixes, key=len)]
        return await client.read_resource(gateway_prefix + uri)

    def _without_gateway_prefix(self, name: str, separator: str) -> tuple[str, str]:
        """(the server's own name, the gateway's prefix or "")."""
        for target in self._gateway_targets:
            prefix = target + separator
            if name.startswith(prefix):
                return name.removeprefix(prefix), prefix
        return name, ""
