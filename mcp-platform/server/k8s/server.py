"""The Kubernetes MCP server: `python -m k8s.server` (port MCP_K8S_SERVER__PORT, 9000)."""

from mcp.server.mcpserver import MCPServer

from auth.roles import build_access_policy
from base_server import add_tools, build_mcp_server, run_mcp_server
from k8s.cluster.access import ClusterReader, ClusterWriter
from k8s.cluster.fake import FakeClusterReader, FakeClusterWriter
from k8s.cluster.kubernetes_api import KubernetesReader, KubernetesWriter
from k8s.config import K8sServerSettings, get_k8s_settings
from k8s.constants import WRITE_TOOLS
from k8s.deployments import build_deployment_tools
from k8s.events import build_event_tools
from k8s.knowledge import build_completion_handler, build_resources
from k8s.pods import build_pod_tools


def create_reader(settings: K8sServerSettings) -> ClusterReader:
    if settings.backend == "fake":
        return FakeClusterReader()
    return KubernetesReader(settings.kubeconfig_path, settings.kube_request_timeout_seconds)


def create_writer(settings: K8sServerSettings) -> ClusterWriter:
    if settings.backend == "fake":
        return FakeClusterWriter()
    return KubernetesWriter(settings.operator_kubeconfig_path, settings.kube_request_timeout_seconds)


def build_k8s_server(settings: K8sServerSettings, reader: ClusterReader | None = None,
                     writer: ClusterWriter | None = None) -> MCPServer:
    """Pod, deployment and event tools (changes only with MCP_ENABLE_WRITE_TOOLS), the
    team's knowledge as resources, and completions for them."""
    reader = reader or create_reader(settings)
    if settings.enable_write_tools:
        writer = writer or create_writer(settings)
    else:
        writer = None
    policy = build_access_policy(settings, WRITE_TOOLS)
    server = build_mcp_server(settings, settings.k8s_server, policy, WRITE_TOOLS)
    add_tools(server, build_pod_tools(reader, settings))
    add_tools(server, build_deployment_tools(reader, writer, settings, policy))
    add_tools(server, build_event_tools(reader, settings))
    for resource in build_resources(reader, settings):
        server.resource(resource.uri, name=resource.name, description=resource.description,
                        mime_type=resource.mime_type)(resource.read)
    server.completion()(build_completion_handler(reader, settings))
    return server


def main() -> None:
    settings = get_k8s_settings()
    run_mcp_server(build_k8s_server(settings), settings, settings.k8s_server)


if __name__ == "__main__":
    main()
