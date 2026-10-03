"""Changes to the cluster (Phase 18). Separate from ClusterBackend, which only reads, and
run with the `mcp-operator` ServiceAccount: an investigation can't change anything even
by mistake."""

from datetime import datetime, timezone
from functools import cached_property
from typing import Protocol

from kubernetes import client

from cluster.backend import ClusterError
from cluster.kubernetes_backend import load_api_client, translate_errors
from constants import (
    POD_TEMPLATE_HASH_LABEL,
    RESTARTED_AT_ANNOTATION,
    REVISION_ANNOTATION,
)


class ClusterOperations(Protocol):
    """Each method performs the change and returns what was done, in one sentence."""

    def restart_deployment(self, namespace: str, name: str) -> str: ...

    def scale_deployment(self, namespace: str, name: str, replicas: int) -> str: ...

    def rollback_deployment(self, namespace: str, name: str, revision: int) -> str: ...


class KubernetesOperations:
    def __init__(self, kubeconfig_path: str, request_timeout_seconds: float):
        self._kubeconfig_path = kubeconfig_path
        self._timeout = request_timeout_seconds

    @cached_property
    def _api_client(self) -> client.ApiClient:
        return load_api_client(self._kubeconfig_path)

    @cached_property
    def _apps(self) -> client.AppsV1Api:
        return client.AppsV1Api(self._api_client)

    def restart_deployment(self, namespace: str, name: str) -> str:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        patch = {"spec": {"template": {"metadata": {"annotations": {RESTARTED_AT_ANNOTATION: now}}}}}
        with translate_errors(f"restart deployment '{name}'", namespace):
            self._apps.patch_namespaced_deployment(name, namespace, patch, _request_timeout=self._timeout)
        return f"Restarted deployment {name}: its pods are being replaced one by one."

    def scale_deployment(self, namespace: str, name: str, replicas: int) -> str:
        with translate_errors(f"scale deployment '{name}'", namespace):
            self._apps.patch_namespaced_deployment_scale(
                name, namespace, {"spec": {"replicas": replicas}}, _request_timeout=self._timeout)
        return f"Scaled deployment {name} to {replicas} replicas."

    def rollback_deployment(self, namespace: str, name: str, revision: int) -> str:
        """What `kubectl rollout undo --to-revision` does: put the pod template of that
        revision's ReplicaSet back into the Deployment."""
        with translate_errors(f"roll back deployment '{name}'", namespace):
            deployment = self._apps.read_namespaced_deployment(name, namespace, _request_timeout=self._timeout)
            selector = ",".join(f"{k}={v}" for k, v in (deployment.spec.selector.match_labels or {}).items())
            replica_sets = self._apps.list_namespaced_replica_set(
                namespace, label_selector=selector, _request_timeout=self._timeout).items
        owned = [rs for rs in replica_sets
                 if any(o.uid == deployment.metadata.uid for o in rs.metadata.owner_references or [])]
        target = next((rs for rs in owned
                       if (rs.metadata.annotations or {}).get(REVISION_ANNOTATION) == str(revision)), None)
        if target is None:
            raise ClusterError(f"Deployment '{name}' has no revision {revision}")
        template = self._api_client.sanitize_for_serialization(target.spec.template)
        template.get("metadata", {}).get("labels", {}).pop(POD_TEMPLATE_HASH_LABEL, None)
        # A JSON Patch *replaces* the template. A strategic merge patch would merge lists such
        # as `env` by name and keep settings the bad release added (found on the live cluster).
        replace_template = [{"op": "replace", "path": "/spec/template", "value": template}]
        with translate_errors(f"roll back deployment '{name}'", namespace):
            self._apps.patch_namespaced_deployment(name, namespace, replace_template, _request_timeout=self._timeout)
        return f"Rolled back deployment {name} to the pod template of revision {revision}."
