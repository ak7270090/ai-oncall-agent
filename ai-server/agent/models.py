from typing import Any, Literal

from pydantic import BaseModel, Field


class IncidentScope(BaseModel):
    """What the LLM understood from the question; drives which evidence is gathered."""

    namespace: str | None = Field(description="Kubernetes namespace if the question names one, else null")
    suspected_services: list[str] = Field(description="Service names the question points at, e.g. payment-service; empty if unclear")
    symptom: str = Field(description="The reported problem in a few words, e.g. 'checkout returns errors'")
    window_minutes: int = Field(description="How far back to look, from the question (default 15)")


class Evidence(BaseModel):
    """One MCP tool call and its outcome."""

    source: str
    arguments: dict[str, Any]
    result: Any = None
    error: str | None = None
    step: str


class EvidenceCitation(BaseModel):
    source: str = Field(description="Tool the finding came from, e.g. get_pod_logs")
    finding: str = Field(description="The concrete observation, quoting values/log lines")


class IncidentReport(BaseModel):
    incident: str = Field(description="One line: what is broken")
    impact: str = Field(description="Who/what is affected")
    evidence: list[EvidenceCitation]
    likely_cause: str
    confidence: Literal["low", "medium", "high"]
    recommended_actions: list[str] = Field(description="Concrete next steps for a human; the agent cannot change anything")
    timeline: list[str] = Field(description="Timestamped events in order, if the evidence shows them")
