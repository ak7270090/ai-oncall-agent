"""Fixed values of the Kubernetes MCP server."""

from enum import StrEnum

# Tool argument contract: defaults and upper bounds published in each tool's JSON Schema.
DEFAULT_LOG_LINES = 50
MAX_LOG_LINES = 500
DEFAULT_EVENT_LIMIT = 20
MAX_EVENT_LIMIT = 100

# Kubernetes vocabulary.
REVISION_ANNOTATION = "deployment.kubernetes.io/revision"
WARNING_EVENT_TYPE = "Warning"
# Set on the pod template to make a Deployment restart its pods (what `kubectl rollout restart` does).
RESTARTED_AT_ANNOTATION = "kubectl.kubernetes.io/restartedAt"
# Label every ReplicaSet adds to its pod template; dropped when restoring an old template.
POD_TEMPLATE_HASH_LABEL = "pod-template-hash"

# Log summaries through MCP sampling (pods.py): what the summary request asks of
# the client's model (0-1; cheap and fast matter more than intelligence), and how many
# raw lines are kept next to the summary.
LOG_SUMMARY_TASK = "summarize_pod_logs"
LOG_SUMMARY_COST_PRIORITY = 0.8
LOG_SUMMARY_SPEED_PRIORITY = 0.7
LOG_SUMMARY_INTELLIGENCE_PRIORITY = 0.2
LOG_LINES_KEPT_WITH_SUMMARY = 5

# MCP resource URI templates (Phase 13). The agent reads them by these names too.
RUNBOOK_URI = "runbook://{service}"
TOPOLOGY_URI = "topology://{namespace}"
DEPLOYMENT_SPEC_URI = "k8s://{namespace}/deployments/{name}"


class Operation(StrEnum):
    """Write tools (Phase 18): the only tools that change the cluster."""

    RESTART_DEPLOYMENT = "restart_deployment"
    SCALE_DEPLOYMENT = "scale_deployment"
    ROLLBACK_DEPLOYMENT = "rollback_deployment"


WRITE_TOOLS = frozenset(Operation)
