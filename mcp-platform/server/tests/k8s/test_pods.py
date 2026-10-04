import pytest
from mcp import Client
from mcp_types import CreateMessageResult, TextContent

from access.audit_log import AuditLog
from config import Settings
from k8s.constants import LOG_LINES_KEPT_WITH_SUMMARY, LOG_SUMMARY_TASK
from k8s.pods import RecentLogs
from k8s.server import build_k8s_server

pytestmark = pytest.mark.anyio
CRASHING_POD = "payment-service-7d9f8c6b5-2xkqp"
LOGS = {"pod": CRASHING_POD, "previous": True, "summarize": True}


def summarizing_server(min_lines: int = 1):
    return build_k8s_server(Settings(_env_file=None, backend="fake", log_summary_min_lines=min_lines))


class RecordingSampler:
    """Stands in for the AI server's LLM: records each sampling request and answers it."""

    def __init__(self):
        self.requests = []

    async def __call__(self, context, params):
        self.requests.append(params)
        return CreateMessageResult(role="assistant", model="fast-model",
                                   content=TextContent(type="text", text="2x could not resolve host payments-db"))


async def test_summarize_asks_the_clients_llm_with_cheap_model_preferences(audit_log_in_tmp):
    sampler = RecordingSampler()
    async with Client(summarizing_server(), sampling_callback=sampler) as client:
        result = (await client.call_tool("get_pod_logs", LOGS)).structured_content

    [request] = sampler.requests
    assert request.model_preferences.cost_priority > request.model_preferences.intelligence_priority
    assert request.metadata == {"task": LOG_SUMMARY_TASK, "pod": CRASHING_POD}
    assert "could not resolve host" in request.messages[0].content.text
    assert result["summary"] == "2x could not resolve host payments-db"
    assert result["summarized_by"] == "fast-model"
    assert len(result["lines"]) <= LOG_LINES_KEPT_WITH_SUMMARY
    assert [r["event"] for r in AuditLog(audit_log_in_tmp).read()] == ["sampling_requested", "tool_call"]


async def test_short_logs_and_clients_without_sampling_get_raw_lines():
    sampler = RecordingSampler()
    async with Client(summarizing_server(min_lines=10_000), sampling_callback=sampler) as client:
        short = (await client.call_tool("get_pod_logs", LOGS)).structured_content
    async with Client(summarizing_server()) as client:
        no_sampling = (await client.call_tool("get_pod_logs", LOGS)).structured_content

    assert sampler.requests == []
    for result in (short, no_sampling):
        assert result["summary"] is None and result["lines"]


def test_recent_logs_reuses_lines_within_the_ttl():
    class GrowingLog:
        calls = 0

        def get_pod_logs(self, namespace, pod, lines, previous):
            self.calls += 1
            return [f"line {self.calls}"]

    now = [0.0]
    backend = GrowingLog()
    recent = RecentLogs(backend, ttl_seconds=30, clock=lambda: now[0])
    first = recent.get("shop", "p", 50, False)
    now[0] = 5
    assert recent.get("shop", "p", 50, False) == first  # the retry round sees the same lines
    now[0] = 40
    assert recent.get("shop", "p", 50, False) != first
    assert backend.calls == 2
