"""KubernetesBackend mapping and error translation, using real client model objects
and stubbed API classes (no cluster needed)."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from kubernetes import client as k8s
from kubernetes.client.rest import ApiException
from urllib3.exceptions import MaxRetryError

from cluster import ClusterError, KubernetesBackend

NAMESPACE = "shop"
CREATED = datetime(2026, 9, 27, 10, 0, tzinfo=timezone.utc)


def crashing_pod() -> k8s.V1Pod:
    return k8s.V1Pod(
        metadata=k8s.V1ObjectMeta(name="payment-abc", namespace=NAMESPACE,
                                  labels={"app": "payment-service", "version": "v2"}, creation_timestamp=CREATED),
        spec=k8s.V1PodSpec(containers=[k8s.V1Container(
            name="payment-service", image="payment-service:v2",
            resources=k8s.V1ResourceRequirements(requests={"cpu": "50m"}, limits={"cpu": "250m", "memory": "128Mi"}),
        )]),
        status=k8s.V1PodStatus(
            phase="Running",
            conditions=[k8s.V1PodCondition(type="Ready", status="False", reason="ContainersNotReady")],
            container_statuses=[k8s.V1ContainerStatus(
                name="payment-service", image="payment-service:v2", image_id="", ready=False, restart_count=7,
                state=k8s.V1ContainerState(waiting=k8s.V1ContainerStateWaiting(reason="CrashLoopBackOff")),
                last_state=k8s.V1ContainerState(terminated=k8s.V1ContainerStateTerminated(exit_code=1, reason="Error")),
            )],
        ),
    )


def replica_set(revision: int, image: str, ready: int, owner_uid: str) -> k8s.V1ReplicaSet:
    return k8s.V1ReplicaSet(
        metadata=k8s.V1ObjectMeta(
            name=f"payment-{revision}", annotations={"deployment.kubernetes.io/revision": str(revision)},
            owner_references=[k8s.V1OwnerReference(api_version="apps/v1", kind="Deployment", name="payment", uid=owner_uid)],
        ),
        spec=k8s.V1ReplicaSetSpec(
            replicas=2, selector=k8s.V1LabelSelector(match_labels={"app": "payment-service"}),
            template=k8s.V1PodTemplateSpec(
                metadata=k8s.V1ObjectMeta(labels={"app": "payment-service", "version": f"v{revision}"}),
                spec=k8s.V1PodSpec(containers=[k8s.V1Container(name="payment-service", image=image)]),
            ),
        ),
        status=k8s.V1ReplicaSetStatus(replicas=2, ready_replicas=ready),
    )


def deployment() -> k8s.V1Deployment:
    template = k8s.V1PodTemplateSpec(
        metadata=k8s.V1ObjectMeta(labels={"app": "payment-service", "version": "v2"}),
        spec=k8s.V1PodSpec(containers=[k8s.V1Container(name="payment-service", image="payment-service:v2")]),
    )
    return k8s.V1Deployment(
        metadata=k8s.V1ObjectMeta(name="payment-service", uid="dep-uid"),
        spec=k8s.V1DeploymentSpec(replicas=2, selector=k8s.V1LabelSelector(match_labels={"app": "payment-service"}),
                                  template=template),
        status=k8s.V1DeploymentStatus(ready_replicas=0, updated_replicas=2, available_replicas=0),
    )


def backend_with(core=None, apps=None) -> KubernetesBackend:
    backend = KubernetesBackend("unused", request_timeout_seconds=1)
    backend.__dict__.update(_core=core, _apps=apps)
    return backend


def test_pod_mapping_extracts_crash_details():
    core = SimpleNamespace(list_namespaced_pod=lambda *a, **kw: k8s.V1PodList(items=[crashing_pod()]))
    [pod] = backend_with(core=core).list_pods(NAMESPACE, app=None)
    container = pod.containers[0]
    assert (pod.app, pod.version, pod.phase) == ("payment-service", "v2", "Running")
    assert (container.state, container.reason, container.restart_count) == ("waiting", "CrashLoopBackOff", 7)
    assert (container.last_termination_reason, container.last_exit_code) == ("Error", 1)
    assert (container.cpu_request, container.cpu_limit, container.memory_limit) == ("50m", "250m", "128Mi")


def test_app_filter_becomes_label_selector():
    seen = {}
    def list_pods(namespace, **kwargs):
        seen.update(kwargs)
        return k8s.V1PodList(items=[])
    backend_with(core=SimpleNamespace(list_namespaced_pod=list_pods)).list_pods(NAMESPACE, app="payment-service")
    assert seen["label_selector"] == "app=payment-service"


def test_deployment_revisions_only_owned_and_newest_first():
    replica_sets = [
        replica_set(1, "payment-service:v1", ready=0, owner_uid="dep-uid"),
        replica_set(2, "payment-service:v2", ready=0, owner_uid="dep-uid"),
        replica_set(9, "other:v9", ready=2, owner_uid="someone-else"),
    ]
    apps = SimpleNamespace(
        read_namespaced_deployment=lambda *a, **kw: deployment(),
        list_namespaced_replica_set=lambda *a, **kw: k8s.V1ReplicaSetList(items=replica_sets),
    )
    detail = backend_with(apps=apps).get_deployment(NAMESPACE, "payment-service")
    assert [r.revision for r in detail.revisions] == [2, 1]
    assert detail.revisions[1].image == "payment-service:v1"


def test_logs_are_decoded_into_timestamped_lines():
    seen = {}

    def read_log(*args, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(data="2026-09-28T16:27:02Z first\n2026-09-28T16:27:03Z second\n".encode())

    lines = backend_with(core=SimpleNamespace(read_namespaced_pod_log=read_log)).get_pod_logs(NAMESPACE, "p", 10, previous=True)
    assert lines == ["2026-09-28T16:27:02Z first", "2026-09-28T16:27:03Z second"]
    assert seen["timestamps"] is True


@pytest.mark.parametrize(("status", "expected"), [(404, "Not found"), (403, "Forbidden by RBAC"), (500, "API error 500")])
def test_api_errors_become_readable_tool_errors(status, expected):
    def fail(*args, **kwargs):
        raise ApiException(status=status, reason="x")
    with pytest.raises(ClusterError, match=expected):
        backend_with(core=SimpleNamespace(read_namespaced_pod=fail)).get_pod(NAMESPACE, "p")


def test_unreachable_cluster_is_reported():
    def fail(*args, **kwargs):
        raise MaxRetryError(pool=None, url="https://127.0.0.1:6443")
    with pytest.raises(ClusterError, match="unreachable"):
        backend_with(core=SimpleNamespace(list_namespaced_pod=fail)).list_pods(NAMESPACE, None)


def test_missing_kubeconfig_explains_how_to_fix(tmp_path):
    backend = KubernetesBackend(str(tmp_path / "missing"), request_timeout_seconds=1)
    with pytest.raises(ClusterError, match="make mcp-kubeconfig"):
        backend.list_pods(NAMESPACE, None)


def test_missing_previous_container_tells_model_what_to_do_instead():
    def fail(*args, **kwargs):
        raise ApiException(status=400, reason="previous terminated container not found")
    with pytest.raises(ClusterError, match="previous=false"):
        backend_with(core=SimpleNamespace(read_namespaced_pod_log=fail)).get_pod_logs(NAMESPACE, "p", 10, previous=True)
