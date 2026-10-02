"""Fixed values of the AI server. Anything an operator may want to tune per
environment (thresholds, limits, URLs, timeouts) lives in config/settings.py instead."""

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


class McpTool(StrEnum):
    """MCP tools the fixed investigation steps call by name (the contract with mcp-server)."""

    GET_SERVICE_OVERVIEW = "get_service_overview"
    GET_METRICS = "get_metrics"
    LIST_PODS = "list_pods"
    GET_POD_STATUS = "get_pod_status"
    GET_POD_LOGS = "get_pod_logs"
    LIST_DEPLOYMENTS = "list_deployments"
    GET_DEPLOYMENT = "get_deployment"
    LIST_EVENTS = "list_events"


class Metric(StrEnum):
    """Metric names accepted by the get_metrics tool."""

    ERROR_RATE = "error_rate"
    LATENCY_P99_MS = "latency_p99_ms"
    CPU_CORES = "cpu_cores"
    CPU_THROTTLED_RATIO = "cpu_throttled_ratio"


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

# API status values.
HEALTH_STATUS_OK = "ok"
READY_STATUS = "ready"

# Shown to API callers instead of provider error details (which go to the server log).
LLM_FAILURE_MESSAGE = "The LLM provider request failed. See server logs for details."
