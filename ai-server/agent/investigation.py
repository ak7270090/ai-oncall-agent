"""Running an investigation end to end, and re-running only its reasoning (for evals)."""

from collections.abc import Sequence
from dataclasses import dataclass

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langgraph.graph.state import CompiledStateGraph

from agent.llm.chat_model import invoke_llm
from agent.llm.prompts import report_messages, root_cause_messages
from agent.models import Evidence, IncidentReport, IncidentScope
from agent.workflow.state import new_investigation_state
from constants import GRAPH_STEPS_PER_FOLLOW_UP, GRAPH_STEPS_WITHOUT_FOLLOW_UPS
from tracing import DISABLED_TRACER, NO_LABELS, InvestigationTracer, TraceLabels


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
    tracer: InvestigationTracer = DISABLED_TRACER, labels: TraceLabels = NO_LABELS,
    callbacks: Sequence[BaseCallbackHandler] = (),
) -> InvestigationResult:
    """`callbacks` receive every LangChain event of the run besides tracing (e.g. live streaming)."""
    recursion_limit = GRAPH_STEPS_WITHOUT_FOLLOW_UPS + GRAPH_STEPS_PER_FOLLOW_UP * max_follow_up_rounds + 1
    with tracer.trace_investigation(question, labels) as trace:
        final = await graph.ainvoke(
            new_investigation_state(question),
            {"recursion_limit": recursion_limit, "callbacks": [*trace.callbacks, *callbacks]})
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
            **_report_outcome(result.report),
            "namespace": result.namespace,
            "llm_calls": result.llm_calls,
            "tool_calls": len(result.evidence),
            "follow_up_limit_reached": result.follow_up_limit_reached,
        })
    return result


def _report_outcome(report: IncidentReport) -> dict[str, str | None]:
    return {
        "cause_category": report.cause_category,
        "root_cause_service": report.root_cause_service,
        "confidence": report.confidence,
    }


@dataclass(frozen=True)
class ReanalysisResult:
    analysis: str
    report: IncidentReport
    trace_id: str | None = None


async def reanalyze_evidence(
    chat_model: BaseChatModel, question: str, scope: IncidentScope, namespace: str,
    evidence: list[Evidence], notes: list[str],
    tracer: InvestigationTracer = DISABLED_TRACER, labels: TraceLabels = NO_LABELS,
) -> ReanalysisResult:
    """find_root_cause + write_report on already-collected evidence, without follow-up
    tool calls. Used by `make replay` to test prompt changes on saved investigations."""
    with tracer.trace_investigation(question, labels) as trace:
        traced = {"callbacks": trace.callbacks}
        analysis = await invoke_llm(chat_model.with_config(traced),
                                    root_cause_messages(question, scope, namespace, evidence))
        report = await invoke_llm(chat_model.with_structured_output(IncidentReport).with_config(traced),
                                  report_messages(question, evidence, notes, analysis.text))
        trace.record_outcome(report.to_markdown(), _report_outcome(report))
    return ReanalysisResult(analysis.text, report, trace.trace_id)
