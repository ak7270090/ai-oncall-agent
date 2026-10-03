from typing import Any, Literal

from pydantic import BaseModel, Field

from constants import McpOperation


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


CauseCategory = Literal[
    "dependency_unavailable",  # something a service calls is down / has no pods / refuses connections
    "bad_deployment",          # a recent rollout introduced the failure
    "crash_loop",              # containers keep crashing (startup failure, bad config, OOM)
    "resource_exhaustion",     # CPU/memory at or near limits (throttling, OOM)
    "slow_dependency",         # a dependency answers but too slowly
    "no_incident",             # evidence shows everything healthy
    "other",
]


class ProposedAction(BaseModel):
    """A change the report proposes. Nothing runs until a human approves it (POST /actions)."""

    operation: McpOperation = Field(description="Which operation, from the available operations only")
    deployment: str = Field(description="Deployment to change, e.g. payment-service")
    replicas: int | None = Field(description="scale_deployment only: the desired number of pods; else null")
    revision: int | None = Field(
        description="rollback_deployment only: the revision to go back to (from get_deployment); else null")
    reason: str = Field(description="Why this fixes the root cause, citing the evidence")

    def tool_arguments(self, namespace: str) -> dict[str, Any]:
        arguments: dict[str, Any] = {"name": self.deployment, "namespace": namespace}
        if self.operation == McpOperation.SCALE_DEPLOYMENT:
            arguments["replicas"] = self.replicas
        if self.operation == McpOperation.ROLLBACK_DEPLOYMENT:
            arguments["revision"] = self.revision
        return arguments

    def describe(self) -> str:
        detail = {McpOperation.SCALE_DEPLOYMENT: f" to {self.replicas} replicas",
                  McpOperation.ROLLBACK_DEPLOYMENT: f" to revision {self.revision}"}.get(self.operation, "")
        return f"{self.operation} {self.deployment}{detail}"


class IncidentReport(BaseModel):
    incident: str = Field(description="One line: what is broken")
    cause_category: CauseCategory = Field(description="Which kind of failure the ROOT cause is (not the symptom)")
    root_cause_service: str | None = Field(
        description="Service/deployment where the root cause lies (e.g. payments-db), not the one showing symptoms; null if unknown")
    impact: str = Field(description="Who/what is affected")
    evidence: list[EvidenceCitation]
    likely_cause: str
    confidence: Literal["low", "medium", "high"]
    recommended_actions: list[str] = Field(description="Concrete next steps for a human; the agent cannot change anything")
    proposed_actions: list[ProposedAction] = Field(
        description="Changes that would fix the root cause, using only the available operations; each "
                    "needs a human's approval. Empty if none fits or the evidence is unclear")
    timeline: list[str] = Field(description="Timestamped events in order, if the evidence shows them")

    def to_markdown(self) -> str:
        lines = [
            f"**Incident:** {self.incident}",
            f"**Impact:** {self.impact}",
            "",
            "**Evidence:**",
            *(f"- `{e.source}`: {e.finding}" for e in self.evidence),
            "",
            f"**Likely cause** ({self.confidence} confidence): {self.likely_cause}",
            f"**Root cause:** `{self.cause_category}` in `{self.root_cause_service or 'unknown'}`",
            "",
            "**Recommended action:**",
            *(f"- {action}" for action in self.recommended_actions),
        ]
        if self.proposed_actions:
            lines += ["", "**Proposed changes (each needs approval):**",
                      *(f"- `{a.describe()}`: {a.reason}" for a in self.proposed_actions)]
        if self.timeline:
            lines += ["", "**Timeline:**", *(f"- {entry}" for entry in self.timeline)]
        return "\n".join(lines)
