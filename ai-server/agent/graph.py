r"""The investigation as a LangGraph state machine.

    START → understand → sweep → focus → follow_dependencies → correlate ⇄ follow_up
                                                                   └──────→ report → END

understand / correlate / report use the LLM; sweep / focus / follow_dependencies are
deterministic code calling MCP tools, so the key checks run every time.
"""

import json
import operator
from typing import Annotated, Any, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode

from agent import evidence as gather
from agent.chat_model import LLMError
from agent.models import Evidence, IncidentReport, IncidentScope
from agent.prompts import CORRELATE_PROMPT, REPORT_PROMPT, UNDERSTAND_PROMPT
from agent.toolbox import MCPToolbox
from config import Settings

UNDERSTAND, SWEEP, FOCUS, FOLLOW_DEPENDENCIES = "understand", "sweep", "focus", "follow_dependencies"
CORRELATE, FOLLOW_UP, REPORT = "correlate", "follow_up", "report"


class InvestigationState(TypedDict):
    question: str
    scope: IncidentScope | None
    namespace: str
    evidence: Annotated[list[Evidence], operator.add]
    notes: Annotated[list[str], operator.add]
    steps: Annotated[list[str], operator.add]
    llm_calls: Annotated[int, operator.add]
    messages: Annotated[list[BaseMessage], add_messages]
    follow_up_rounds: int
    report: IncidentReport | None


def evidence_json(evidence: list[Evidence]) -> str:
    items = [e.model_dump(exclude_none=True) for e in evidence]
    return json.dumps(items, default=str, separators=(",", ":"))


async def invoke_llm(runnable: Any, messages: list[BaseMessage]) -> Any:
    try:
        return await runnable.ainvoke(messages)
    except Exception as error:
        raise LLMError(f"LLM call failed: {error}") from error


def _tool_messages_to_evidence(messages: list[BaseMessage], calls: dict[str, dict]) -> list[Evidence]:
    evidence = []
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        call = calls.get(message.tool_call_id, {})
        content = message.content if isinstance(message.content, str) else json.dumps(message.content)
        is_error = message.status == "error"
        try:
            result = None if is_error else json.loads(content)
        except json.JSONDecodeError:
            result = content
        evidence.append(Evidence(source=call.get("name", message.name or "unknown"), arguments=call.get("args", {}),
                                 result=result, error=content if is_error else None, step=FOLLOW_UP))
    return evidence


def build_investigation_graph(
    chat_model: BaseChatModel, toolbox: MCPToolbox, tools: list[BaseTool], settings: Settings
) -> CompiledStateGraph:
    limits = gather.GatheringLimits(
        error_rate_threshold=settings.error_rate_threshold,
        max_pods=settings.max_pods_to_inspect,
        max_services=settings.max_services_to_inspect,
        log_lines=settings.log_lines,
    )
    scope_model = chat_model.with_structured_output(IncidentScope)
    report_model = chat_model.with_structured_output(IncidentReport)
    correlate_model = chat_model.bind_tools(tools)
    tool_node = ToolNode(tools)

    async def understand(state: InvestigationState) -> dict:
        scope = await invoke_llm(scope_model, [SystemMessage(UNDERSTAND_PROMPT), HumanMessage(state["question"])])
        return {"scope": scope, "namespace": scope.namespace or settings.default_namespace,
                "steps": [UNDERSTAND], "llm_calls": 1}

    async def sweep(state: InvestigationState) -> dict:
        notes: list[str] = []
        found = await gather.sweep(toolbox, state["namespace"], notes)
        return {"evidence": found, "notes": notes, "steps": [SWEEP]}

    async def focus(state: InvestigationState) -> dict:
        notes: list[str] = []
        found = await gather.focus(toolbox, state["namespace"], state["scope"], state["evidence"], limits, notes)
        return {"evidence": found, "notes": notes, "steps": [FOCUS]}

    async def follow_dependencies(state: InvestigationState) -> dict:
        notes: list[str] = []
        found = await gather.follow_dependencies(toolbox, state["namespace"], state["evidence"], notes)
        return {"evidence": found, "notes": notes, "steps": [FOLLOW_DEPENDENCIES]}

    async def correlate(state: InvestigationState) -> dict:
        new_messages: list[BaseMessage] = []
        if not state["messages"]:
            new_messages = [
                SystemMessage(CORRELATE_PROMPT),
                HumanMessage(
                    f"Incident report: {state['question']}\n"
                    f"Understood scope: {state['scope'].model_dump_json()}\n"
                    f"Namespace: {state['namespace']}\n"
                    f"Evidence: {evidence_json(state['evidence'])}"
                ),
            ]
        response = await invoke_llm(correlate_model, [*state["messages"], *new_messages])
        return {"messages": [*new_messages, response], "steps": [CORRELATE], "llm_calls": 1}

    def after_correlate(state: InvestigationState) -> str:
        last = state["messages"][-1]
        wants_tools = isinstance(last, AIMessage) and bool(last.tool_calls)
        return FOLLOW_UP if wants_tools and state["follow_up_rounds"] < settings.max_follow_up_rounds else REPORT

    async def follow_up(state: InvestigationState) -> dict:
        last = state["messages"][-1]
        calls = {call["id"]: call for call in last.tool_calls}
        output = await tool_node.ainvoke({"messages": [last]})
        return {
            "messages": output["messages"],
            "evidence": _tool_messages_to_evidence(output["messages"], calls),
            "follow_up_rounds": state["follow_up_rounds"] + 1,
            "steps": [FOLLOW_UP],
        }

    async def report(state: InvestigationState) -> dict:
        analysis = "\n\n".join(
            m.text for m in state["messages"] if isinstance(m, AIMessage) and m.text
        ) or "(no analysis produced)"
        notes = "; ".join(state["notes"]) or "none"
        result = await invoke_llm(report_model, [
            SystemMessage(REPORT_PROMPT),
            HumanMessage(
                f"Incident report: {state['question']}\n"
                f"Evidence: {evidence_json(state['evidence'])}\n"
                f"Investigation notes: {notes}\n"
                f"Analysis: {analysis}"
            ),
        ])
        return {"report": result, "steps": [REPORT], "llm_calls": 1}

    graph = StateGraph(InvestigationState)
    for name, node in [(UNDERSTAND, understand), (SWEEP, sweep), (FOCUS, focus),
                       (FOLLOW_DEPENDENCIES, follow_dependencies), (CORRELATE, correlate),
                       (FOLLOW_UP, follow_up), (REPORT, report)]:
        graph.add_node(name, node)
    graph.add_edge(START, UNDERSTAND)
    graph.add_edge(UNDERSTAND, SWEEP)
    graph.add_edge(SWEEP, FOCUS)
    graph.add_edge(FOCUS, FOLLOW_DEPENDENCIES)
    graph.add_edge(FOLLOW_DEPENDENCIES, CORRELATE)
    graph.add_conditional_edges(CORRELATE, after_correlate, [FOLLOW_UP, REPORT])
    graph.add_edge(FOLLOW_UP, CORRELATE)
    graph.add_edge(REPORT, END)
    return graph.compile()
