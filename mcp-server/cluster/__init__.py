from cluster.backend import ClusterBackend, ClusterError
from cluster.kubernetes_backend import KubernetesBackend
from config import Settings
from fake.cluster_backend import FakeClusterBackend


def create_backend(settings: Settings) -> ClusterBackend:
    if settings.backend == "fake":
        return FakeClusterBackend()
    return KubernetesBackend(settings.kubeconfig_path, settings.kube_request_timeout_seconds)


__all__ = ["ClusterBackend", "ClusterError", "FakeClusterBackend", "KubernetesBackend", "create_backend"]
