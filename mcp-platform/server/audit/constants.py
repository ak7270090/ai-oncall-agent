"""Fixed values of the audit log (Phase 20)."""

from enum import StrEnum


class AuditEvent(StrEnum):
    TOOL_CALL = "tool_call"
    APPROVAL_REQUESTED = "approval_requested"   # a write tool asked a human (elicitation)
    SAMPLING_REQUESTED = "sampling_requested"   # a tool asked the client's LLM (log summary)
    REFUSED = "refused"


class AuditOutcome(StrEnum):
    OK = "ok"
    ERROR = "error"
    REFUSED = "refused"


# Method of an approval request inside an `input_required` result.
ELICITATION_METHOD = "elicitation/create"
# `_meta` key of the caller's W3C trace context (the Langfuse trace of the agent's run).
TRACEPARENT_KEY = "traceparent"
