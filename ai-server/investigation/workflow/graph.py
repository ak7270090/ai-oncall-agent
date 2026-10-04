r"""Wires the investigation steps (nodes.py) into a LangGraph flow:

    START → extract_incident_scope → collect_namespace_overview → inspect_flagged_problems
          → trace_failing_dependencies → find_root_cause ⇄ run_requested_tools
                                                       └──→ write_report → END

extract_incident_scope / find_root_cause / write_report use the LLM; the three
collection steps are deterministic code calling MCP tools, so the key checks run every time.
"""

from collections.abc import Sequence

from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from config import Settings
from investigation.constants import Step
from investigation.evidence.mcp_toolbox import MCPToolbox
from investigation.workflow.nodes import InvestigationNodes
from investigation.workflow.state import InvestigationState
from llm.model_router import ModelRouter


def build_investigation_graph(
    models: ModelRouter, toolbox: MCPToolbox, tools: list[BaseTool], settings: Settings,
    operations: Sequence[str] = (),
) -> CompiledStateGraph:
    """`operations`: write tools the MCP server offers; the report may propose them, the graph never calls them."""
    nodes = InvestigationNodes(models, toolbox, tools, settings, operations)
    graph = StateGraph(InvestigationState)

    graph.add_node(Step.EXTRACT_INCIDENT_SCOPE, nodes.extract_incident_scope)
    graph.add_node(Step.COLLECT_NAMESPACE_OVERVIEW, nodes.collect_namespace_overview)
    graph.add_node(Step.INSPECT_FLAGGED_PROBLEMS, nodes.inspect_flagged_problems)
    graph.add_node(Step.TRACE_FAILING_DEPENDENCIES, nodes.trace_failing_dependencies)
    graph.add_node(Step.FIND_ROOT_CAUSE, nodes.find_root_cause)
    graph.add_node(Step.RUN_REQUESTED_TOOLS, nodes.run_requested_tools)
    graph.add_node(Step.WRITE_REPORT, nodes.write_report)

    graph.add_edge(START, Step.EXTRACT_INCIDENT_SCOPE)
    graph.add_edge(Step.EXTRACT_INCIDENT_SCOPE, Step.COLLECT_NAMESPACE_OVERVIEW)
    graph.add_edge(Step.COLLECT_NAMESPACE_OVERVIEW, Step.INSPECT_FLAGGED_PROBLEMS)
    graph.add_edge(Step.INSPECT_FLAGGED_PROBLEMS, Step.TRACE_FAILING_DEPENDENCIES)
    graph.add_edge(Step.TRACE_FAILING_DEPENDENCIES, Step.FIND_ROOT_CAUSE)
    graph.add_conditional_edges(Step.FIND_ROOT_CAUSE, nodes.next_step_after_root_cause,
                                [Step.RUN_REQUESTED_TOOLS, Step.WRITE_REPORT])
    graph.add_edge(Step.RUN_REQUESTED_TOOLS, Step.FIND_ROOT_CAUSE)
    graph.add_edge(Step.WRITE_REPORT, END)
    return graph.compile()
