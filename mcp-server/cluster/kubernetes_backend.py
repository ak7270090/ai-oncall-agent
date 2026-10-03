from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from functools import cached_property
from pathlib import Path

from kubernetes import client, config
from kubernetes.client.rest import ApiException
from kubernetes.config.config_exception import ConfigException
from urllib3.exceptions import HTTPError as TransportError

from cluster.backend import ClusterError, no_previous_container_error, not_found_error
from cluster.models import (
    ClusterEvent,
    Condition,
    ContainerSpec,
    ContainerStatus,
    DeploymentDetail,
    DeploymentSpec,
    DeploymentSummary,
    PodDetail,
    ReplicaSetRevision,
)
from constants import REVISION_ANNOTATION, WARNING_EVENT_TYPE


def load_api_client(kubeconfig_path: str) -> client.ApiClient:
    if not Path(kubeconfig_path).is_file():
        raise ClusterError(f"No kubeconfig at '{kubeconfig_path}'. Run `make mcp-kubeconfig`.")
    configuration = client.Configuration()
    try:
        config.load_kube_config(config_file=kubeconfig_path, client_configuration=configuration)
    except ConfigException as error:
        raise ClusterError(f"Invalid kubeconfig '{kubeconfig_path}': {error}") from error
    return client.ApiClient(configuration)


@contextmanager
def translate_errors(action: str, namespace: str) -> Iterator[None]:
    try:
        yield
    except ApiException as error:
        if error.status == 404:
            raise not_found_error(action, namespace) from error
        if error.status == 403:
            raise ClusterError(f"Forbidden by RBAC: the MCP server may not {action} in '{namespace}'") from error
        raise ClusterError(f"Kubernetes API error {error.status} ({error.reason}) during {action}: {error.body}") from error
    except TransportError as error:
        raise ClusterError("Kubernetes API unreachable. Is the cluster running?") from error


def _to_condition(raw) -> Condition:
    return Condition(type=raw.type, status=raw.status, reason=raw.reason, message=raw.message)


def _to_resource_fields(container) -> dict[str, str | None]:
    resources = container.resources if container else None
    requests = (resources.requests if resources else None) or {}
    limits = (resources.limits if resources else None) or {}
    return {
        "cpu_request": requests.get("cpu"), "cpu_limit": limits.get("cpu"),
        "memory_request": requests.get("memory"), "memory_limit": limits.get("memory"),
    }


def _to_container_status(raw, spec) -> ContainerStatus:
    state, reason, message = "unknown", None, None
    if raw.state and raw.state.running:
        state = "running"
    elif raw.state and raw.state.waiting:
        state, reason, message = "waiting", raw.state.waiting.reason, raw.state.waiting.message
    elif raw.state and raw.state.terminated:
        state, reason, message = "terminated", raw.state.terminated.reason, raw.state.terminated.message
    last = raw.last_state.terminated if raw.last_state else None
    return ContainerStatus(
        name=raw.name,
        image=spec.image if spec else "",
        ready=bool(raw.ready),
        restart_count=raw.restart_count or 0,
        state=state,
        reason=reason,
        message=message,
        last_termination_reason=last.reason if last else None,
        last_exit_code=last.exit_code if last else None,
        **_to_resource_fields(spec),
    )


def _to_pod_detail(raw) -> PodDetail:
    labels = raw.metadata.labels or {}
    specs = {c.name: c for c in raw.spec.containers}
    return PodDetail(
        name=raw.metadata.name,
        namespace=raw.metadata.namespace,
        app=labels.get("app"),
        version=labels.get("version"),
        phase=raw.status.phase or "Unknown",
        node=raw.spec.node_name,
        created_at=raw.metadata.creation_timestamp,
        conditions=[_to_condition(c) for c in raw.status.conditions or []],
        containers=[_to_container_status(c, specs.get(c.name)) for c in raw.status.container_statuses or []],
    )


def _to_deployment_summary(raw) -> DeploymentSummary:
    template = raw.spec.template
    return DeploymentSummary(
        name=raw.metadata.name,
        image=template.spec.containers[0].image,
        version=(template.metadata.labels or {}).get("version"),
        desired_replicas=raw.spec.replicas or 0,
        ready_replicas=raw.status.ready_replicas or 0,
        updated_replicas=raw.status.updated_replicas or 0,
        available_replicas=raw.status.available_replicas or 0,
    )


def _to_replica_set_revision(raw) -> ReplicaSetRevision:
    annotations = raw.metadata.annotations or {}
    template = raw.spec.template
    return ReplicaSetRevision(
        revision=int(annotations.get(REVISION_ANNOTATION, 0)),
        name=raw.metadata.name,
        image=template.spec.containers[0].image,
        version=(template.metadata.labels or {}).get("version"),
        desired_replicas=raw.spec.replicas or 0,
        ready_replicas=raw.status.ready_replicas or 0,
        created_at=raw.metadata.creation_timestamp,
    )


def _to_cluster_event(raw) -> ClusterEvent:
    involved = raw.involved_object
    return ClusterEvent(
        type=raw.type or "Normal",
        reason=raw.reason,
        object=f"{involved.kind}/{involved.name}",
        message=raw.message,
        count=raw.count or 1,
        last_seen=raw.last_timestamp or raw.event_time or raw.metadata.creation_timestamp,
    )


def _describe_probe(probe) -> str | None:
    if probe is None:
        return None
    if probe.http_get:
        target = f"http GET {probe.http_get.path}:{probe.http_get.port}"
    elif probe.tcp_socket:
        target = f"tcp :{probe.tcp_socket.port}"
    elif getattr(probe, "_exec", None):  # the client names the `exec` field `_exec`
        target = "exec " + " ".join(probe._exec.command or [])
    else:
        target = "probe"
    return f"{target} every {probe.period_seconds or 10}s, fails after {probe.failure_threshold or 3}"


def _describe_env_source(source) -> str:
    if source.config_map_ref:
        return f"configMap/{source.config_map_ref.name}"
    if source.secret_ref:
        return f"secret/{source.secret_ref.name}"
    return "unknown"


def _to_container_spec(container) -> ContainerSpec:
    return ContainerSpec(
        name=container.name,
        image=container.image,
        env_names=sorted({env.name for env in container.env or []}),
        env_from=[_describe_env_source(source) for source in container.env_from or []],
        **_to_resource_fields(container),
        readiness_probe=_describe_probe(container.readiness_probe),
        liveness_probe=_describe_probe(container.liveness_probe),
    )


def _newest_first_sort_key(value: datetime | None) -> float:
    return -value.timestamp() if value else 0.0


class KubernetesBackend:
    """Read-only access to the Kubernetes API with the credentials in `kubeconfig_path`."""

    def __init__(self, kubeconfig_path: str, request_timeout_seconds: float):
        self._kubeconfig_path = kubeconfig_path
        self._timeout = request_timeout_seconds

    @cached_property
    def _api_client(self) -> client.ApiClient:
        return load_api_client(self._kubeconfig_path)

    @cached_property
    def _core(self) -> client.CoreV1Api:
        return client.CoreV1Api(self._api_client)

    @cached_property
    def _apps(self) -> client.AppsV1Api:
        return client.AppsV1Api(self._api_client)

    def list_pods(self, namespace: str, app: str | None) -> list[PodDetail]:
        selector = f"app={app}" if app else None
        with translate_errors("list pods", namespace):
            pods = self._core.list_namespaced_pod(namespace, label_selector=selector, _request_timeout=self._timeout)
        return [_to_pod_detail(p) for p in pods.items]

    def get_pod(self, namespace: str, name: str) -> PodDetail:
        with translate_errors(f"get pod '{name}'", namespace):
            return _to_pod_detail(self._core.read_namespaced_pod(name, namespace, _request_timeout=self._timeout))

    def get_pod_logs(self, namespace: str, name: str, tail_lines: int, previous: bool) -> list[str]:
        try:
            with translate_errors(f"read logs of pod '{name}'", namespace):
                # Raw response: the client's own decoding can hand back a bytes repr as one line.
                response = self._core.read_namespaced_pod_log(
                    name, namespace, tail_lines=tail_lines, previous=previous, timestamps=True,
                    _preload_content=False, _request_timeout=self._timeout,
                )
                text = response.data.decode("utf-8", errors="replace")
        except ClusterError as error:
            if previous and isinstance(error.__cause__, ApiException) and error.__cause__.status == 400:
                raise no_previous_container_error(name) from error
            raise
        return text.splitlines()

    def list_deployments(self, namespace: str) -> list[DeploymentSummary]:
        with translate_errors("list deployments", namespace):
            deployments = self._apps.list_namespaced_deployment(namespace, _request_timeout=self._timeout)
        return [_to_deployment_summary(d) for d in deployments.items]

    def get_deployment(self, namespace: str, name: str) -> DeploymentDetail:
        with translate_errors(f"get deployment '{name}'", namespace):
            raw = self._apps.read_namespaced_deployment(name, namespace, _request_timeout=self._timeout)
            selector = ",".join(f"{k}={v}" for k, v in (raw.spec.selector.match_labels or {}).items())
            replica_sets = self._apps.list_namespaced_replica_set(
                namespace, label_selector=selector, _request_timeout=self._timeout
            )
        owned = [
            rs for rs in replica_sets.items
            if any(owner.uid == raw.metadata.uid for owner in rs.metadata.owner_references or [])
        ]
        return DeploymentDetail(
            **_to_deployment_summary(raw).model_dump(),
            namespace=namespace,
            conditions=[_to_condition(c) for c in raw.status.conditions or []],
            revisions=sorted((_to_replica_set_revision(rs) for rs in owned), key=lambda r: r.revision, reverse=True),
        )

    def list_events(self, namespace: str, warnings_only: bool, limit: int) -> list[ClusterEvent]:
        selector = f"type={WARNING_EVENT_TYPE}" if warnings_only else None
        with translate_errors("list events", namespace):
            events = self._core.list_namespaced_event(namespace, field_selector=selector, _request_timeout=self._timeout)
        return sorted((_to_cluster_event(e) for e in events.items), key=lambda e: _newest_first_sort_key(e.last_seen))[:limit]

    def get_deployment_spec(self, namespace: str, name: str) -> DeploymentSpec:
        with translate_errors(f"get deployment '{name}'", namespace):
            raw = self._apps.read_namespaced_deployment(name, namespace, _request_timeout=self._timeout)
        return DeploymentSpec(
            namespace=namespace,
            name=raw.metadata.name,
            replicas=raw.spec.replicas or 0,
            strategy=raw.spec.strategy.type if raw.spec.strategy else None,
            containers=[_to_container_spec(c) for c in raw.spec.template.spec.containers],
        )
