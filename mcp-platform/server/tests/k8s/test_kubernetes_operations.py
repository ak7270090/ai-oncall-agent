"""KubernetesOperations against stubbed API classes (no cluster needed)."""

from types import SimpleNamespace

import pytest
from kubernetes import client as k8s

from k8s import ClusterError, KubernetesOperations

NAMESPACE = "shop"


def replica_set(revision: int, image: str, env: list[k8s.V1EnvVar]) -> k8s.V1ReplicaSet:
    return k8s.V1ReplicaSet(
        metadata=k8s.V1ObjectMeta(name=f"payment-service-{revision}",
                                  annotations={"deployment.kubernetes.io/revision": str(revision)},
                                  owner_references=[k8s.V1OwnerReference(api_version="apps/v1", kind="Deployment",
                                                                         name="payment-service", uid="dep-uid")]),
        spec=k8s.V1ReplicaSetSpec(selector=k8s.V1LabelSelector(match_labels={"app": "payment-service"}),
                                  template=k8s.V1PodTemplateSpec(
                                      metadata=k8s.V1ObjectMeta(labels={"app": "payment-service",
                                                                        "pod-template-hash": f"hash{revision}"}),
                                      spec=k8s.V1PodSpec(containers=[k8s.V1Container(name="payment-service",
                                                                                     image=image, env=env)]))),
    )


def operations_with(patches: list) -> KubernetesOperations:
    deployment = k8s.V1Deployment(
        metadata=k8s.V1ObjectMeta(name="payment-service", uid="dep-uid"),
        spec=k8s.V1DeploymentSpec(selector=k8s.V1LabelSelector(match_labels={"app": "payment-service"}),
                                  template=k8s.V1PodTemplateSpec()))
    apps = SimpleNamespace(
        read_namespaced_deployment=lambda *a, **kw: deployment,
        list_namespaced_replica_set=lambda *a, **kw: k8s.V1ReplicaSetList(items=[
            replica_set(1, "payment-service:v1", []),
            replica_set(2, "payment-service:v2", [k8s.V1EnvVar(name="FAULT_MODE", value="error")]),
        ]),
        patch_namespaced_deployment=lambda name, namespace, body, **kw: patches.append(body),
    )
    operations = KubernetesOperations("unused", request_timeout_seconds=1)
    operations.__dict__.update(_apps=apps, _api_client=k8s.ApiClient())
    return operations


def test_rollback_replaces_the_whole_template_so_settings_of_the_bad_release_go_away():
    patches = []
    operations_with(patches).rollback_deployment(NAMESPACE, "payment-service", 1)
    [[operation]] = patches
    assert operation["op"] == "replace" and operation["path"] == "/spec/template"
    container = operation["value"]["spec"]["containers"][0]
    assert container["image"] == "payment-service:v1" and not container.get("env")  # FAULT_MODE gone
    assert "pod-template-hash" not in operation["value"]["metadata"]["labels"]


def test_rollback_to_an_unknown_revision_changes_nothing():
    patches = []
    with pytest.raises(ClusterError, match="no revision 9"):
        operations_with(patches).rollback_deployment(NAMESPACE, "payment-service", 9)
    assert patches == []
