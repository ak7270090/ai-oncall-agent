from cluster.backend import ClusterBackend, ClusterError
from cluster.fake_backend import FakeBackend
from cluster.kubernetes_backend import KubernetesBackend
from config import Settings


def create_backend(settings: Settings) -> ClusterBackend:
    if settings.backend == "fake":
        return FakeBackend()
    return KubernetesBackend(settings.kubeconfig_path, settings.kube_request_timeout_seconds)


__all__ = ["ClusterBackend", "ClusterError", "FakeBackend", "KubernetesBackend", "create_backend"]
