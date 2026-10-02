import pytest
from langfuse import Langfuse, LangfuseOtelSpanAttributes
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from agent import (
    Evidence,
    MCPToolbox,
    ModelRouter,
    build_investigation_graph,
    reanalyze_evidence,
    run_investigation,
)
from config import Settings
from constants import INVESTIGATION_TRACE_NAME, Step
from mcp_client import list_all_tools, to_langchain_tool
from tests.fakes import (
    PAYMENT_DOWN,
    ScriptedChatModel,
    build_fake_mcp_server,
    fake_connector,
    report,
    scope,
    scripted_model,
    tool_call_message,
)
from tracing import (
    DISABLED_TRACER,
    InvestigationTracer,
    TraceLabels,
    create_tracer,
    should_export_span,
)

pytestmark = pytest.mark.anyio
SETTINGS = Settings(_env_file=None, max_follow_up_rounds=2)
TEST_PUBLIC_KEY = "pk-lf-test"
# Nothing listens here: proves an unreachable Langfuse doesn't break an investigation.
UNREACHABLE_LANGFUSE_URL = "http://127.0.0.1:9"


@pytest.fixture(scope="module")
def span_exporter():
    exporter = InMemorySpanExporter()
    # Langfuse keeps one client per public key, so build it once for the whole module.
    client = Langfuse(public_key=TEST_PUBLIC_KEY, secret_key="sk-lf-test", base_url=UNREACHABLE_LANGFUSE_URL,
                      span_exporter=exporter, should_export_span=should_export_span)
    exporter.tracer = InvestigationTracer(client, TEST_PUBLIC_KEY, {"llm_model": "fake"})
    exporter.client = client
    yield exporter
    client.shutdown()


async def traced_investigation(span_exporter, chat_model, labels=TraceLabels()):
    span_exporter.clear()
    async with fake_connector(build_fake_mcp_server(PAYMENT_DOWN))() as mcp_client:
        tools = await list_all_tools(mcp_client)
        graph = build_investigation_graph(
            ModelRouter.single(chat_model), MCPToolbox(mcp_client, tools), [to_langchain_tool(mcp_client, t) for t in tools], SETTINGS
        )
        result = await run_investigation(graph, "Checkout is failing", SETTINGS.max_follow_up_rounds,
                                         span_exporter.tracer, labels)
    span_exporter.client.flush()
    spans = span_exporter.get_finished_spans()
    by_id = {span.context.span_id: span for span in spans}
    parents = {(span.name, by_id[span.parent.span_id].name if span.parent and span.parent.span_id in by_id else None)
               for span in spans}
    return result, spans, parents


async def test_investigation_is_one_trace_with_tool_calls_under_their_step(span_exporter):
    result, spans, parents = await traced_investigation(span_exporter, scripted_model())

    assert {span.context.trace_id for span in spans} == {int(result.trace_id, 16)}
    [root] = [span for span in spans if span.parent is None]
    assert root.name == INVESTIGATION_TRACE_NAME
    assert ("list_pods", Step.COLLECT_NAMESPACE_OVERVIEW) in parents
    assert ("get_pod_logs", Step.INSPECT_FLAGGED_PROBLEMS) in parents
    assert ("list_pods", Step.TRACE_FAILING_DEPENDENCIES) in parents
    assert not any(span.name.startswith("tools/call") for span in spans)


async def test_tools_the_llm_requests_appear_under_run_requested_tools(span_exporter):
    chat_model = scripted_model(tool_call_message(("get_pod_status", {"pod": "order-service-a"})), "done")
    _, _, parents = await traced_investigation(span_exporter, chat_model)
    assert ("get_pod_status", Step.RUN_REQUESTED_TOOLS) in parents


async def test_unreachable_langfuse_only_loses_the_trace_link(span_exporter):
    result, _, _ = await traced_investigation(span_exporter, scripted_model())
    assert result.report.root_cause_service == "payment-service"
    assert result.trace_id and result.trace_url is None


async def test_labels_become_trace_tags(span_exporter):
    labels = TraceLabels(tags=("eval", "incident:db-down"))
    _, spans, _ = await traced_investigation(span_exporter, scripted_model(), labels)
    [root] = [span for span in spans if span.parent is None]
    assert tuple(root.attributes[LangfuseOtelSpanAttributes.TRACE_TAGS]) == labels.tags


async def test_traceparent_puts_the_investigation_inside_the_callers_trace(span_exporter):
    caller_trace_id, caller_span_id = "4bf92f3577b34da6a3ce929d0e0e4736", "00f067aa0ba902b7"
    labels = TraceLabels(traceparent=f"00-{caller_trace_id}-{caller_span_id}-01")
    result, spans, _ = await traced_investigation(span_exporter, scripted_model(), labels)
    [root] = [span for span in spans if span.name == INVESTIGATION_TRACE_NAME]
    assert result.trace_id == caller_trace_id
    assert {span.context.trace_id for span in spans} == {int(caller_trace_id, 16)}
    assert root.parent.span_id == int(caller_span_id, 16)


async def test_reanalysis_is_traced_with_both_llm_calls(span_exporter):
    span_exporter.clear()
    model = ScriptedChatModel(messages=iter(["payment-service is down"]), structured_replies=[report()])
    evidence = [Evidence(source="list_pods", arguments={}, step=Step.COLLECT_NAMESPACE_OVERVIEW, result={"pods": []})]
    result = await reanalyze_evidence(ModelRouter.single(model), "Checkout failing", scope(), "shop", evidence, [], span_exporter.tracer)
    span_exporter.client.flush()
    spans = span_exporter.get_finished_spans()
    assert {span.context.trace_id for span in spans} == {int(result.trace_id, 16)}
    assert sum(span.attributes.get("langfuse.observation.type") == "generation" for span in spans) >= 1
    assert result.report.root_cause_service == "payment-service"


def test_tracing_is_off_without_keys():
    assert create_tracer(Settings(_env_file=None)) is DISABLED_TRACER
    assert not DISABLED_TRACER.enabled
