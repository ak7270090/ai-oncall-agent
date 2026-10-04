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


class McpOperation(StrEnum):
    """MCP write tools (Phase 18). Never called by the investigation: only proposed in the
    report, and run through POST /actions after a human approves."""

    RESTART_DEPLOYMENT = "restart_deployment"
    SCALE_DEPLOYMENT = "scale_deployment"
    ROLLBACK_DEPLOYMENT = "rollback_deployment"


class McpScope(StrEnum):
    """Scopes of the MCP server's bearer tokens (Phase 19). Investigations only read;
    actions (POST /actions) may also write."""

    READ = "k8s:read"
    WRITE = "k8s:write"


READ_SCOPES = (McpScope.READ,)
WRITE_SCOPES = (McpScope.READ, McpScope.WRITE)
MCP_TOKEN_ALGORITHM = "RS256"
# The agent named in the MCP tokens (`client_id`), and the person it acts for when
# nobody signed in (no API keys configured) or for its own checks (/ready).
AGENT_CLIENT_ID = "oncall-ai-server"
ANONYMOUS_USER = "anonymous"
API_KEY_HEADER = "X-API-Key"
# How a gateway that multiplexes several MCP servers renames their tools and resource
# URIs (agentgateway): k8s_list_pods, k8s+runbook://payment-service.
GATEWAY_TOOL_SEPARATOR = "_"
GATEWAY_URI_SEPARATOR = "+"


class ActionStatus(StrEnum):
    STARTING = "starting"
    AWAITING_APPROVAL = "awaiting_approval"
    DONE = "done"            # approved and made
    NOT_DONE = "not_done"    # rejected, declined or the approval timed out: nothing changed
    FAILED = "failed"        # refused by the MCP server or failed while changing


class McpResource(StrEnum):
    """MCP resource URI templates the investigation reads (the contract with mcp-server)."""

    RUNBOOK = "runbook://{service}"
    TOPOLOGY = "topology://{namespace}"


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


class ModelTier(StrEnum):
    """Strong: the configured LLM_MODEL, for reasoning. Fast: LLM_MODEL_FAST, a cheaper
    and faster model for simple tasks (log summaries); falls back to strong when unset."""

    STRONG = "strong"
    FAST = "fast"


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

# Name of the Langfuse trace recorded for each investigation.
INVESTIGATION_TRACE_NAME = "investigate"
ACTION_TRACE_NAME = "action"
# OpenTelemetry tracer name the mcp SDK uses for its own spans (not exported).
MCP_SDK_TRACER_NAME = "mcp-python-sdk"
# W3C Trace Context header (https://www.w3.org/TR/trace-context/): version-traceid-spanid-flags.
TRACEPARENT_PATTERN = r"00-(?P<trace_id>[0-9a-f]{32})-(?P<span_id>[0-9a-f]{16})-[0-9a-f]{2}"
# Most trace tags a caller may send with /investigate.
MAX_TRACE_TAGS = 10

# get_pod_logs argument asking the MCP server for a summary (via MCP sampling).
SUMMARIZE_ARGUMENT = "summarize"
# Sampling requests carry max_tokens; reasoning models count hidden reasoning tokens in
# their output limit, so the limit is applied to the answer text instead, at roughly
# this many characters per token.
APPROX_CHARS_PER_TOKEN = 4

# Longest error text sent in a streamed tool event.
MAX_STREAMED_ERROR_LENGTH = 300
# Hex characters (the random end) of a LangChain run id used as a streamed call_id.
CALL_ID_LENGTH = 8

# API status values.
HEALTH_STATUS_OK = "ok"
READY_STATUS = "ready"

# Shown to API callers instead of provider error details (which go to the server log).
LLM_FAILURE_MESSAGE = "The LLM provider request failed. See server logs for details."
