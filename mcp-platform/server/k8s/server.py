"""The Kubernetes MCP server: `python -m k8s.server` (port MCP_K8S_SERVER__PORT, 9000)."""

from mcp.server.mcpserver import MCPServer

from access.policy import build_access_policy
from base_server import add_tools, build_mcp_server, run_mcp_server
from config import Settings, get_settings
from k8s.backend import ClusterBackend
from k8s.completions import build_completion_handler
from k8s.constants import WRITE_TOOLS
from k8s.fake_backend import FakeClusterBackend
from k8s.fake_operations import FakeOperations
from k8s.kubernetes_backend import KubernetesBackend
from k8s.operations import ClusterOperations, KubernetesOperations
from k8s.resources import build_resources
from k8s.tools import build_kubernetes_tools
from k8s.write_tools import build_operation_tools


def create_backend(settings: Settings) -> ClusterBackend:
    if settings.backend == "fake":
        return FakeClusterBackend()
    return KubernetesBackend(settings.kubeconfig_path, settings.kube_request_timeout_seconds)


def create_operations(settings: Settings) -> ClusterOperations:
    if settings.backend == "fake":
        return FakeOperations()
    return KubernetesOperations(settings.operator_kubeconfig_path, settings.kube_request_timeout_seconds)


def build_k8s_server(settings: Settings, cluster: ClusterBackend | None = None,
                     operations: ClusterOperations | None = None) -> MCPServer:
    """Read tools, write tools (if enabled), team knowledge resources and completions."""
    cluster = cluster or create_backend(settings)
    policy = build_access_policy(settings, WRITE_TOOLS)
    server = build_mcp_server(settings, settings.k8s_server, policy, WRITE_TOOLS)
    add_tools(server, build_kubernetes_tools(cluster, settings))
    if settings.enable_write_tools:
        add_tools(server, build_operation_tools(cluster, operations or create_operations(settings), settings, policy))
    for resource in build_resources(cluster, settings):
        server.resource(resource.uri, name=resource.name, description=resource.description,
                        mime_type=resource.mime_type)(resource.read)
    server.completion()(build_completion_handler(cluster, settings))
    return server


def main() -> None:
    settings = get_settings()
    run_mcp_server(build_k8s_server(settings), settings, settings.k8s_server)


if __name__ == "__main__":
    main()
