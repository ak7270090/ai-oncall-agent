import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

from agent import create_chat_model
from api.dependencies import get_chat_model, get_mcp_connector
from config import Settings, get_settings
from main import LLM_FAILURE_MESSAGE, app
from mcp_client import connect_to_mcp
from tests.fakes import build_fake_mcp_server, fake_connector, scripted_model, tool_call_message

UNREACHABLE_MCP_URL = "http://127.0.0.1:9/mcp"


class FailingChatModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, *args, **kwargs):
        raise RuntimeError("provider down")


@pytest.fixture
def client():
    # Isolate from the developer's ai-server/.env and from any real LLM provider.
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    app.dependency_overrides[get_chat_model] = lambda: scripted_model("unused")
    app.dependency_overrides[get_mcp_connector] = lambda: fake_connector(build_fake_mcp_server())
    yield TestClient(app)
    app.dependency_overrides.clear()


def use_chat_model(chat_model):
    app.dependency_overrides[get_chat_model] = lambda: chat_model


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_ready_when_mcp_reachable(client):
    assert client.get("/ready").json() == {"status": "ready"}


def test_tools_lists_mcp_tools(client):
    tools = client.get("/tools").json()["tools"]
    assert {t["name"] for t in tools} == {"get_pod_status", "get_logs"}
    assert "service" in tools[0]["input_schema"]["properties"]


def test_investigate(client):
    use_chat_model(scripted_model(
        tool_call_message(("get_pod_status", {"service": "payment-service"})),
        "Likely cause: crash loop",
    ))
    response = client.post("/investigate", json={"question": "payments are down"})
    assert response.status_code == 200
    assert response.json() == {
        "answer": "Likely cause: crash loop",
        "completed": True,
        "llm_calls": 2,
        "tool_calls": [
            {"tool": "get_pod_status", "arguments": {"service": "payment-service"}, "is_error": False}
        ],
    }


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
    app.dependency_overrides[get_chat_model] = lambda: create_chat_model(settings_without_key)
    response = client.post("/investigate", json={"question": "hi"})
    assert response.status_code == 502
    assert response.json()["detail"] == LLM_FAILURE_MESSAGE


def test_unreachable_mcp_returns_503(client):
    app.dependency_overrides[get_mcp_connector] = lambda: lambda: connect_to_mcp(UNREACHABLE_MCP_URL, 5)
    use_chat_model(scripted_model("unused"))
    assert client.get("/ready").status_code == 503
    assert client.get("/tools").status_code == 503
    assert client.post("/investigate", json={"question": "hi"}).status_code == 503
