"""Tool and resource results. Deliberately small: only the fields an on-call engineer
needs; never environment variable values, volumes or other parts of a spec that may
hold secrets (env var *names* only)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class Condition(BaseModel):
    type: str
    status: str
    reason: str | None = None
    message: str | None = None


class ContainerStatus(BaseModel):
    name: str
    image: str
    ready: bool
    restart_count: int
    state: Literal["running", "waiting", "terminated", "unknown"]
    reason: str | None = None
    message: str | None = None
    last_termination_reason: str | None = None
    last_exit_code: int | None = None
    cpu_request: str | None = None
    cpu_limit: str | None = None
    memory_request: str | None = None
    memory_limit: str | None = None


class PodDetail(BaseModel):
    name: str
    namespace: str
    app: str | None = None
    version: str | None = None
    phase: str
    node: str | None = None
    created_at: datetime | None = None
    conditions: list[Condition] = []
    containers: list[ContainerStatus] = []


class PodSummary(BaseModel):
    name: str
    app: str | None = None
    version: str | None = None
    phase: str
    status: str
    ready: bool
    restarts: int
    created_at: datetime | None = None


class PodList(BaseModel):
    namespace: str
    pods: list[PodSummary]


class PodLogs(BaseModel):
    namespace: str
    pod: str
    previous: bool
    lines: list[str]
    # Set when summarize=true and the client summarized the logs (MCP sampling): `lines`
    # then holds only the newest few lines.
    summary: str | None = None
    summarized_by: str | None = None
    summarized_lines: int | None = None


class DeploymentSummary(BaseModel):
    name: str
    image: str
    version: str | None = None
    desired_replicas: int
    ready_replicas: int
    updated_replicas: int
    available_replicas: int


class DeploymentList(BaseModel):
    namespace: str
    deployments: list[DeploymentSummary]


class ReplicaSetRevision(BaseModel):
    revision: int
    name: str
    image: str
    version: str | None = None
    desired_replicas: int
    ready_replicas: int
    created_at: datetime | None = None


class DeploymentDetail(DeploymentSummary):
    namespace: str
    conditions: list[Condition] = []
    revisions: list[ReplicaSetRevision] = []


class ContainerSpec(BaseModel):
    name: str
    image: str
    env_names: list[str] = []
    cpu_request: str | None = None
    cpu_limit: str | None = None
    memory_request: str | None = None
    memory_limit: str | None = None
    readiness_probe: str | None = None
    liveness_probe: str | None = None


class DeploymentSpec(BaseModel):
    """What a deployment is configured to run (the desired state), not how it's doing."""

    namespace: str
    name: str
    replicas: int
    strategy: str | None = None
    containers: list[ContainerSpec] = []


class ClusterEvent(BaseModel):
    type: str
    reason: str | None = None
    object: str
    message: str | None = None
    count: int = 1
    last_seen: datetime | None = None


class EventList(BaseModel):
    namespace: str
    events: list[ClusterEvent]


def summarize_pod(pod: PodDetail) -> PodSummary:
    """One status word per pod: the first abnormal container reason, else the phase."""
    abnormal_reasons = [c.reason for c in pod.containers if c.reason and c.state != "running"]
    return PodSummary(
        name=pod.name,
        app=pod.app,
        version=pod.version,
        phase=pod.phase,
        status=abnormal_reasons[0] if abnormal_reasons else pod.phase,
        ready=bool(pod.containers) and all(c.ready for c in pod.containers),
        restarts=sum(c.restart_count for c in pod.containers),
        created_at=pod.created_at,
    )


def summarize_deployment(deployment: DeploymentDetail) -> DeploymentSummary:
    return DeploymentSummary.model_validate(
        deployment.model_dump(include=set(DeploymentSummary.model_fields))
    )
