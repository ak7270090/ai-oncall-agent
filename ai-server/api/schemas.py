from typing import Any

from pydantic import BaseModel, Field

from agent import IncidentReport, IncidentScope
from config import get_settings


class InvestigateRequest(BaseModel):
    question: str = Field(
        min_length=1,
        max_length=get_settings().max_question_length,
        examples=["Checkout is failing, what's wrong with payments?"],
    )
    include_evidence_results: bool = Field(
        default=False, description="Also return raw tool output per check (large; for debugging and evals)")


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


class ToolDescription(BaseModel):
    name: str
    description: str
    input_schema: dict


class ToolsResponse(BaseModel):
    tools: list[ToolDescription]


class StatusResponse(BaseModel):
    status: str
