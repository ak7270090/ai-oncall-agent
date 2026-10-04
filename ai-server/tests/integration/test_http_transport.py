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
from contextlib import contextmanager
from pathlib import Path

import pytest
from mcp.shared.exceptions import MCPError

from auth.constants import READ_SCOPES, WRITE_SCOPES
from auth.token_keys import JWKS_FILE, PRIVATE_KEY_FILE, write_key_files
from auth.tokens import McpTokenAuth, McpTokenIssuer
from mcp_client.connection import MCPUnavailableError, connect_to_mcp, connect_to_mcp_servers
from mcp_client.constants import McpOperation
from mcp_client.langchain_tools import list_all_tools

pytestmark = pytest.mark.anyio

MCP_SERVER_DIR = Path(os.environ.get("MCP_SERVER_DIR", Path(__file__).parents[3] / "mcp-server"))
VENV_PYTHON = MCP_SERVER_DIR / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
HOST = "127.0.0.1"
STARTUP_TIMEOUT_SECONDS = 20
MCP_TIMEOUT_SECONDS = 10
EXPECTED_TOOLS = {"list_pods", "get_pod_status", "get_pod_logs", "list_deployments", "get_deployment",
                  "list_events", "get_service_overview", "get_metrics"}
# Overrides whatever the developer's mcp-server/.env sets; each test adds what it needs.
BASELINE_SETTINGS = {"MCP_AUTH_JWKS_PATH": "", "MCP_USER_ROLES": "{}", "MCP_ENABLE_WRITE_TOOLS": "false"}

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


@contextmanager
def running_mcp_server(audit_log: Path, **settings: str):
    port = free_port()
    process = subprocess.Popen(
        [str(VENV_PYTHON), "server.py"],
        cwd=MCP_SERVER_DIR,
        env={**os.environ, "MCP_HOST": HOST, "MCP_PORT": str(port), "MCP_TRANSPORT": "streamable-http",
             "MCP_BACKEND": "fake", "MCP_AUDIT_LOG_PATH": str(audit_log), **BASELINE_SETTINGS, **settings},
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


@pytest.fixture(scope="module")
def mcp_server_url(tmp_path_factory):
    with running_mcp_server(tmp_path_factory.mktemp("audit") / "audit.jsonl") as url:
        yield url


@pytest.fixture(scope="module")
def token_keys(tmp_path_factory) -> tuple[McpTokenIssuer, Path]:
    """A fresh key pair: the issuer (private key) and the JWKS file (public key)."""
    directory = tmp_path_factory.mktemp("keys")
    write_key_files(directory)
    issuer = McpTokenIssuer.from_key_file(directory / PRIVATE_KEY_FILE, "http://127.0.0.1:8000", "oncall-mcp-server", 60)
    return issuer, directory / JWKS_FILE


@pytest.fixture(scope="module")
def authenticated_mcp_server_url(tmp_path_factory, token_keys):
    with running_mcp_server(tmp_path_factory.mktemp("audit") / "audit.jsonl", MCP_AUTH_JWKS_PATH=str(token_keys[1]),
                            MCP_ENABLE_WRITE_TOOLS="true", MCP_USER_ROLES=json.dumps({"bob": "lead"})) as url:
        yield url


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


async def test_authenticated_server_refuses_requests_without_a_token(authenticated_mcp_server_url):
    with pytest.raises(MCPError, match="error response"):
        async with connect_to_mcp(authenticated_mcp_server_url, MCP_TIMEOUT_SECONDS) as mcp_client:
            await list_all_tools(mcp_client)


@pytest.mark.parametrize("scopes, sees_write_tools", [(READ_SCOPES, False), (WRITE_SCOPES, True)])
async def test_token_scopes_decide_whether_write_tools_are_listed(authenticated_mcp_server_url, token_keys, scopes,
                                                                  sees_write_tools):
    auth = McpTokenAuth(token_keys[0], "bob", scopes)
    async with connect_to_mcp(authenticated_mcp_server_url, MCP_TIMEOUT_SECONDS, auth=auth) as mcp_client:
        names = {tool.name for tool in await list_all_tools(mcp_client)}
        result = await mcp_client.call_tool("list_pods", {"app": "payment-service"})
    assert EXPECTED_TOOLS <= names and not result.is_error
    assert (set(McpOperation) <= names) is sees_write_tools


async def test_person_without_a_role_is_refused(authenticated_mcp_server_url, token_keys):
    auth = McpTokenAuth(token_keys[0], "mallory", READ_SCOPES)
    with pytest.raises(MCPError, match="user mallory has no role"):
        async with connect_to_mcp(authenticated_mcp_server_url, MCP_TIMEOUT_SECONDS, auth=auth) as mcp_client:
            await mcp_client.call_tool("list_pods", {"app": "payment-service"})


async def test_two_servers_one_per_toolset_work_as_one_client(tmp_path_factory, token_keys):
    audit_dir = tmp_path_factory.mktemp("audit")
    auth = McpTokenAuth(token_keys[0], "bob", WRITE_SCOPES)
    settings = {"MCP_AUTH_JWKS_PATH": str(token_keys[1]), "MCP_USER_ROLES": json.dumps({"bob": "lead"})}
    with (
        running_mcp_server(audit_dir / "k8s.jsonl", MCP_TOOLSETS='["kubernetes"]', **settings) as k8s_url,
        running_mcp_server(audit_dir / "prometheus.jsonl", MCP_TOOLSETS='["prometheus"]', **settings) as prometheus_url,
    ):
        servers = {"k8s": k8s_url, "prometheus": prometheus_url}
        async with connect_to_mcp_servers(servers, MCP_TIMEOUT_SECONDS, auth=auth) as group:
            names = {tool.name for tool in await list_all_tools(group)}
            overview = await group.call_tool("get_service_overview", {})
            pods = await group.call_tool("list_pods", {"app": "payment-service"})
    assert names == EXPECTED_TOOLS
    assert not overview.is_error and not pods.is_error
    assert "get_service_overview" in (audit_dir / "prometheus.jsonl").read_text()
    assert "list_pods" in (audit_dir / "k8s.jsonl").read_text()
