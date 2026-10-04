import pytest

from config import Settings
from investigation.constants import Step
from investigation.evidence.analysis import (
    computed_findings,
    services_blamed_in_logs,
    without_stale_pod_events,
)
from investigation.evidence.mcp_toolbox import MCPToolbox
from investigation.models import Evidence
from investigation.service import reanalyze_evidence, run_investigation
from investigation.workflow.graph import build_investigation_graph
from llm.model_router import ModelRouter
from mcp_client.langchain_tools import list_all_tools, to_langchain_tool
from tests.fakes import (
    PAYMENT_CRASHLOOP,
    PAYMENT_DOWN,
    build_fake_mcp_server,
    fake_connector,
    report,
    scripted_model,
    tool_call_message,
)

pytestmark = pytest.mark.anyio
SETTINGS = Settings(_env_file=None, max_follow_up_rounds=2)
EXPECTED_STEPS = [Step.EXTRACT_INCIDENT_SCOPE, Step.COLLECT_NAMESPACE_OVERVIEW, Step.INSPECT_FLAGGED_PROBLEMS,
                  Step.TRACE_FAILING_DEPENDENCIES, Step.FIND_ROOT_CAUSE, Step.WRITE_REPORT]


async def investigate(chat_model, incident=PAYMENT_DOWN, with_metrics=True):
    async with fake_connector(build_fake_mcp_server(incident, with_metrics))() as mcp_client:
        tools = await list_all_tools(mcp_client)
        graph = build_investigation_graph(
            ModelRouter.single(chat_model), MCPToolbox(mcp_client, tools), [to_langchain_tool(mcp_client, t) for t in tools], SETTINGS
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
    swept = {e.source for e in result.evidence if e.step == Step.COLLECT_NAMESPACE_OVERVIEW}
    assert swept == {"get_service_overview", "list_pods", "list_events", "list_deployments"}


async def test_failing_service_logs_are_read_even_when_its_pods_look_healthy():
    result = await investigate(scripted_model())
    [logs] = calls(result, "get_pod_logs", Step.INSPECT_FLAGGED_PROBLEMS)
    assert logs.arguments["pod"] == "order-service-a" and logs.arguments["previous"] is False
    assert calls(result, "get_metrics", Step.INSPECT_FLAGGED_PROBLEMS)[0].arguments["service"] == "order-service"


async def test_upstream_named_in_logs_is_investigated():
    result = await investigate(scripted_model())
    followed = {(e.source, e.arguments.get("app") or e.arguments.get("name"))
                for e in result.evidence if e.step == Step.TRACE_FAILING_DEPENDENCIES}
    assert ("list_pods", "payment-service") in followed
    followed_metrics = {e.arguments["metric"] for e in calls(result, "get_metrics", Step.TRACE_FAILING_DEPENDENCIES)}
    assert followed_metrics == {"error_rate", "latency_p99_ms"}
    assert any("payment-service" in note for note in result.notes)


async def test_crash_looping_pod_gets_previous_logs_and_rollout_history():
    result = await investigate(scripted_model(), incident=PAYMENT_CRASHLOOP)
    logs = [e for e in calls(result, "get_pod_logs", Step.INSPECT_FLAGGED_PROBLEMS) if e.arguments["pod"] == "payment-service-x"]
    assert logs[0].arguments["previous"] is True
    assert "exit code 1" in logs[0].result["lines"]
    assert calls(result, "get_deployment", Step.INSPECT_FLAGGED_PROBLEMS)[0].arguments["name"] == "payment-service"


async def test_missing_metrics_tools_are_skipped_not_fatal():
    result = await investigate(scripted_model(), with_metrics=False)
    assert any("skipped get_service_overview" in note for note in result.notes)
    assert result.report is not None


async def test_tool_errors_are_kept_as_evidence():
    incident = {**PAYMENT_CRASHLOOP, "previous_logs": {}}
    result = await investigate(scripted_model(), incident=incident)
    failed = [e for e in calls(result, "get_pod_logs") if e.error]
    assert failed and "no previous" in failed[0].error


async def test_follow_up_requests_add_evidence_and_are_capped():
    model = scripted_model(
        tool_call_message(("get_pod_status", {"pod": "order-service-a"})),
        tool_call_message(("list_pods", {"app": "user-service"})),
        tool_call_message(("list_events", {})),
    )
    result = await investigate(model)
    assert [e.source for e in result.evidence if e.step == Step.RUN_REQUESTED_TOOLS] == ["get_pod_status", "list_pods"]
    assert result.follow_up_limit_reached
    assert result.steps.count(Step.RUN_REQUESTED_TOOLS) == SETTINGS.max_follow_up_rounds
    assert result.llm_calls == 1 + 3 + 1


def test_upstream_detection_ignores_unknown_hosts_and_non_error_lines():
    evidence = [Evidence(source="get_pod_logs", arguments={"pod": "order-service-a"}, step=Step.INSPECT_FLAGGED_PROBLEMS, result={"lines": [
        "ERROR upstream unavailable: POST http://payment-service/payments",
        "INFO fetched http://user-service/users/1",
        "ERROR upstream unavailable: GET http://example.com/x",
    ]})]
    assert services_blamed_in_logs(evidence, {"payment-service", "user-service", "order-service"}) == {"payment-service"}


def test_upstream_detection_finds_non_http_dependencies_but_not_the_pods_own_service():
    evidence = [Evidence(source="get_pod_logs", arguments={"pod": "payment-service-7f-x"}, step=Step.INSPECT_FLAGGED_PROBLEMS, result={"lines": [
        "ERROR database unavailable: payments-db:5432 (connection refused)",
        "ERROR payment-service could not connect to payments-db",
    ]})]
    assert services_blamed_in_logs(evidence, {"payments-db", "payment-service"}) == {"payments-db"}


async def test_slow_service_gets_latency_cpu_and_pod_limits():
    incident = {**PAYMENT_DOWN, "overview": [
        {"service": "user-service", "request_rate_per_second": 1.0, "error_rate": 0.0, "latency_p99_ms": 2500},
    ]}
    result = await investigate(scripted_model(), incident=incident)
    metrics = {e.arguments["metric"] for e in calls(result, "get_metrics", Step.INSPECT_FLAGGED_PROBLEMS)}
    assert {"latency_p99_ms", "cpu_cores"} <= metrics
    assert calls(result, "get_pod_status", Step.INSPECT_FLAGGED_PROBLEMS)[0].arguments["pod"] == "user-service-a"


def test_markdown_report_has_every_section():
    markdown = report().to_markdown()
    for heading in ("**Incident:**", "**Impact:**", "**Evidence:**", "**Likely cause**", "**Root cause:**",
                    "**Recommended action:**", "**Timeline:**"):
        assert heading in markdown


def test_stale_pod_events_are_hidden_but_current_problems_kept():
    pods = [
        {"name": "ready-pod", "ready": True, "restarts": 0},
        {"name": "crashing-pod", "ready": False, "restarts": 5},
    ]
    events = [
        {"reason": "Unhealthy", "object": "Pod/ready-pod"},       # booted, now fine
        {"reason": "Unhealthy", "object": "Pod/replaced-pod"},    # pod gone
        {"reason": "BackOff", "object": "Pod/old-crashed-pod"},   # earlier incident, pod gone
        {"reason": "Unhealthy", "object": "Pod/crashing-pod"},
        {"reason": "BackOff", "object": "Pod/crashing-pod"},
        {"reason": "ProgressDeadlineExceeded", "object": "Deployment/payment-service"},
    ]
    kept, dropped = without_stale_pod_events(events, pods)
    assert dropped == 3
    assert [e["object"] for e in kept] == ["Pod/crashing-pod", "Pod/crashing-pod", "Deployment/payment-service"]


async def test_saved_evidence_can_be_reanalysed_without_tools():
    from tests.fakes import ScriptedChatModel, scope
    model = ScriptedChatModel(messages=iter(["payment-service is down"]), structured_replies=[report()])
    evidence = [Evidence(source="list_pods", arguments={}, step=Step.COLLECT_NAMESPACE_OVERVIEW, result={"pods": []})]
    result = await reanalyze_evidence(ModelRouter.single(model), "Checkout failing", scope(), "shop", evidence, [])
    assert result.analysis == "payment-service is down"
    assert result.report.root_cause_service == "payment-service"
    assert result.trace_id is None


def test_slow_call_log_lines_point_at_the_dependency():
    evidence = [Evidence(source="get_pod_logs", arguments={"pod": "order-service-a"}, step=Step.INSPECT_FLAGGED_PROBLEMS, result={"lines": [
        "WARNING: slow upstream call: POST http://payment-service/payments took 3.02s",
    ]})]
    assert services_blamed_in_logs(evidence, {"payment-service", "order-service"}) == {"payment-service"}


def test_cpu_starved_service_is_stated_as_a_finding():
    evidence = [
        Evidence(source="get_metrics", step=Step.INSPECT_FLAGGED_PROBLEMS,
                 arguments={"service": "user-service", "metric": "cpu_throttled_ratio"}, result={"latest": 0.34, "max": 0.48}),
        Evidence(source="get_metrics", step=Step.INSPECT_FLAGGED_PROBLEMS,
                 arguments={"service": "user-service", "metric": "cpu_cores"}, result={"latest": 0.09, "max": 0.09}),
        # Throttled but nearly idle (short bursts only): not CPU-starved.
        Evidence(source="get_metrics", step=Step.INSPECT_FLAGGED_PROBLEMS,
                 arguments={"service": "payment-service", "metric": "cpu_throttled_ratio"}, result={"latest": 0.28, "max": 0.57}),
        Evidence(source="get_metrics", step=Step.INSPECT_FLAGGED_PROBLEMS,
                 arguments={"service": "payment-service", "metric": "cpu_cores"}, result={"latest": 0.004, "max": 0.004}),
        Evidence(source="get_pod_status", step=Step.INSPECT_FLAGGED_PROBLEMS, arguments={"pod": "payment-service-a"},
                 result={"app": "payment-service", "containers": [{"cpu_limit": "250m"}]}),
        Evidence(source="get_pod_status", step=Step.INSPECT_FLAGGED_PROBLEMS, arguments={"pod": "user-service-a"},
                 result={"app": "user-service", "containers": [{"cpu_limit": "250m"}]}),
    ]
    [finding] = computed_findings(evidence, cpu_throttled_ratio_threshold=0.25, cpu_min_usage_of_limit=0.15,
                                  latency_threshold_ms=1000)
    assert finding.startswith("user-service is held at its CPU limit (250m): throttled in 34%")
    assert "resource_exhaustion" in finding
    assert computed_findings(evidence, cpu_throttled_ratio_threshold=0.5, cpu_min_usage_of_limit=0.15,
                             latency_threshold_ms=1000) == []


def test_slow_now_and_recovered_services_are_stated_as_findings():
    evidence = [
        Evidence(source="get_service_overview", step=Step.COLLECT_NAMESPACE_OVERVIEW, arguments={}, result={"services": [
            {"service": "payment-service", "latency_p99_ms": 4980.0}, {"service": "user-service", "latency_p99_ms": 49.5}]}),
        Evidence(source="get_metrics", step=Step.TRACE_FAILING_DEPENDENCIES,
                 arguments={"service": "user-service", "metric": "latency_p99_ms"}, result={"latest": 49.5, "max": 4980.0}),
    ]
    findings = computed_findings(evidence, cpu_throttled_ratio_threshold=0.25, cpu_min_usage_of_limit=0.15,
                                 latency_threshold_ms=1000)
    assert findings[0] == "Slow right now (latest p99): payment-service 4980 ms."
    assert findings[1].startswith("user-service was slow earlier in the window (p99 up to 4980 ms) but has recovered")
