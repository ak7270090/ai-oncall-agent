from pydantic import BaseModel, Field

from agent import IncidentReport
from config import get_settings


class InvestigateRequest(BaseModel):
    question: str = Field(
        min_length=1,
        max_length=get_settings().max_question_length,
        examples=["Checkout is failing, what's wrong with payments?"],
    )


class EvidenceResponse(BaseModel):
    """One check the investigation ran. Raw tool output is summarized in the report."""

    step: str
    source: str
    arguments: dict
    error: str | None = None


class InvestigateResponse(BaseModel):
    answer: str = Field(description="The report rendered as Markdown")
    report: IncidentReport
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
