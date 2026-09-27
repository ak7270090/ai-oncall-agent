"""Runs the real MCP server as a separate process and talks to it over Streamable HTTP.

The servers share no code: the MCP server is started from its own directory and
virtualenv (override the location with MCP_SERVER_DIR).
"""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from mcp_client import MCPUnavailableError, connect_to_mcp, list_all_tools

pytestmark = pytest.mark.anyio

MCP_SERVER_DIR = Path(os.environ.get("MCP_SERVER_DIR", Path(__file__).parents[3] / "mcp-server"))
VENV_PYTHON = MCP_SERVER_DIR / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
HOST = "127.0.0.1"
STARTUP_TIMEOUT_SECONDS = 20
MCP_TIMEOUT_SECONDS = 10
EXPECTED_TOOLS = {"list_pods", "get_pod_status", "get_pod_logs", "list_deployments", "get_deployment",
                  "list_events", "get_metrics"}

if not VENV_PYTHON.exists():
    pytest.skip(f"MCP server virtualenv not found at {VENV_PYTHON}", allow_module_level=True)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind((HOST, 0))
        return sock.getsockname()[1]


def wait_until_healthy(health_url: str, process: subprocess.Popen) -> None:
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"MCP server exited early:\n{process.stdout.read()}")
        try:
            with urllib.request.urlopen(health_url) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.2)
    raise TimeoutError(f"MCP server not healthy at {health_url}")


@pytest.fixture(scope="module")
def mcp_server_url():
    port = free_port()
    process = subprocess.Popen(
        [str(VENV_PYTHON), "server.py"],
        cwd=MCP_SERVER_DIR,
        env={**os.environ, "MCP_HOST": HOST, "MCP_PORT": str(port), "MCP_TRANSPORT": "streamable-http",
             "MCP_BACKEND": "fake"},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        wait_until_healthy(f"http://{HOST}:{port}/health", process)
        yield f"http://{HOST}:{port}/mcp"
    finally:
        process.terminate()
        process.wait()


async def test_discovers_tools_over_http(mcp_server_url):
    async with connect_to_mcp(mcp_server_url, MCP_TIMEOUT_SECONDS) as mcp_client:
        tools = await list_all_tools(mcp_client)
    assert {tool.name for tool in tools} == EXPECTED_TOOLS


async def test_calls_tool_over_http(mcp_server_url):
    async with connect_to_mcp(mcp_server_url, MCP_TIMEOUT_SECONDS) as mcp_client:
        result = await mcp_client.call_tool("list_pods", {"app": "payment-service"})
    pods = json.loads(result.content[0].text)["pods"]
    assert all(pod["status"] == "CrashLoopBackOff" for pod in pods)


async def test_unreachable_server_raises_mcp_unavailable():
    with pytest.raises(MCPUnavailableError):
        async with connect_to_mcp(f"http://{HOST}:{free_port()}/mcp", MCP_TIMEOUT_SECONDS):
            pass
