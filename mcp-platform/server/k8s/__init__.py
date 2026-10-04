"""The Kubernetes tool set (MCP_TOOLSETS=kubernetes): pods, deployments, events and logs
(tools.py), write tools with approval (write_tools.py), team knowledge as resources
(resources.py, completions.py), and the backends they read and change through
(kubernetes_backend.py and operations.py for a real cluster, fake_*.py for
MCP_BACKEND=fake)."""

from config import Settings
from k8s.backend import ClusterBackend, ClusterError
from k8s.completions import build_completion_handler
from k8s.fake_backend import FakeClusterBackend
from k8s.fake_operations import FakeOperations
from k8s.kubernetes_backend import KubernetesBackend
from k8s.operations import ClusterOperations, KubernetesOperations
from k8s.resources import build_resources
from k8s.tools import build_kubernetes_tools
from k8s.write_tools import build_operation_tools


def create_operations(settings: Settings) -> ClusterOperations:
    if settings.backend == "fake":
        return FakeOperations()
    return KubernetesOperations(settings.operator_kubeconfig_path, settings.kube_request_timeout_seconds)


def create_backend(settings: Settings) -> ClusterBackend:
    if settings.backend == "fake":
        return FakeClusterBackend()
    return KubernetesBackend(settings.kubeconfig_path, settings.kube_request_timeout_seconds)


__all__ = [
    "ClusterBackend",
    "ClusterError",
    "ClusterOperations",
    "FakeClusterBackend",
    "FakeOperations",
    "KubernetesBackend",
    "KubernetesOperations",
    "build_completion_handler",
    "build_kubernetes_tools",
    "build_operation_tools",
    "build_resources",
    "create_backend",
    "create_operations",
]
