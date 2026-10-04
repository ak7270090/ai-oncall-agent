"""The steps of an investigation, one method each. Every step receives the whole
InvestigationState and returns only the keys it changes (see state.py).
graph.py wires these methods into the LangGraph flow."""

from collections.abc import Sequence

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.tools import BaseTool
from langgraph.prebuilt import ToolNode

from config import Settings
from investigation.constants import Step
from investigation.evidence import collection_steps
from investigation.evidence.analysis import computed_findings
from investigation.evidence.collection_steps import CollectionLimits
from investigation.evidence.mcp_toolbox import MCPToolbox, evidence_from_tool_messages
from investigation.models import IncidentReport, IncidentScope
from investigation.prompts import report_messages, root_cause_messages, scope_messages
from investigation.workflow.state import InvestigationState
from llm.chat_model import invoke_llm
from llm.model_router import ModelRouter


class InvestigationNodes:
    def __init__(self, models: ModelRouter, toolbox: MCPToolbox, tools: list[BaseTool], settings: Settings,
                 operations: Sequence[str] = ()):
        self._toolbox = toolbox
        self._operations = list(operations)
        self._settings = settings
        self._limits = CollectionLimits(
            error_rate_threshold=settings.error_rate_threshold,
            latency_threshold_ms=settings.latency_threshold_ms,
            max_pods=settings.max_pods_to_inspect,
            max_services=settings.max_services_to_inspect,
            log_lines=settings.log_lines,
            summarize_logs=settings.summarize_logs,
            use_service_knowledge=settings.use_service_knowledge,
        )
        # Each LLM step gets the model tier the router assigns it (FAST_MODEL_STEPS).
        self._scope_model = models.for_step(Step.EXTRACT_INCIDENT_SCOPE).with_structured_output(IncidentScope)
        self._root_cause_model = models.for_step(Step.FIND_ROOT_CAUSE).bind_tools(tools)
        self._report_model = models.for_step(Step.WRITE_REPORT).with_structured_output(IncidentReport)
        self._requested_tool_runner = ToolNode(tools)

    # --- LLM: understand the question -------------------------------------------------

    async def extract_incident_scope(self, state: InvestigationState) -> dict:
        """LLM call 1: namespace, suspected services, symptom and time window from the question."""
        scope = await invoke_llm(self._scope_model, scope_messages(state["question"]))
        return {
            "scope": scope,
            "namespace": scope.namespace or self._settings.default_namespace,
            "steps": [Step.EXTRACT_INCIDENT_SCOPE],
            "llm_calls": 1,
        }

    # --- Code: collect evidence (no LLM) -------------------------------------------------

    async def collect_namespace_overview(self, state: InvestigationState) -> dict:
        notes: list[str] = []
        found = await collection_steps.collect_namespace_overview(self._toolbox, state["namespace"], self._limits, notes)
        return {"evidence": found, "notes": notes, "steps": [Step.COLLECT_NAMESPACE_OVERVIEW]}

    async def inspect_flagged_problems(self, state: InvestigationState) -> dict:
        notes: list[str] = []
        found = await collection_steps.inspect_flagged_problems(
            self._toolbox, state["namespace"], state["scope"], state["evidence"], self._limits, notes)
        return {"evidence": found, "notes": notes, "steps": [Step.INSPECT_FLAGGED_PROBLEMS]}

    async def trace_failing_dependencies(self, state: InvestigationState) -> dict:
        notes: list[str] = []
        found = await collection_steps.trace_failing_dependencies(
            self._toolbox, state["namespace"], state["evidence"], state["scope"].window_minutes, self._limits, notes)
        return {"evidence": found, "notes": notes, "steps": [Step.TRACE_FAILING_DEPENDENCIES]}

    # --- LLM: reason, optionally asking for more tools -------------------------------------

    async def find_root_cause(self, state: InvestigationState) -> dict:
        """LLM call 2 (repeated after each follow-up round): reason over all evidence;
        may answer, or request more tool calls."""
        opening: list[BaseMessage] = []
        if not state["messages"]:
            opening = root_cause_messages(state["question"], state["scope"], state["namespace"], state["evidence"],
                                          self._findings(state))
        response = await invoke_llm(self._root_cause_model, [*state["messages"], *opening])
        return {"messages": [*opening, response], "steps": [Step.FIND_ROOT_CAUSE], "llm_calls": 1}

    def next_step_after_root_cause(self, state: InvestigationState) -> Step:
        """Route: run the tools the LLM asked for (while rounds are left), else write the report."""
        last = state["messages"][-1]
        wants_tools = isinstance(last, AIMessage) and bool(last.tool_calls)
        rounds_left = state["follow_up_rounds"] < self._settings.max_follow_up_rounds
        return Step.RUN_REQUESTED_TOOLS if wants_tools and rounds_left else Step.WRITE_REPORT

    async def run_requested_tools(self, state: InvestigationState) -> dict:
        """Execute the LLM's tool calls (in parallel) and keep the results as evidence too."""
        request = state["messages"][-1]
        requested_calls = {call["id"]: call for call in request.tool_calls}
        output = await self._requested_tool_runner.ainvoke({"messages": [request]})
        return {
            "messages": output["messages"],
            "evidence": evidence_from_tool_messages(output["messages"], requested_calls),
            "follow_up_rounds": state["follow_up_rounds"] + 1,
            "steps": [Step.RUN_REQUESTED_TOOLS],
        }

    def _findings(self, state: InvestigationState) -> list[str]:
        settings = self._settings
        return computed_findings(state["evidence"], settings.cpu_throttled_ratio_threshold,
                                 settings.cpu_min_usage_of_limit, settings.latency_threshold_ms)

    # --- LLM: write the report -----------------------------------------------------------

    async def write_report(self, state: InvestigationState) -> dict:
        """LLM call 3: a typed IncidentReport from the evidence and the analysis."""
        analysis = "\n\n".join(m.text for m in state["messages"] if isinstance(m, AIMessage) and m.text)
        messages = report_messages(state["question"], state["evidence"], state["notes"], analysis,
                                   self._findings(state), self._operations)
        report = await invoke_llm(self._report_model, messages)
        return {"report": report, "steps": [Step.WRITE_REPORT], "llm_calls": 1}
