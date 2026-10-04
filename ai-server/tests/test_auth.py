"""Phases 19-20 in the AI server: API keys, four eyes on actions, MCP token claims."""

import jwt
import pytest
from fastapi.testclient import TestClient

from actions.constants import ActionStatus
from actions.dependencies import get_action_registry
from actions.registry import ActionRegistry
from auth.constants import WRITE_SCOPES
from auth.token_keys import JWKS_FILE, PRIVATE_KEY_FILE, write_key_files
from auth.tokens import McpTokenIssuer
from config import Settings, get_settings
from llm.dependencies import get_model_router
from llm.model_router import ModelRouter
from main import app
from mcp_client.dependencies import get_mcp_connector
from tests.fakes import PAYMENT_DOWN, build_fake_mcp_server, fake_connector, scripted_model
from tests.test_actions import SCALE_UP, wait_for

ALICE, BOB = {"X-API-Key": "key-of-alice"}, {"X-API-Key": "key-of-bob"}


@pytest.fixture
def performed():
    return []


@pytest.fixture
def client(performed):
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, api_keys={"key-of-alice": "alice", "key-of-bob": "bob"})
    app.dependency_overrides[get_model_router] = lambda: ModelRouter.single(scripted_model())
    app.dependency_overrides[get_mcp_connector] = lambda: fake_connector(
        build_fake_mcp_server(PAYMENT_DOWN, performed=performed))
    registry = ActionRegistry(approval_timeout_seconds=5, require_second_person=True)
    app.dependency_overrides[get_action_registry] = lambda: registry
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong"}])
def test_api_needs_a_known_api_key(client, headers):
    assert client.get("/health").status_code == 200
    for response in (client.post("/investigate", json={"question": "hi"}, headers=headers),
                     client.post("/actions", json=SCALE_UP, headers=headers),
                     client.get("/tools", headers=headers)):
        assert response.status_code == 401


def test_signed_in_user_may_use_the_api(client):
    assert client.get("/tools", headers=ALICE).status_code == 200


def test_requester_cannot_approve_their_own_action(client, performed):
    started = client.post("/actions", json=SCALE_UP, headers=ALICE).json()
    assert started["requested_by"] == "alice"
    waiting = wait_for_approval(client, started["id"])
    own = client.post(f"/actions/{waiting['id']}/approval", json={"approve": True, "reason": "me"}, headers=ALICE)
    assert own.status_code == 403 and performed == []
    client.post(f"/actions/{waiting['id']}/approval", json={"approve": True, "reason": "ok"}, headers=BOB)
    done = wait_for(client_as(client, BOB), waiting["id"], {ActionStatus.DONE, ActionStatus.NOT_DONE, ActionStatus.FAILED})
    assert done["status"] == ActionStatus.DONE and done["approved_by"] == "bob"
    assert performed == ["scaled payment-service to 2"]


def test_mcp_tokens_are_signed_with_the_private_key_and_checked_with_the_jwks(tmp_path):
    write_key_files(tmp_path)
    issuer = McpTokenIssuer.from_key_file(tmp_path / PRIVATE_KEY_FILE, "http://ai", "mcp", ttl_seconds=60)
    token = issuer.mint("alice", WRITE_SCOPES)
    public_keys = jwt.PyJWKSet.from_json((tmp_path / JWKS_FILE).read_text())
    claims = jwt.decode(token, public_keys[jwt.get_unverified_header(token)["kid"]], algorithms=["RS256"],
                        audience="mcp", issuer="http://ai")
    assert claims["sub"] == "alice" and claims["client_id"] == "oncall-ai-server"
    assert claims["scope"] == "k8s:read k8s:write" and claims["exp"] - claims["iat"] == 60


def client_as(client: TestClient, headers: dict) -> TestClient:
    client.headers.update(headers)
    return client


def wait_for_approval(client: TestClient, action_id: str) -> dict:
    return wait_for(client_as(client, ALICE), action_id, {ActionStatus.AWAITING_APPROVAL})
