from cluster.backend import ClusterBackend, ClusterError
from cluster.kubernetes_backend import KubernetesBackend
from cluster.operations import ClusterOperations, KubernetesOperations
from config import Settings
from fake.cluster_backend import FakeClusterBackend
from fake.operations import FakeOperations


def create_operations(settings: Settings) -> ClusterOperations:
    if settings.backend == "fake":
        return FakeOperations()
    return KubernetesOperations(settings.operator_kubeconfig_path, settings.kube_request_timeout_seconds)


def create_backend(settings: Settings) -> ClusterBackend:
    if settings.backend == "fake":
        return FakeClusterBackend()
    return KubernetesBackend(settings.kubeconfig_path, settings.kube_request_timeout_seconds)


__all__ = [
    "ClusterOperations",
    "KubernetesOperations",
    "create_operations","ClusterBackend", "ClusterError", "FakeClusterBackend", "KubernetesBackend", "create_backend"]
