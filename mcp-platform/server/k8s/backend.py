from typing import Protocol

from mcp.server.mcpserver.exceptions import ToolError

from k8s.models import (
    ClusterEvent,
    DeploymentDetail,
    DeploymentSpec,
    DeploymentSummary,
    PodDetail,
)


class ClusterError(ToolError):
    """An anticipated cluster failure; its message is shown to the model."""


# Shared by every backend so the model sees the same message whichever one runs.
def not_found_error(action: str, namespace: str) -> ClusterError:
    return ClusterError(f"Not found: {action} in namespace '{namespace}'")


def no_previous_container_error(pod: str) -> ClusterError:
    return ClusterError(
        f"Pod '{pod}' has no previous (crashed) container; it has not restarted. "
        "Call get_pod_logs again with previous=false for its current logs."
    )


class ClusterBackend(Protocol):
    def list_pods(self, namespace: str, app: str | None) -> list[PodDetail]: ...

    def get_pod(self, namespace: str, name: str) -> PodDetail: ...

    def get_pod_logs(self, namespace: str, name: str, tail_lines: int, previous: bool) -> list[str]: ...

    def list_deployments(self, namespace: str) -> list[DeploymentSummary]: ...

    def get_deployment(self, namespace: str, name: str) -> DeploymentDetail: ...

    def list_events(self, namespace: str, warnings_only: bool, limit: int) -> list[ClusterEvent]: ...

    def get_deployment_spec(self, namespace: str, name: str) -> DeploymentSpec: ...
