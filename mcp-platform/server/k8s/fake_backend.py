import fake_incident
from k8s.backend import no_previous_container_error, not_found_error
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


class FakeClusterBackend:
    """Serves the canned incident in fake_incident.py; same behavior contract as KubernetesBackend."""

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
