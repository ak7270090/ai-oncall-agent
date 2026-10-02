"""Running an investigation end to end, and re-running only its reasoning (for evals)."""

from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langgraph.graph.state import CompiledStateGraph

from agent.llm.chat_model import invoke_llm
from agent.llm.prompts import report_messages, root_cause_messages
from agent.models import Evidence, IncidentReport, IncidentScope
from agent.workflow.state import new_investigation_state
from constants import GRAPH_STEPS_PER_FOLLOW_UP, GRAPH_STEPS_WITHOUT_FOLLOW_UPS
from tracing import DISABLED_TRACER, InvestigationTracer


@dataclass(frozen=True)
class InvestigationResult:
    report: IncidentReport
    answer: str
    scope: IncidentScope
    namespace: str
    evidence: list[Evidence]
    notes: list[str]
    steps: list[str]
    llm_calls: int
    follow_up_limit_reached: bool
    trace_id: str | None = None
    trace_url: str | None = None


def _still_wanted_tools(messages: list) -> bool:
    last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
    return bool(last_ai and last_ai.tool_calls)


async def run_investigation(
    graph: CompiledStateGraph, question: str, max_follow_up_rounds: int,
    tracer: InvestigationTracer = DISABLED_TRACER,
) -> InvestigationResult:
    recursion_limit = GRAPH_STEPS_WITHOUT_FOLLOW_UPS + GRAPH_STEPS_PER_FOLLOW_UP * max_follow_up_rounds + 1
    with tracer.trace_investigation(question) as trace:
        final = await graph.ainvoke(
            new_investigation_state(question), {"recursion_limit": recursion_limit, "callbacks": trace.callbacks})
        result = InvestigationResult(
            report=final["report"],
            answer=final["report"].to_markdown(),
            scope=final["scope"],
            namespace=final["namespace"],
            evidence=final["evidence"],
            notes=final["notes"],
            steps=final["steps"],
            llm_calls=final["llm_calls"],
            follow_up_limit_reached=_still_wanted_tools(final["messages"]),
            trace_id=trace.trace_id,
            trace_url=trace.trace_url,
        )
        trace.record_outcome(result.answer, {
            "namespace": result.namespace,
            "cause_category": result.report.cause_category,
            "root_cause_service": result.report.root_cause_service,
            "confidence": result.report.confidence,
            "llm_calls": result.llm_calls,
            "tool_calls": len(result.evidence),
            "follow_up_limit_reached": result.follow_up_limit_reached,
        })
    return result


async def reanalyze_evidence(
    chat_model: BaseChatModel, question: str, scope: IncidentScope, namespace: str,
    evidence: list[Evidence], notes: list[str],
) -> tuple[str, IncidentReport]:
    """find_root_cause + write_report on already-collected evidence, without follow-up
    tool calls. Used by `make replay` to test prompt changes on saved investigations."""
    analysis = await invoke_llm(chat_model, root_cause_messages(question, scope, namespace, evidence))
    report = await invoke_llm(chat_model.with_structured_output(IncidentReport),
                              report_messages(question, evidence, notes, analysis.text))
    return analysis.text, report
