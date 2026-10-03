from typing import Any

from pydantic import BaseModel, Field

from agent import IncidentReport, IncidentScope
from agent.models import ProposedAction
from config import get_settings
from constants import MAX_TRACE_TAGS


class InvestigateRequest(BaseModel):
    question: str = Field(
        min_length=1,
        max_length=get_settings().max_question_length,
        examples=["Checkout is failing, what's wrong with payments?"],
    )
    include_evidence_results: bool = Field(
        default=False, description="Also return raw tool output per check (large; for debugging and evals)")
    trace_tags: list[str] = Field(
        default=[], max_length=MAX_TRACE_TAGS, description="Tags for this investigation's trace, e.g. incident:db-down")


class EvidenceResponse(BaseModel):
    """One check the investigation ran; `result` only when include_evidence_results is set."""

    step: str
    source: str
    arguments: dict
    error: str | None = None
    result: Any = None


class InvestigateResponse(BaseModel):
    answer: str = Field(description="The report rendered as Markdown")
    report: IncidentReport
    scope: IncidentScope
    namespace: str
    evidence: list[EvidenceResponse]
    notes: list[str]
    steps: list[str]
    llm_calls: int
    follow_up_limit_reached: bool
    llm_model: str = Field(description="The LLM_MODEL that produced this report")
    trace_id: str | None = Field(default=None, description="Langfuse trace id; null when tracing is off")
    trace_url: str | None = Field(default=None, description="Link to this investigation in Langfuse")


class ActionRequest(BaseModel):
    action: ProposedAction
    namespace: str | None = Field(default=None, description="Defaults to the configured namespace")


class ToolDescription(BaseModel):
    name: str
    description: str
    input_schema: dict
    read_only: bool = Field(description="Annotated read-only by the MCP server; only these are given to the agent")
    destructive: bool | None = Field(default=None, description="The server's destructiveHint, if set")


class ToolsResponse(BaseModel):
    tools: list[ToolDescription]


class StatusResponse(BaseModel):
    status: str
