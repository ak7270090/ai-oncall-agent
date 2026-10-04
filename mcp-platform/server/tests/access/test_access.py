"""Phases 19-20 over real HTTP (in-process ASGI): bearer tokens, scopes, roles, four
eyes and the audit log."""

import json
import time
from contextlib import asynccontextmanager

import httpx2
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError
from mcp_types import ElicitResult

from access.audit_log import AuditLog
from access.constants import ACCESS_DENIED_ERROR_CODE, Scope
from config import Settings
from k8s.cluster.fake import FakeClusterWriter
from k8s.server import build_k8s_server

pytestmark = pytest.mark.anyio

SIGNING_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
SOMEONE_ELSES_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
KEY_ID = "test-key"
BASE_URL = "http://127.0.0.1:9000"
READ, WRITE = [Scope.READ], [Scope.READ, Scope.WRITE]
ROLES = {"dev": "developer", "alice": "oncall", "bob": "lead", "carol": "lead"}
TRACEPARENT = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
ROLLBACK = ("rollback_deployment", {"name": "payment-service", "revision": 1})


def mint_token(user: str, scopes: list[str], expires_in: float = 60, key=SIGNING_KEY,
               audience: str = "oncall-mcp-server") -> str:
    now = int(time.time())
    claims = {"sub": user, "client_id": "oncall-ai-server", "scope": " ".join(scopes), "iat": now,
              "exp": now + expires_in, "iss": "http://127.0.0.1:8000", "aud": audience}
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": KEY_ID})


def write_jwks(path) -> None:
    jwk = RSAAlgorithm.to_jwk(SIGNING_KEY.public_key(), as_dict=True)
    path.write_text(json.dumps({"keys": [{**jwk, "kid": KEY_ID, "alg": "RS256", "use": "sig"}]}))


def approval_by(approver: str):
    async def answer(context, params):
        return ElicitResult(action="accept", content={"approve": True, "reason": "bad release", "approver": approver})
    return answer


@pytest.fixture
def operations():
    return FakeClusterWriter()


@pytest.fixture
def server(operations, tmp_path):
    write_jwks(tmp_path / "jwks.json")
    server = build_k8s_server(Settings(_env_file=None, backend="fake", enable_write_tools=True,
                                    auth_jwks_path=tmp_path / "jwks.json", user_roles=ROLES), writer=operations)
    return server, server.streamable_http_app()


def http_client(app, token: str | None = None) -> httpx2.AsyncClient:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE_URL, headers=headers)


@asynccontextmanager
async def connect(server, token: str, elicitation_callback=None):
    mcp_server, app = server
    async with mcp_server.session_manager.run(), http_client(app, token) as http:
        transport = streamable_http_client(f"{BASE_URL}/mcp", http_client=http)
        async with Client(transport, elicitation_callback=elicitation_callback) as client:
            yield client


def audit_records(audit_log_in_tmp) -> list[dict]:
    return AuditLog(audit_log_in_tmp).read()


@pytest.mark.parametrize("token", [
    None,
    "not-a-jwt",
    mint_token("bob", WRITE, key=SOMEONE_ELSES_KEY),
    mint_token("bob", WRITE, expires_in=-120),
    mint_token("bob", WRITE, audience="another-server"),
    mint_token("bob", []),
])
async def test_requests_without_a_valid_token_get_401(server, token):
    mcp_server, app = server
    async with mcp_server.session_manager.run(), http_client(app, token) as http:
        response = await http.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert response.status_code in (401, 403)
    assert "oauth-protected-resource" in response.headers["www-authenticate"]


async def test_protected_resource_metadata_names_issuer_and_scopes(server):
    async with http_client(server[1]) as http:
        metadata = (await http.get("/.well-known/oauth-protected-resource/mcp")).json()
    assert metadata["authorization_servers"] == ["http://127.0.0.1:8000"]
    assert metadata["scopes_supported"] == [Scope.READ]


async def test_refusal_happens_before_the_tool_and_is_audited(server, operations, audit_log_in_tmp):
    async with connect(server, mint_token("alice", WRITE)) as client:
        with pytest.raises(MCPError) as refused:
            await client.call_tool(*ROLLBACK)
    assert refused.value.code == ACCESS_DENIED_ERROR_CODE
    assert operations.performed == []
    assert audit_records(audit_log_in_tmp)[-1] | {"time": None, "duration_ms": None} == {
        "time": None, "event": "refused", "user": "alice", "client": "oncall-ai-server", "tool": "rollback_deployment",
        "arguments": ROLLBACK[1], "trace_id": None, "outcome": "refused", "duration_ms": None,
        "error": "Access denied: role oncall may not call rollback_deployment"}


@pytest.mark.parametrize("user, tool, arguments, refusal", [
    ("alice", *ROLLBACK, "role oncall may not call rollback_deployment"),
    ("dev", "restart_deployment", {"name": "payment-service"}, "role developer may not call restart_deployment"),
    ("mallory", "get_deployment", {"name": "payment-service"}, "user mallory has no role"),
])
async def test_roles_decide_which_tools_a_person_may_call(server, operations, user, tool, arguments, refusal):
    async with connect(server, mint_token(user, WRITE), approval_by("bob")) as client:
        with pytest.raises(MCPError, match=refusal):
            await client.call_tool(tool, arguments)
    assert operations.performed == []


async def test_developer_may_read(server):
    async with connect(server, mint_token("dev", READ)) as client:
        result = await client.call_tool("get_deployment", {"name": "payment-service"})
    assert not result.is_error


@pytest.mark.parametrize("approver, refusal", [
    ("bob", "bob requested this change and can't also approve it"),
    ("alice", "role oncall may not approve rollback_deployment"),
    ("mallory", "user mallory has no role"),
])
async def test_approval_needs_a_second_person_allowed_to_run_the_tool(server, operations, approver, refusal):
    async with connect(server, mint_token("bob", WRITE), approval_by(approver)) as client:
        result = (await client.call_tool(*ROLLBACK)).structured_content
    assert operations.performed == []
    assert result["done"] is False and result["approval"] == "refused"
    assert result["detail"] == f"Not done: approval refused, {refusal}."


async def test_approved_change_is_audited_once_with_who_approved_and_the_trace(server, operations, audit_log_in_tmp):
    async with connect(server, mint_token("bob", WRITE), approval_by("carol")) as client:
        result = (await client.call_tool(*ROLLBACK, meta={"traceparent": TRACEPARENT})).structured_content
    assert result["done"] is True and result["requested_by"] == "bob" and result["approved_by"] == "carol"
    asked, done = audit_records(audit_log_in_tmp)
    assert asked["event"] == "approval_requested" and asked["questions"] == [
        "Roll back deployment payment-service in shop to revision 1 (image payment-service:v2.3.1)?"]
    assert {key: done[key] for key in ("event", "user", "tool", "outcome", "done", "approval", "requested_by",
                                       "approved_by", "approval_reason", "trace_id")} == {
        "event": "tool_call", "user": "bob", "tool": "rollback_deployment", "outcome": "ok", "done": True,
        "approval": "approved", "requested_by": "bob", "approved_by": "carol", "approval_reason": "bad release",
        "trace_id": "0af7651916cd43dd8448eb211c80319c"}
