"""Reading MCP request and result payloads as the middleware sees them (plain mappings)."""

from collections.abc import Mapping
from typing import Any

from access.constants import ELICITATION_METHOD

TRACEPARENT_KEY = "traceparent"


def extract_trace_id(params: Mapping[str, Any]) -> str | None:
    """Trace id from the W3C traceparent the client put in the request's `_meta`
    (`00-<trace id>-<span id>-<flags>`), i.e. the caller's Langfuse trace."""
    traceparent = (params.get("_meta") or {}).get(TRACEPARENT_KEY)
    parts = traceparent.split("-") if isinstance(traceparent, str) else []
    return parts[1] if len(parts) == 4 else None


def extract_questions(result: Mapping[str, Any]) -> list[str]:
    """Questions an `input_required` interim result asks the human (approvals); sampling
    requests to the client's LLM have none."""
    return [request.get("params", {}).get("message", "") for request in (result.get("inputRequests") or {}).values()
            if request.get("method") == ELICITATION_METHOD]


def to_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return value.model_dump(by_alias=True, exclude_none=True) if hasattr(value, "model_dump") else {}
