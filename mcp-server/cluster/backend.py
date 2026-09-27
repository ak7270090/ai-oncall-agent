from typing import Protocol

from mcp.server.mcpserver.exceptions import ToolError

from cluster.models import ClusterEvent, DeploymentDetail, DeploymentSummary, PodDetail


class ClusterError(ToolError):
    """An anticipated cluster failure; its message is shown to the model."""


class ClusterBackend(Protocol):
    def list_pods(self, namespace: str, app: str | None) -> list[PodDetail]: ...

    def get_pod(self, namespace: str, name: str) -> PodDetail: ...

    def get_pod_logs(self, namespace: str, name: str, tail_lines: int, previous: bool) -> list[str]: ...

    def list_deployments(self, namespace: str) -> list[DeploymentSummary]: ...

    def get_deployment(self, namespace: str, name: str) -> DeploymentDetail: ...

    def list_events(self, namespace: str, warnings_only: bool, limit: int) -> list[ClusterEvent]: ...
