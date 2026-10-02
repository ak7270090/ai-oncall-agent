import operator
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

from agent.models import Evidence, IncidentReport, IncidentScope


class InvestigationState(TypedDict):
    """Everything an investigation knows, passed from step to step.

    Each step returns only the keys it changes. Keys annotated with a reducer
    (operator.add / add_messages) are appended to; all others are replaced.
    """

    question: str                                              # the user's report, unchanged
    scope: IncidentScope | None                                # set by extract_incident_scope
    namespace: str                                             # namespace being investigated
    evidence: Annotated[list[Evidence], operator.add]          # every tool call and its result
    notes: Annotated[list[str], operator.add]                  # what was skipped/filtered and why
    steps: Annotated[list[str], operator.add]                  # steps run so far, in order
    llm_calls: Annotated[int, operator.add]                    # LLM requests made
    messages: Annotated[list[BaseMessage], add_messages]       # the find_root_cause conversation
    follow_up_rounds: int                                      # tool rounds the LLM asked for
    report: IncidentReport | None                              # set by write_report


def new_investigation_state(question: str) -> InvestigationState:
    return InvestigationState(
        question=question, scope=None, namespace="", evidence=[], notes=[], steps=[],
        llm_calls=0, messages=[], follow_up_rounds=0, report=None,
    )
