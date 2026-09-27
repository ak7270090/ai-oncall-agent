from dataclasses import dataclass

from langchain_core.messages import AIMessage
from langgraph.graph.state import CompiledStateGraph

from agent.models import Evidence, IncidentReport
from agent.report import render_markdown

# understand, sweep, focus, follow_dependencies, correlate, report; each follow-up
# round adds follow_up + correlate.
FIXED_GRAPH_STEPS = 6
STEPS_PER_FOLLOW_UP = 2


@dataclass(frozen=True)
class InvestigationResult:
    report: IncidentReport
    answer: str
    evidence: list[Evidence]
    notes: list[str]
    steps: list[str]
    llm_calls: int
    follow_up_limit_reached: bool


def _still_wanted_tools(messages: list) -> bool:
    last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
    return bool(last_ai and last_ai.tool_calls)


async def run_investigation(graph: CompiledStateGraph, question: str, max_follow_up_rounds: int) -> InvestigationResult:
    final = await graph.ainvoke(
        {"question": question, "scope": None, "namespace": "", "evidence": [], "notes": [], "steps": [],
         "llm_calls": 0, "messages": [], "follow_up_rounds": 0, "report": None},
        {"recursion_limit": FIXED_GRAPH_STEPS + STEPS_PER_FOLLOW_UP * max_follow_up_rounds + 1},
    )
    return InvestigationResult(
        report=final["report"],
        answer=render_markdown(final["report"]),
        evidence=final["evidence"],
        notes=final["notes"],
        steps=final["steps"],
        llm_calls=final["llm_calls"],
        follow_up_limit_reached=_still_wanted_tools(final["messages"]),
    )
