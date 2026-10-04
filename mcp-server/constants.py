"""Fixed values of the MCP server. Anything an operator may want to tune per
environment (URLs, timeouts, allowed namespaces, rate windows) lives in
config.py instead. Fake incident data lives in fake_incident.py."""

from enum import StrEnum
from typing import Literal

# Tool argument contract: defaults and upper bounds published in each tool's JSON Schema.
DEFAULT_LOG_LINES = 50
MAX_LOG_LINES = 500
DEFAULT_EVENT_LIMIT = 20
MAX_EVENT_LIMIT = 100
DEFAULT_HISTORY_MINUTES = 15
MAX_HISTORY_MINUTES = 120

# Kubernetes object/label value syntax; also keeps values safe to embed in PromQL.
NAME_PATTERN = r"^[a-z0-9]([a-z0-9.-]{0,61}[a-z0-9])?$"

# Kubernetes vocabulary.
REVISION_ANNOTATION = "deployment.kubernetes.io/revision"
WARNING_EVENT_TYPE = "Warning"
# Set on the pod template to make a Deployment restart its pods (what `kubectl rollout restart` does).
RESTARTED_AT_ANNOTATION = "kubectl.kubernetes.io/restartedAt"
# Label every ReplicaSet adds to its pod template; dropped when restoring an old template.
POD_TEMPLATE_HASH_LABEL = "pod-template-hash"

# Metrics offered by get_metrics, and the unit each is reported in.
class Metric(StrEnum):
    REQUEST_RATE = "request_rate"
    ERROR_RATE = "error_rate"
    ERROR_COUNT = "error_count"
    LATENCY_P99_MS = "latency_p99_ms"
    CPU_CORES = "cpu_cores"
    CPU_THROTTLED_RATIO = "cpu_throttled_ratio"
    MEMORY_MB = "memory_mb"


# Type of the get_metrics `metric` argument. A Literal gives the model an inline `enum`
# in the tool's JSON Schema; an Enum type would become a `$ref` instead.
MetricName = Literal[tuple(metric.value for metric in Metric)]

METRIC_UNITS: dict[Metric, str] = {
    Metric.REQUEST_RATE: "req/s",
    Metric.ERROR_RATE: "ratio (0-1) of 5xx responses",
    Metric.ERROR_COUNT: "5xx responses in window",
    Metric.LATENCY_P99_MS: "ms",
    Metric.CPU_CORES: "cores per pod (avg); compare with the container cpu_limit",
    Metric.CPU_THROTTLED_RATIO: "ratio (0-1) of CPU periods throttled at the container limit",
    Metric.MEMORY_MB: "MiB per pod (avg)",
}
SERVICE_OVERVIEW_METRICS: tuple[Metric, ...] = (Metric.REQUEST_RATE, Metric.ERROR_RATE, Metric.LATENCY_P99_MS)
METRIC_VALUE_DECIMALS = 4
BYTES_PER_MIB = 1024 * 1024

# Log summaries through MCP sampling (k8s/log_summary.py): what the summary request
# asks of the client's model (0-1; cheap and fast matter more than intelligence), and
# how many raw lines are kept next to the summary.
LOG_SUMMARY_TASK = "summarize_pod_logs"
LOG_SUMMARY_COST_PRIORITY = 0.8
LOG_SUMMARY_SPEED_PRIORITY = 0.7
LOG_SUMMARY_INTELLIGENCE_PRIORITY = 0.2
LOG_LINES_KEPT_WITH_SUMMARY = 5

# MCP resource URI templates (Phase 13). The agent reads them by these names too.
RUNBOOK_URI = "runbook://{service}"
TOPOLOGY_URI = "topology://{namespace}"
DEPLOYMENT_SPEC_URI = "k8s://{namespace}/deployments/{name}"

HEALTH_STATUS_OK = "ok"

# Tool sets one server process may serve (Phase 22): the same code runs as a Kubernetes
# server and a Prometheus server, each with only its own credentials.
class Toolset(StrEnum):
    KUBERNETES = "kubernetes"
    PROMETHEUS = "prometheus"


# Write tools (Phase 18): the only tools that change the cluster.
class Operation(StrEnum):
    RESTART_DEPLOYMENT = "restart_deployment"
    SCALE_DEPLOYMENT = "scale_deployment"
    ROLLBACK_DEPLOYMENT = "rollback_deployment"


WRITE_TOOLS = frozenset(Operation)

# Authentication (Phase 19): OAuth scopes of the MCP server's bearer tokens, and how the
# tokens are signed (RS256 by the AI server, which issues them; checked with its public key).
class Scope(StrEnum):
    READ = "k8s:read"
    WRITE = "k8s:write"


TOKEN_ALGORITHM = "RS256"
TOKEN_REQUIRED_CLAIMS = ("exp", "iat", "sub", "iss", "aud", "scope")
# Who calls when there is no token: stdio, in-process, or authentication switched off.
ANONYMOUS_USER = "anonymous"

# Authorization and audit (Phase 20). JSON-RPC error code of a refused request (the
# -32000..-32099 range is left to servers).
ACCESS_DENIED_ERROR_CODE = -32003
# Methods of the requests inside an `input_required` result.
ELICITATION_METHOD = "elicitation/create"


class AuditEvent(StrEnum):
    TOOL_CALL = "tool_call"
    APPROVAL_REQUESTED = "approval_requested"   # a write tool asked a human (elicitation)
    SAMPLING_REQUESTED = "sampling_requested"   # a tool asked the client's LLM (log summary)
    REFUSED = "refused"


class AuditOutcome(StrEnum):
    OK = "ok"
    ERROR = "error"
    REFUSED = "refused"
