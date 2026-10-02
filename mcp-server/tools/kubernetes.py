from collections.abc import Callable
from typing import Annotated

from pydantic import Field

from cluster import ClusterBackend
from cluster.models import (
    DeploymentDetail,
    DeploymentList,
    EventList,
    PodDetail,
    PodList,
    PodLogs,
    summarize_pod,
)
from config import Settings
from constants import (
    DEFAULT_EVENT_LIMIT,
    DEFAULT_LOG_LINES,
    MAX_EVENT_LIMIT,
    MAX_LOG_LINES,
)
from tools.helpers import namespace_guard


def build_kubernetes_tools(backend: ClusterBackend, settings: Settings) -> list[Callable]:
    Namespace, require_allowed = namespace_guard(settings)

    def list_pods(
        namespace: Namespace = settings.default_namespace,
        app: Annotated[str | None, Field(description="Only pods with this `app` label, e.g. payment-service")] = None,
    ) -> PodList:
        """List pods with phase, readiness, restart count and a one-word status
        (e.g. CrashLoopBackOff, ImagePullBackOff, Running). Start here to find unhealthy pods."""
        require_allowed(namespace)
        return PodList(namespace=namespace, pods=[summarize_pod(p) for p in backend.list_pods(namespace, app)])

    def get_pod_status(pod: str, namespace: Namespace = settings.default_namespace) -> PodDetail:
        """Detailed status of one pod: conditions and, per container, state, reason,
        restart count and the last termination reason / exit code (why it last crashed)."""
        require_allowed(namespace)
        return backend.get_pod(namespace, pod)

    def get_pod_logs(
        pod: str,
        namespace: Namespace = settings.default_namespace,
        lines: Annotated[int, Field(ge=1, le=MAX_LOG_LINES, description="Recent lines to return")] = DEFAULT_LOG_LINES,
        previous: Annotated[bool, Field(description="Logs of the previous (crashed) container instead of the current one")] = False,
    ) -> PodLogs:
        """Recent log lines of a pod (newest last), each starting with its timestamp. For a
        crash-looping pod set previous=true: the current container has usually only just
        started. Compare timestamps with now: old errors may belong to an earlier problem."""
        require_allowed(namespace)
        return PodLogs(
            namespace=namespace, pod=pod, previous=previous,
            lines=backend.get_pod_logs(namespace, pod, lines, previous),
        )

    def list_deployments(namespace: Namespace = settings.default_namespace) -> DeploymentList:
        """List deployments with image, version label and desired/ready/updated/available replicas."""
        require_allowed(namespace)
        return DeploymentList(namespace=namespace, deployments=backend.list_deployments(namespace))

    def get_deployment(name: str, namespace: Namespace = settings.default_namespace) -> DeploymentDetail:
        """One deployment with its conditions and rollout history (ReplicaSet revisions,
        newest first, each with image and ready replicas). Use it to spot a bad rollout:
        the newest revision failing while an older one worked."""
        require_allowed(namespace)
        return backend.get_deployment(namespace, name)

    def list_events(
        namespace: Namespace = settings.default_namespace,
        warnings_only: bool = True,
        limit: Annotated[int, Field(ge=1, le=MAX_EVENT_LIMIT)] = DEFAULT_EVENT_LIMIT,
    ) -> EventList:
        """Recent Kubernetes events, newest first (BackOff, Unhealthy probes, FailedScheduling,
        OOMKilling, image pull errors...). Often the fastest way to see why something fails."""
        require_allowed(namespace)
        return EventList(namespace=namespace, events=backend.list_events(namespace, warnings_only, limit))

    return [list_pods, get_pod_status, get_pod_logs, list_deployments, get_deployment, list_events]
