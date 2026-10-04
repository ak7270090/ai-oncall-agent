"""The contract with the MCP servers: tool, resource, metric and argument names the AI
server uses, and how a gateway renames them."""

from enum import StrEnum


class McpTool(StrEnum):
    """MCP tools the fixed investigation steps call by name."""

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


class McpResource(StrEnum):
    """MCP resource URI templates the investigation reads."""

    RUNBOOK = "runbook://{service}"
    TOPOLOGY = "topology://{namespace}"


class Metric(StrEnum):
    """Metric names accepted by the get_metrics tool."""

    ERROR_RATE = "error_rate"
    LATENCY_P99_MS = "latency_p99_ms"
    CPU_CORES = "cpu_cores"
    CPU_THROTTLED_RATIO = "cpu_throttled_ratio"


# get_pod_logs argument asking the MCP server for a summary (via MCP sampling).
SUMMARIZE_ARGUMENT = "summarize"

# How a gateway that multiplexes several MCP servers renames their tools and resource
# URIs (agentgateway): k8s_list_pods, k8s+runbook://payment-service.
GATEWAY_TOOL_SEPARATOR = "_"
GATEWAY_URI_SEPARATOR = "+"
