"""The fake cluster (MCP_BACKEND=fake): serves the canned incident in fake_incident.py and
records changes instead of making them. Same behavior contract as the real cluster."""

import fake_incident
from k8s.cluster.access import no_previous_container_error, not_found_error
from k8s.constants import WARNING_EVENT_TYPE
from k8s.models import (
    ClusterEvent,
    ContainerSpec,
    DeploymentDetail,
    DeploymentSpec,
    DeploymentSummary,
    PodDetail,
    summarize_deployment,
)


class FakeClusterReader:
    """Reads the canned incident in fake_incident.py."""

    def list_pods(self, namespace: str, app: str | None) -> list[PodDetail]:
        return [p for p in fake_incident.PODS if p.namespace == namespace and (app is None or p.app == app)]

    def get_pod(self, namespace: str, name: str) -> PodDetail:
        for pod in fake_incident.PODS:
            if pod.namespace == namespace and pod.name == name:
                return pod
        raise not_found_error(f"get pod '{name}'", namespace)

    def get_pod_logs(self, namespace: str, name: str, tail_lines: int, previous: bool) -> list[str]:
        self.get_pod(namespace, name)
        logs = fake_incident.PREVIOUS_LOGS if previous else fake_incident.LOGS
        if name not in logs:
            raise no_previous_container_error(name)
        return logs[name][-tail_lines:]

    def list_deployments(self, namespace: str) -> list[DeploymentSummary]:
        return [summarize_deployment(d) for d in fake_incident.DEPLOYMENTS if d.namespace == namespace]

    def get_deployment(self, namespace: str, name: str) -> DeploymentDetail:
        for deployment in fake_incident.DEPLOYMENTS:
            if deployment.namespace == namespace and deployment.name == name:
                return deployment
        raise not_found_error(f"get deployment '{name}'", namespace)

    def list_events(self, namespace: str, warnings_only: bool, limit: int) -> list[ClusterEvent]:
        if namespace != fake_incident.NAMESPACE:
            return []
        events = [e for e in fake_incident.EVENTS if not warnings_only or e.type == WARNING_EVENT_TYPE]
        return events[:limit]

    def get_deployment_spec(self, namespace: str, name: str) -> DeploymentSpec:
        deployment = self.get_deployment(namespace, name)
        return DeploymentSpec(
            namespace=namespace, name=name, replicas=deployment.desired_replicas, strategy="RollingUpdate",
            containers=[ContainerSpec(name=name, image=deployment.image, env_names=fake_incident.ENV_NAMES.get(name, []),
                                      env_from=fake_incident.ENV_FROM.get(name, []),
                                      cpu_limit=fake_incident.CPU_LIMIT)],
        )


class FakeClusterWriter:
    """Records the changes it is asked to make instead of making them (tests, `make up`)."""

    def __init__(self):
        self.performed: list[str] = []

    def restart_deployment(self, namespace: str, name: str) -> str:
        return self._record(f"Restarted deployment {name}.")

    def scale_deployment(self, namespace: str, name: str, replicas: int) -> str:
        return self._record(f"Scaled deployment {name} to {replicas} replicas.")

    def rollback_deployment(self, namespace: str, name: str, revision: int) -> str:
        return self._record(f"Rolled back deployment {name} to the pod template of revision {revision}.")

    def _record(self, done: str) -> str:
        self.performed.append(done)
        return done
