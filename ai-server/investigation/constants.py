"""Fixed values of the investigation (graph steps, live events, evidence reading)."""

from enum import StrEnum


class Step(StrEnum):
    """Steps (LangGraph nodes) of an investigation, in the order they run. The value is
    also recorded on every Evidence item and returned in the API response's `steps`."""

    EXTRACT_INCIDENT_SCOPE = "extract_incident_scope"
    COLLECT_NAMESPACE_OVERVIEW = "collect_namespace_overview"
    INSPECT_FLAGGED_PROBLEMS = "inspect_flagged_problems"
    TRACE_FAILING_DEPENDENCIES = "trace_failing_dependencies"
    FIND_ROOT_CAUSE = "find_root_cause"
    RUN_REQUESTED_TOOLS = "run_requested_tools"
    WRITE_REPORT = "write_report"


class StreamEvent(StrEnum):
    """Event types of POST /investigate/stream (the SSE `event:` field)."""

    STEP = "step"
    TOOL = "tool"
    PROGRESS = "progress"
    LLM = "llm"
    NOTE = "note"
    REPORT = "report"
    ERROR = "error"


class EventStatus(StrEnum):
    STARTED = "started"
    FINISHED = "finished"
    FAILED = "failed"


# Graph size, for LangGraph's recursion limit: the fixed steps run once each; every
# follow-up round adds RUN_REQUESTED_TOOLS + FIND_ROOT_CAUSE.
GRAPH_STEPS_WITHOUT_FOLLOW_UPS = 6
GRAPH_STEPS_PER_FOLLOW_UP = 2

# Log lines containing one of these (lower-cased) report a failed or slow call to another
# service, e.g. "upstream unavailable: POST http://payment-service/payments".
FAILED_CALL_LOG_HINTS = (
    "upstream", "slow", "unavailable", "connection refused", "connecterror",
    "timed out", "timeout", "could not connect",
)

# Kubernetes vocabulary used when reading tool results.
POD_OBJECT_PREFIX = "Pod/"
PROBE_FAILURE_EVENT_REASON = "Unhealthy"
RUNNING_POD_STATUS = "Running"

# Most trace tags a caller may send with /investigate.
MAX_TRACE_TAGS = 10

# Longest error text sent in a streamed tool event.
MAX_STREAMED_ERROR_LENGTH = 300
# Hex characters (the random end) of a LangChain run id used as a streamed call_id.
CALL_ID_LENGTH = 8
