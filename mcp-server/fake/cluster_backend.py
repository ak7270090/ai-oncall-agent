from cluster.backend import ClusterError
from cluster.models import ClusterEvent, DeploymentDetail, DeploymentSummary, PodDetail, summarize_deployment
from fake import incident_data


class FakeClusterBackend:
    """Serves the canned incident in fake/incident_data.py; same behavior contract as KubernetesBackend."""

    def list_pods(self, namespace: str, app: str | None) -> list[PodDetail]:
        return [p for p in incident_data.PODS if p.namespace == namespace and (app is None or p.app == app)]

    def get_pod(self, namespace: str, name: str) -> PodDetail:
        for pod in incident_data.PODS:
            if pod.namespace == namespace and pod.name == name:
                return pod
        raise ClusterError(f"Not found: get pod '{name}' in namespace '{namespace}'")

    def get_pod_logs(self, namespace: str, name: str, tail_lines: int, previous: bool) -> list[str]:
        self.get_pod(namespace, name)
        logs = incident_data.PREVIOUS_LOGS if previous else incident_data.LOGS
        if name not in logs:
            raise ClusterError(
                f"Pod '{name}' has no previous (crashed) container; it has not restarted. "
                "Call get_pod_logs again with previous=false for its current logs."
            )
        return logs[name][-tail_lines:]

    def list_deployments(self, namespace: str) -> list[DeploymentSummary]:
        return [summarize_deployment(d) for d in incident_data.DEPLOYMENTS if d.namespace == namespace]

    def get_deployment(self, namespace: str, name: str) -> DeploymentDetail:
        for deployment in incident_data.DEPLOYMENTS:
            if deployment.namespace == namespace and deployment.name == name:
                return deployment
        raise ClusterError(f"Not found: get deployment '{name}' in namespace '{namespace}'")

    def list_events(self, namespace: str, warnings_only: bool, limit: int) -> list[ClusterEvent]:
        if namespace != incident_data.NAMESPACE:
            return []
        events = [e for e in incident_data.EVENTS if not warnings_only or e.type == "Warning"]
        return events[:limit]
