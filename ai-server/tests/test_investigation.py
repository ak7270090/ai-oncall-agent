import pytest

from agent import Evidence, MCPToolbox, build_investigation_graph, run_investigation
from agent.evidence import upstream_services, without_routine_startup_events
from agent.report import render_markdown
from config import Settings
from mcp_client import list_all_tools, to_langchain_tool
from tests.fakes import (PAYMENT_CRASHLOOP, PAYMENT_DOWN, build_fake_mcp_server, fake_connector, report,
                         scripted_model, tool_call_message)

pytestmark = pytest.mark.anyio
SETTINGS = Settings(_env_file=None, max_follow_up_rounds=2)
EXPECTED_STEPS = ["understand", "sweep", "focus", "follow_dependencies", "correlate", "report"]


async def investigate(chat_model, scenario=PAYMENT_DOWN, with_metrics=True):
    async with fake_connector(build_fake_mcp_server(scenario, with_metrics))() as mcp_client:
        tools = await list_all_tools(mcp_client)
        graph = build_investigation_graph(
            chat_model, MCPToolbox(mcp_client, tools), [to_langchain_tool(mcp_client, t) for t in tools], SETTINGS
        )
        return await run_investigation(graph, "Checkout is failing", SETTINGS.max_follow_up_rounds)


def calls(result, source: str, step: str | None = None) -> list[Evidence]:
    return [e for e in result.evidence if e.source == source and (step is None or e.step == step)]


async def test_runs_every_step_with_three_llm_calls():
    result = await investigate(scripted_model())
    assert result.steps == EXPECTED_STEPS
    assert result.llm_calls == 3
    assert result.report.confidence == "high"
    assert "**Likely cause** (high confidence)" in result.answer


async def test_sweep_covers_the_whole_namespace():
    result = await investigate(scripted_model())
    swept = {e.source for e in result.evidence if e.step == "sweep"}
    assert swept == {"get_service_overview", "list_pods", "list_events", "list_deployments"}


async def test_failing_service_logs_are_read_even_when_its_pods_look_healthy():
    result = await investigate(scripted_model())
    [logs] = calls(result, "get_pod_logs", "focus")
    assert logs.arguments["pod"] == "order-service-a" and logs.arguments["previous"] is False
    assert calls(result, "get_metrics", "focus")[0].arguments["service"] == "order-service"


async def test_upstream_named_in_logs_is_investigated():
    result = await investigate(scripted_model())
    followed = {(e.source, e.arguments.get("app") or e.arguments.get("name"))
                for e in result.evidence if e.step == "follow_dependencies"}
    assert ("list_pods", "payment-service") in followed
    assert any("payment-service" in note for note in result.notes)


async def test_crash_looping_pod_gets_previous_logs_and_rollout_history():
    result = await investigate(scripted_model(), scenario=PAYMENT_CRASHLOOP)
    logs = [e for e in calls(result, "get_pod_logs", "focus") if e.arguments["pod"] == "payment-service-x"]
    assert logs[0].arguments["previous"] is True
    assert "exit code 1" in logs[0].result["lines"]
    assert calls(result, "get_deployment", "focus")[0].arguments["name"] == "payment-service"


async def test_missing_metrics_tools_are_skipped_not_fatal():
    result = await investigate(scripted_model(), with_metrics=False)
    assert any("skipped get_service_overview" in note for note in result.notes)
    assert result.report is not None


async def test_tool_errors_are_kept_as_evidence():
    scenario = {**PAYMENT_CRASHLOOP, "previous_logs": {}}
    result = await investigate(scripted_model(), scenario=scenario)
    failed = [e for e in calls(result, "get_pod_logs") if e.error]
    assert failed and "no previous" in failed[0].error


async def test_follow_up_requests_add_evidence_and_are_capped():
    model = scripted_model(
        tool_call_message(("get_pod_status", {"pod": "order-service-a"})),
        tool_call_message(("list_pods", {"app": "user-service"})),
        tool_call_message(("list_events", {})),
    )
    result = await investigate(model)
    assert [e.source for e in result.evidence if e.step == "follow_up"] == ["get_pod_status", "list_pods"]
    assert result.follow_up_limit_reached
    assert result.steps.count("follow_up") == SETTINGS.max_follow_up_rounds
    assert result.llm_calls == 1 + 3 + 1


def test_upstream_detection_ignores_unknown_hosts_and_non_error_lines():
    evidence = [Evidence(source="get_pod_logs", arguments={"pod": "order-service-a"}, step="focus", result={"lines": [
        "ERROR upstream unavailable: POST http://payment-service/payments",
        "INFO fetched http://user-service/users/1",
        "ERROR upstream unavailable: GET http://example.com/x",
    ]})]
    assert upstream_services(evidence, {"payment-service", "user-service", "order-service"}) == {"payment-service"}


def test_upstream_detection_finds_non_http_dependencies_but_not_the_pods_own_service():
    evidence = [Evidence(source="get_pod_logs", arguments={"pod": "payment-service-7f-x"}, step="focus", result={"lines": [
        "ERROR database unavailable: payments-db:5432 (connection refused)",
        "ERROR payment-service could not connect to payments-db",
    ]})]
    assert upstream_services(evidence, {"payments-db", "payment-service"}) == {"payments-db"}


async def test_slow_service_gets_latency_cpu_and_pod_limits():
    scenario = {**PAYMENT_DOWN, "overview": [
        {"service": "user-service", "request_rate_per_second": 1.0, "error_rate": 0.0, "latency_p99_ms": 2500},
    ]}
    result = await investigate(scripted_model(), scenario=scenario)
    metrics = {e.arguments["metric"] for e in calls(result, "get_metrics", "focus")}
    assert {"latency_p99_ms", "cpu_cores"} <= metrics
    assert calls(result, "get_pod_status", "focus")[0].arguments["pod"] == "user-service-a"


def test_markdown_report_has_every_section():
    markdown = render_markdown(report())
    for heading in ("**Incident:**", "**Impact:**", "**Evidence:**", "**Likely cause**", "**Root cause:**",
                    "**Recommended action:**", "**Timeline:**"):
        assert heading in markdown


def test_routine_startup_probe_failures_are_hidden_but_real_ones_kept():
    pods = [
        {"name": "ready-pod", "ready": True, "restarts": 0},
        {"name": "crashing-pod", "ready": False, "restarts": 5},
    ]
    events = [
        {"reason": "Unhealthy", "object": "Pod/ready-pod"},
        {"reason": "Unhealthy", "object": "Pod/replaced-pod"},
        {"reason": "Unhealthy", "object": "Pod/crashing-pod"},
        {"reason": "BackOff", "object": "Pod/crashing-pod"},
    ]
    kept, dropped = without_routine_startup_events(events, pods)
    assert dropped == 2
    assert [e["object"] for e in kept] == ["Pod/crashing-pod", "Pod/crashing-pod"]
