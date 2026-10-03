import time

import pytest
from fastapi.testclient import TestClient

from actions import ActionRegistry
from agent import ModelRouter
from api.dependencies import get_action_registry, get_mcp_connector, get_model_router
from config import Settings, get_settings
from constants import ActionStatus
from main import app
from tests.fakes import (
    PAYMENT_DOWN,
    build_fake_mcp_server,
    fake_connector,
    scripted_model,
)

SCALE_UP = {"action": {"operation": "scale_deployment", "deployment": "payment-service", "replicas": 2,
                       "revision": None, "reason": "it has 0 replicas"}}


@pytest.fixture
def performed():
    return []


@pytest.fixture
def client(performed):
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    app.dependency_overrides[get_model_router] = lambda: ModelRouter.single(scripted_model())
    app.dependency_overrides[get_mcp_connector] = lambda: fake_connector(build_fake_mcp_server(PAYMENT_DOWN, performed=performed))
    registry = ActionRegistry(approval_timeout_seconds=2)
    app.dependency_overrides[get_action_registry] = lambda: registry
    with TestClient(app) as test_client:  # keeps the event loop (and background actions) running
        yield test_client
    app.dependency_overrides.clear()


def wait_for(client, action_id: str, statuses: set[str], timeout: float = 5) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = client.get(f"/actions/{action_id}").json()
        if state["status"] in statuses:
            return state
        time.sleep(0.05)
    raise AssertionError(f"action {action_id} stayed {state['status']}")


def start(client) -> dict:
    response = client.post("/actions", json=SCALE_UP)
    assert response.status_code == 202
    return wait_for(client, response.json()["id"], {ActionStatus.AWAITING_APPROVAL})


def test_report_proposes_actions_but_the_investigation_changes_nothing(client, performed):
    report = client.post("/investigate", json={"question": "Checkout is failing"}).json()["report"]
    assert report["proposed_actions"][0]["operation"] == "scale_deployment"
    assert performed == []


def test_approved_action_is_made(client, performed):
    waiting = start(client)
    assert waiting["question"] == "Scale deployment payment-service to 2 replicas?"
    assert performed == []
    client.post(f"/actions/{waiting['id']}/approval", json={"approve": True, "reason": "scaled to 0 by mistake"})
    done = wait_for(client, waiting["id"], {ActionStatus.DONE, ActionStatus.NOT_DONE, ActionStatus.FAILED})
    assert done["status"] == ActionStatus.DONE and done["approval_reason"] == "scaled to 0 by mistake"
    assert performed == ["scaled payment-service to 2"]


def test_rejected_or_unanswered_action_changes_nothing(client, performed):
    rejected = start(client)
    client.post(f"/actions/{rejected['id']}/approval", json={"approve": False, "reason": "not now"})
    assert wait_for(client, rejected["id"], {ActionStatus.NOT_DONE, ActionStatus.DONE})["status"] == ActionStatus.NOT_DONE

    unanswered = start(client)  # the approval timeout in this test is 2 s
    final = wait_for(client, unanswered["id"], {ActionStatus.NOT_DONE, ActionStatus.DONE})
    assert final["status"] == ActionStatus.NOT_DONE and "No approval" in final["error"]
    assert performed == []


def test_approval_only_when_awaiting_and_only_known_operations(client):
    assert client.post("/actions/nope/approval", json={"approve": True, "reason": "x"}).status_code == 404
    waiting = start(client)
    client.post(f"/actions/{waiting['id']}/approval", json={"approve": False, "reason": "no"})
    wait_for(client, waiting["id"], {ActionStatus.NOT_DONE})
    assert client.post(f"/actions/{waiting['id']}/approval", json={"approve": True, "reason": "x"}).status_code == 409
    bad = {"action": {**SCALE_UP["action"], "operation": "delete_namespace"}}
    assert client.post("/actions", json=bad).status_code == 422
