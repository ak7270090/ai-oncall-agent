"""Against the real kind cluster (`make cluster-up`); skipped when it isn't reachable."""

from pathlib import Path

import pytest
from kubernetes import client, config
from kubernetes.client.rest import ApiException

from config import Settings
from k8s.backend import ClusterError
from k8s.kubernetes_backend import KubernetesBackend

SETTINGS = Settings(_env_file=None)
NAMESPACE = SETTINGS.default_namespace
SAMPLE_APPS = {"user-service", "payment-service", "order-service"}


def _cluster_reachable() -> bool:
    if not Path(SETTINGS.kubeconfig_path).is_file():
        return False
    try:
        KubernetesBackend(SETTINGS.kubeconfig_path, request_timeout_seconds=3).list_deployments(NAMESPACE)
    except ClusterError:
        return False
    return True


pytestmark = pytest.mark.skipif(not _cluster_reachable(), reason="kind cluster not running (make cluster-up)")


@pytest.fixture(scope="module")
def backend() -> KubernetesBackend:
    return KubernetesBackend(SETTINGS.kubeconfig_path, SETTINGS.kube_request_timeout_seconds)


@pytest.fixture(scope="module")
def raw_core_api() -> client.CoreV1Api:
    """The MCP server's own credentials, used directly: proves RBAC, not our tool code, blocks access."""
    return client.CoreV1Api(config.new_client_from_config(config_file=SETTINGS.kubeconfig_path))


def test_sample_services_are_running(backend):
    pods = backend.list_pods(NAMESPACE, app=None)
    assert {p.app for p in pods} >= SAMPLE_APPS
    assert all(p.phase == "Running" for p in pods)


def test_deployment_has_rollout_history(backend):
    detail = backend.get_deployment(NAMESPACE, "payment-service")
    assert detail.revisions and detail.revisions[0].revision >= 1
    assert detail.ready_replicas == detail.desired_replicas


def test_pod_logs_readable(backend):
    pod = backend.list_pods(NAMESPACE, app="order-service")[0]
    assert backend.get_pod_logs(NAMESPACE, pod.name, tail_lines=20, previous=False)


def test_events_listable(backend):
    backend.list_events(NAMESPACE, warnings_only=False, limit=10)


def test_rbac_denies_secrets(raw_core_api):
    with pytest.raises(ApiException) as error:
        raw_core_api.list_namespaced_secret(NAMESPACE)
    assert error.value.status == 403


def test_rbac_denies_other_namespaces(raw_core_api):
    with pytest.raises(ApiException) as error:
        raw_core_api.list_namespaced_pod("kube-system")
    assert error.value.status == 403


def test_rbac_denies_writes(raw_core_api):
    pod = raw_core_api.list_namespaced_pod(NAMESPACE).items[0]
    with pytest.raises(ApiException) as error:
        raw_core_api.delete_namespaced_pod(pod.metadata.name, NAMESPACE)
    assert error.value.status == 403
