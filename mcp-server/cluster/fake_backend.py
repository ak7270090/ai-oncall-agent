from cluster.backend import ClusterError
from cluster.models import ClusterEvent, DeploymentDetail, DeploymentSummary, PodDetail, summarize_deployment
from data import fake_cluster


class FakeBackend:
    """Serves the canned incident in data/fake_cluster.py; same behavior contract as KubernetesBackend."""

    def list_pods(self, namespace: str, app: str | None) -> list[PodDetail]:
        return [p for p in fake_cluster.PODS if p.namespace == namespace and (app is None or p.app == app)]

    def get_pod(self, namespace: str, name: str) -> PodDetail:
        for pod in fake_cluster.PODS:
            if pod.namespace == namespace and pod.name == name:
                return pod
        raise ClusterError(f"Not found: get pod '{name}' in namespace '{namespace}'")

    def get_pod_logs(self, namespace: str, name: str, tail_lines: int, previous: bool) -> list[str]:
        self.get_pod(namespace, name)
        logs = fake_cluster.PREVIOUS_LOGS if previous else fake_cluster.LOGS
        if name not in logs:
            raise ClusterError(f"No previous terminated container for pod '{name}'")
        return logs[name][-tail_lines:]

    def list_deployments(self, namespace: str) -> list[DeploymentSummary]:
        return [summarize_deployment(d) for d in fake_cluster.DEPLOYMENTS if d.namespace == namespace]

    def get_deployment(self, namespace: str, name: str) -> DeploymentDetail:
        for deployment in fake_cluster.DEPLOYMENTS:
            if deployment.namespace == namespace and deployment.name == name:
                return deployment
        raise ClusterError(f"Not found: get deployment '{name}' in namespace '{namespace}'")

    def list_events(self, namespace: str, warnings_only: bool, limit: int) -> list[ClusterEvent]:
        if namespace != fake_cluster.NAMESPACE:
            return []
        events = [e for e in fake_cluster.EVENTS if not warnings_only or e.type == "Warning"]
        return events[:limit]
