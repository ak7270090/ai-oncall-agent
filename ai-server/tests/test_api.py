import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.runnables import RunnableLambda

from config import Settings, get_settings
from investigation.constants import Step
from llm.chat_model import create_chat_model
from llm.constants import LLM_FAILURE_MESSAGE
from llm.dependencies import get_model_router
from llm.model_router import ModelRouter
from main import app
from mcp_client.connection import connect_to_mcp
from mcp_client.dependencies import get_mcp_connector, get_service_mcp_connector
from tests.fakes import (
    PAYMENT_DOWN,
    build_fake_mcp_server,
    fake_connector,
    scripted_model,
)

UNREACHABLE_MCP_URL = "http://127.0.0.1:9/mcp"


class FailingChatModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self

    def with_structured_output(self, schema, **kwargs):
        return RunnableLambda(self._fail)

    def _fail(self, *args, **kwargs):
        raise RuntimeError("provider down")

    _generate = _fail


@pytest.fixture
def client():
    # Isolate from the developer's ai-server/.env and from any real LLM provider.
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    app.dependency_overrides[get_model_router] = lambda: ModelRouter.single(scripted_model())
    app.dependency_overrides[get_mcp_connector] = lambda: fake_connector(build_fake_mcp_server(PAYMENT_DOWN))
    app.dependency_overrides[get_service_mcp_connector] = app.dependency_overrides[get_mcp_connector]
    yield TestClient(app)
    app.dependency_overrides.clear()


def use_chat_model(chat_model):
    app.dependency_overrides[get_model_router] = lambda: ModelRouter.single(chat_model)


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_ready_when_mcp_reachable(client):
    assert client.get("/ready").json() == {"status": "ready"}


def test_tools_lists_mcp_tools(client):
    tools = client.get("/tools").json()["tools"]
    names = {t["name"] for t in tools}
    assert {"list_pods", "get_pod_logs", "get_service_overview"} <= names
    assert all("properties" in t["input_schema"] for t in tools)


def test_investigate_returns_structured_report_and_evidence(client):
    response = client.post("/investigate", json={"question": "Checkout is failing"})
    assert response.status_code == 200
    body = response.json()
    assert body["steps"] == [Step.EXTRACT_INCIDENT_SCOPE, Step.COLLECT_NAMESPACE_OVERVIEW, Step.INSPECT_FLAGGED_PROBLEMS,
                             Step.TRACE_FAILING_DEPENDENCIES, Step.FIND_ROOT_CAUSE, Step.WRITE_REPORT]
    assert body["report"]["confidence"] == "high"
    assert body["answer"].startswith("**Incident:**")
    assert body["llm_calls"] == 3
    assert {"step", "source", "arguments"} <= body["evidence"][0].keys()
    assert body["evidence"][0]["result"] is None
    assert body["scope"]["symptom"] and body["namespace"] == "shop"
    assert body["trace_id"] is None and body["trace_url"] is None  # no Langfuse keys in tests


def test_investigate_can_include_raw_evidence(client):
    body = client.post("/investigate", json={"question": "Checkout is failing", "include_evidence_results": True}).json()
    assert any(e["result"] for e in body["evidence"])


def test_empty_question_rejected(client):
    assert client.post("/investigate", json={"question": ""}).status_code == 422


def test_llm_failure_returns_502(client):
    use_chat_model(FailingChatModel(messages=iter([])))
    response = client.post("/investigate", json={"question": "hi"})
    assert response.status_code == 502
    assert response.json()["detail"] == LLM_FAILURE_MESSAGE


def test_missing_llm_credentials_returns_502(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings_without_key = Settings(_env_file=None, llm_model="openai:gpt-5.4-mini")
    app.dependency_overrides[get_model_router] = lambda: ModelRouter.single(create_chat_model(settings_without_key))
    response = client.post("/investigate", json={"question": "hi"})
    assert response.status_code == 502
    assert response.json()["detail"] == LLM_FAILURE_MESSAGE


def test_unreachable_mcp_returns_503(client):
    app.dependency_overrides[get_mcp_connector] = lambda: lambda sampling_callback=None, elicitation_callback=None, scopes=(): connect_to_mcp(UNREACHABLE_MCP_URL, 5)
    app.dependency_overrides[get_service_mcp_connector] = app.dependency_overrides[get_mcp_connector]
    assert client.get("/ready").status_code == 503
    assert client.get("/tools").status_code == 503
    assert client.post("/investigate", json={"question": "hi"}).status_code == 503
