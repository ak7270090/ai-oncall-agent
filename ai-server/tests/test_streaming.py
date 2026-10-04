import json

import pytest
from fastapi.testclient import TestClient

from agent import IncidentReport, ModelRouter
from api.dependencies import (
    InvestigationDependencies,
    get_mcp_connector,
    get_model_router,
)
from api.routes import investigate_stream
from api.schemas import InvestigateRequest
from config import Settings, get_settings
from constants import LLM_FAILURE_MESSAGE, EventStatus, Step, StreamEvent
from main import app
from tests.fakes import (
    PAYMENT_DOWN,
    build_fake_mcp_server,
    fake_connector,
    scripted_model,
)
from tests.test_api import FailingChatModel
from tracing import DISABLED_TRACER

QUESTION = {"question": "Checkout is failing"}


@pytest.fixture
def client():
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    app.dependency_overrides[get_model_router] = lambda: ModelRouter.single(scripted_model())
    app.dependency_overrides[get_mcp_connector] = lambda: fake_connector(build_fake_mcp_server(PAYMENT_DOWN))
    yield TestClient(app)
    app.dependency_overrides.clear()


def stream_events(client: TestClient) -> list[tuple[str, dict]]:
    events, name = [], None
    with client.stream("POST", "/investigate/stream", json=QUESTION) as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        for line in response.iter_lines():
            if line.startswith("event: "):
                name = line.removeprefix("event: ")
            elif line.startswith("data: "):
                events.append((name, json.loads(line.removeprefix("data: "))))
    return events


def of_kind(events, kind: StreamEvent) -> list[dict]:
    return [data for name, data in events if name == kind]


def test_stream_shows_steps_tools_progress_and_ends_with_the_report(client):
    events = stream_events(client)

    started_steps = [e["step"] for e in of_kind(events, StreamEvent.STEP) if e["status"] == EventStatus.STARTED]
    assert started_steps[:4] == [Step.EXTRACT_INCIDENT_SCOPE, Step.COLLECT_NAMESPACE_OVERVIEW,
                                 Step.INSPECT_FLAGGED_PROBLEMS, Step.TRACE_FAILING_DEPENDENCIES]
    assert started_steps[-1] == Step.WRITE_REPORT

    tools = of_kind(events, StreamEvent.TOOL)
    assert {"tool": "list_pods", "status": "started", "step": Step.COLLECT_NAMESPACE_OVERVIEW} \
        .items() <= tools[0].items() or any(t["tool"] == "list_pods" and t["step"] == Step.COLLECT_NAMESPACE_OVERVIEW
                                            for t in tools)
    assert all(t["seconds"] is not None for t in tools if t["status"] == EventStatus.FINISHED)

    progress = [e for e in of_kind(events, StreamEvent.PROGRESS) if e["tool"] == "get_service_overview"]
    assert [(e["progress"], e["total"]) for e in progress] == [(1, 3), (2, 3), (3, 3)]

    assert any("payment-service" in e["note"] for e in of_kind(events, StreamEvent.NOTE))
    # The scripted model answers structured calls without a chat-model run, so only the
    # root-cause call shows up here; a real model reports all three LLM calls.
    assert {"step": Step.FIND_ROOT_CAUSE, "status": EventStatus.FINISHED}.items() <=         of_kind(events, StreamEvent.LLM)[-1].items()

    last_name, report = events[-1]
    assert last_name == StreamEvent.REPORT
    assert report["report"]["root_cause_service"] == "payment-service" and report["llm_calls"] == 3


def test_stream_ends_with_an_error_event_when_the_llm_fails(client):
    app.dependency_overrides[get_model_router] = lambda: ModelRouter.single(FailingChatModel(messages=iter([])))
    last_name, error = stream_events(client)[-1]
    assert last_name == StreamEvent.ERROR
    assert error == {"status_code": 502, "detail": LLM_FAILURE_MESSAGE}


@pytest.mark.anyio
async def test_closing_the_stream_cancels_the_investigation():
    chat_model = scripted_model()
    dependencies = InvestigationDependencies(
        Settings(_env_file=None), ModelRouter.single(chat_model), fake_connector(build_fake_mcp_server(PAYMENT_DOWN)), DISABLED_TRACER,
        "anonymous")
    stream = investigate_stream(InvestigateRequest(**QUESTION), dependencies)

    first = await anext(stream)
    await stream.aclose()  # what FastAPI does when the client disconnects

    assert first.event == StreamEvent.STEP
    assert isinstance(chat_model.structured_replies[-1], IncidentReport), "the report was never written"
