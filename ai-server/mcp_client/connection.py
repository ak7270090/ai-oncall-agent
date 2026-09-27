from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx2
from mcp import Client
from mcp.server.mcpserver import MCPServer


class MCPUnavailableError(Exception):
    pass


def _root_cause(error: BaseException) -> BaseException:
    while isinstance(error, BaseExceptionGroup) and error.exceptions:
        error = error.exceptions[0]
    return error


@asynccontextmanager
async def connect_to_mcp(server: str | MCPServer, timeout_seconds: float) -> AsyncIterator[Client]:
    """Connected MCP client: Streamable HTTP for a URL, in-process for a server object.

    mcp.Client runs inside an anyio task group, which wraps every error (including
    ones raised by the caller's block) in an ExceptionGroup. Unwrap it here so
    callers can catch ordinary exception types.
    """
    try:
        async with Client(server, read_timeout_seconds=timeout_seconds) as mcp_client:
            yield mcp_client
    except BaseExceptionGroup as group:
        error = _root_cause(group)
        if isinstance(error, httpx2.TransportError):
            raise MCPUnavailableError(f"MCP server unreachable at {server}") from error
        raise error from group
    except httpx2.TransportError as error:
        raise MCPUnavailableError(f"MCP server unreachable at {server}") from error
