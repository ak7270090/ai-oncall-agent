from functools import lru_cache
from pathlib import Path

from base_server import BaseServerSettings
from config import McpSettings, ServerIdentity


class K8sServerIdentity(ServerIdentity):
    name: str = "oncall-k8s"
    port: int = 9000
    public_url: str = "http://127.0.0.1:9000/mcp"
    audit_log_path: Path = Path("logs/audit-k8s.jsonl")


class KubernetesSettings(McpSettings):
    k8s_server: K8sServerIdentity = K8sServerIdentity()
    # Credentials of the read-only `mcp-server` ServiceAccount (`make mcp-kubeconfig`),
    # not the cluster-admin kubeconfig.
    kubeconfig_path: str = ".kube/config"
    kube_request_timeout_seconds: float = 10
    # Write tools (restart / scale / roll back a Deployment), each asking a human for
    # approval (MCP elicitation). Off by default; they use the separate `mcp-operator`
    # ServiceAccount (`make mcp-kubeconfig` writes its kubeconfig).
    enable_write_tools: bool = False
    operator_kubeconfig_path: str = ".kube/operator-config"
    max_replicas: int = 5

    # get_pod_logs(summarize=true): summarize only logs at least this long; limit the
    # summary's length; reuse fetched lines this long (the sampling retry must see the same).
    log_summary_min_lines: int = 40
    log_summary_max_tokens: int = 500
    log_cache_seconds: float = 30

    # Team knowledge published as MCP resources: runbooks/<service>.md and
    # topology/<namespace>.json (default: mcp-platform/server/knowledge).
    knowledge_dir: Path = Path(__file__).resolve().parents[1] / "knowledge"
    # Most values returned for one completion request.
    max_completion_values: int = 100


class K8sServerSettings(BaseServerSettings, KubernetesSettings):
    """Everything the Kubernetes MCP server reads."""


@lru_cache
def get_k8s_settings() -> K8sServerSettings:
    return K8sServerSettings()
