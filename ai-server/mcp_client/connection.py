from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx2
from mcp import Client
from mcp.client.session import ElicitationFnT, SamplingFnT
from mcp.client.streamable_http import streamable_http_client
from mcp.server.mcpserver import MCPServer
from mcp.shared._httpx_utils import create_mcp_http_client


class MCPUnavailableError(Exception):
    pass


def _unwrap_exception_group(error: BaseException) -> BaseException:
    while isinstance(error, BaseExceptionGroup) and error.exceptions:
        error = error.exceptions[0]
    return error


@asynccontextmanager
async def connect_to_mcp(
    server: str | MCPServer, timeout_seconds: float, sampling_callback: SamplingFnT | None = None,
    elicitation_callback: ElicitationFnT | None = None, auth: httpx2.Auth | None = None,
) -> AsyncIterator[Client]:
    """Connected MCP client: Streamable HTTP for a URL, in-process for a server object.

    mcp.Client runs inside an anyio task group, which wraps every error (including
    ones raised by the caller's block) in an ExceptionGroup. Unwrap it here so
    callers can catch ordinary exception types. `sampling_callback` answers the server's
    sampling requests (MCP sampling); without it the client doesn't offer sampling.
    `elicitation_callback` answers the server's questions to the user (approvals).
    `auth` signs every HTTP request (bearer tokens, Phase 19).
    """
    try:
        async with (
            create_mcp_http_client(auth=auth) as http_client,
            Client(streamable_http_client(server, http_client=http_client) if isinstance(server, str) else server,
                   read_timeout_seconds=timeout_seconds, sampling_callback=sampling_callback,
                   elicitation_callback=elicitation_callback) as mcp_client,
        ):
            yield mcp_client
    except BaseExceptionGroup as group:
        error = _unwrap_exception_group(group)
        if isinstance(error, httpx2.TransportError):
            raise MCPUnavailableError(f"MCP server unreachable at {server}") from error
        raise error from group
    except httpx2.TransportError as error:
        raise MCPUnavailableError(f"MCP server unreachable at {server}") from error
