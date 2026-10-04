"""Fake cluster state for MCP_BACKEND=fake (tests, demos without a cluster).

The incident: payment-service v2.4.0 points at a database host that doesn't exist, so
its pods crash-loop; order-service fails downstream; user-service is healthy.
"""

from datetime import datetime, timezone

from k8s.models import (
    ClusterEvent,
    Condition,
    ContainerStatus,
    DeploymentDetail,
    PodDetail,
    ReplicaSetRevision,
)
from prometheus.constants import Metric

NAMESPACE = "shop"
CPU_LIMIT = "250m"
# Env var names per deployment (values are never exposed).
ENV_NAMES = {"payment-service": ["DB_HOST", "DB_PASSWORD", "FAULT_MODE"]}
ENV_FROM = {"payment-service": ["configMap/payment-service-config", "secret/payment-service-secrets"]}


def _utc_time(hour: int, minute: int, day: int = 27) -> datetime:
    return datetime(2026, 9, day, hour, minute, tzinfo=timezone.utc)


def _make_crashing_container(restarts: int) -> ContainerStatus:
    return ContainerStatus(
        name="payment-service", image="payment-service:v2.4.0", ready=False, restart_count=restarts,
        state="waiting", reason="CrashLoopBackOff", message="back-off 5m0s restarting failed container",
        last_termination_reason="Error", last_exit_code=1,
    )


def _make_healthy_container(service: str, image: str, restarts: int = 0) -> ContainerStatus:
    return ContainerStatus(name=service, image=image, ready=True, restart_count=restarts, state="running")


_NOT_READY = [Condition(type="Ready", status="False", reason="ContainersNotReady")]
_READY = [Condition(type="Ready", status="True")]

PODS: list[PodDetail] = [
    *(
        PodDetail(name=name, namespace=NAMESPACE, app="payment-service", version="v2", phase="Running",
                  created_at=_utc_time(9, 42), conditions=_NOT_READY, containers=[_make_crashing_container(restarts)])
        for name, restarts in (("payment-service-7d9f8c6b5-2xkqp", 14), ("payment-service-7d9f8c6b5-9fzmw", 13))
    ),
    *(
        PodDetail(name=name, namespace=NAMESPACE, app="order-service", version="v1", phase="Running",
                  created_at=_utc_time(14, 5, day=20), conditions=_READY,
                  containers=[_make_healthy_container("order-service", "order-service:v1.8.2")])
        for name in ("order-service-5b7c9d4f8-hl2vn", "order-service-5b7c9d4f8-x8mjc")
    ),
    *(
        PodDetail(name=name, namespace=NAMESPACE, app="user-service", version="v1", phase="Running",
                  created_at=_utc_time(11, 30, day=12), conditions=_READY,
                  containers=[_make_healthy_container("user-service", "user-service:v3.1.0", restarts)])
        for name, restarts in (("user-service-6c4d8f9a7-kp3ws", 0), ("user-service-6c4d8f9a7-r7tbn", 1))
    ),
]

_PAYMENT_CRASH_LOG = [
    "2026-09-27T09:59:48Z INFO  Starting payment-service v2.4.0",
    "2026-09-27T09:59:49Z INFO  Connecting to database payments-db-v2.shop.svc:5432",
    "2026-09-27T09:59:54Z WARN  Database connection attempt 1/3 failed: could not resolve host payments-db-v2.shop.svc",
    "2026-09-27T10:00:04Z WARN  Database connection attempt 3/3 failed: could not resolve host payments-db-v2.shop.svc",
    "2026-09-27T10:00:04Z ERROR Fatal: unable to connect to database after 3 attempts",
    "2026-09-27T10:00:04Z INFO  Shutting down (exit code 1)",
]
_ORDER_LOG = [
    "2026-09-27T09:58:10Z INFO  POST /orders 201 84ms",
    "2026-09-27T09:58:31Z ERROR POST /orders 502 upstream payment-service unavailable (connection refused)",
    "2026-09-27T09:59:40Z WARN  circuit breaker OPEN for payment-service",
    "2026-09-27T10:00:05Z ERROR POST /orders 503 circuit breaker open for payment-service",
]
_USER_LOG = [
    "2026-09-27T09:58:02Z INFO  GET /users/1043 200 9ms",
    "2026-09-27T09:59:55Z INFO  GET /users/881 200 8ms",
]

LOGS: dict[str, list[str]] = {
    pod.name: {"payment-service": _PAYMENT_CRASH_LOG[:2], "order-service": _ORDER_LOG, "user-service": _USER_LOG}[pod.app]
    for pod in PODS
}
PREVIOUS_LOGS: dict[str, list[str]] = {
    pod.name: _PAYMENT_CRASH_LOG for pod in PODS if pod.app == "payment-service"
}

DEPLOYMENTS: list[DeploymentDetail] = [
    DeploymentDetail(
        name="payment-service", namespace=NAMESPACE, image="payment-service:v2.4.0", version="v2",
        desired_replicas=2, ready_replicas=0, updated_replicas=2, available_replicas=0,
        conditions=[
            Condition(type="Available", status="False", reason="MinimumReplicasUnavailable"),
            Condition(type="Progressing", status="False", reason="ProgressDeadlineExceeded"),
        ],
        revisions=[
            ReplicaSetRevision(revision=2, name="payment-service-7d9f8c6b5", image="payment-service:v2.4.0",
                               version="v2", desired_replicas=2, ready_replicas=0, created_at=_utc_time(9, 42)),
            ReplicaSetRevision(revision=1, name="payment-service-54ffb7b494", image="payment-service:v2.3.1",
                               version="v1", desired_replicas=0, ready_replicas=0, created_at=_utc_time(10, 0, day=15)),
        ],
    ),
    DeploymentDetail(
        name="order-service", namespace=NAMESPACE, image="order-service:v1.8.2", version="v1",
        desired_replicas=2, ready_replicas=2, updated_replicas=2, available_replicas=2,
        conditions=[Condition(type="Available", status="True", reason="MinimumReplicasAvailable")],
        revisions=[ReplicaSetRevision(revision=1, name="order-service-5b7c9d4f8", image="order-service:v1.8.2",
                                      version="v1", desired_replicas=2, ready_replicas=2, created_at=_utc_time(14, 5, day=20))],
    ),
    DeploymentDetail(
        name="user-service", namespace=NAMESPACE, image="user-service:v3.1.0", version="v1",
        desired_replicas=2, ready_replicas=2, updated_replicas=2, available_replicas=2,
        conditions=[Condition(type="Available", status="True", reason="MinimumReplicasAvailable")],
        revisions=[ReplicaSetRevision(revision=1, name="user-service-6c4d8f9a7", image="user-service:v3.1.0",
                                      version="v1", desired_replicas=2, ready_replicas=2, created_at=_utc_time(11, 30, day=12))],
    ),
]

EVENTS: list[ClusterEvent] = [
    ClusterEvent(type="Warning", reason="BackOff", object="Pod/payment-service-7d9f8c6b5-2xkqp",
                 message="Back-off restarting failed container payment-service", count=58, last_seen=_utc_time(10, 0)),
    ClusterEvent(type="Warning", reason="BackOff", object="Pod/payment-service-7d9f8c6b5-9fzmw",
                 message="Back-off restarting failed container payment-service", count=55, last_seen=_utc_time(9, 59)),
    ClusterEvent(type="Warning", reason="Unhealthy", object="Pod/payment-service-7d9f8c6b5-2xkqp",
                 message="Readiness probe failed: connection refused", count=12, last_seen=_utc_time(9, 58)),
    ClusterEvent(type="Normal", reason="ScalingReplicaSet", object="Deployment/payment-service",
                 message="Scaled up replica set payment-service-7d9f8c6b5 to 2", count=1, last_seen=_utc_time(9, 42)),
]

# Last 5 one-minute samples (oldest first) per service per metric; see prometheus/queries.py for units.
METRICS_END_TIME = _utc_time(10, 0)
METRICS: dict[str, dict[Metric, list[float]]] = {
    "payment-service": {
        Metric.CPU_THROTTLED_RATIO: [0.0, 0.0, 0.0, 0.0, 0.0],
        Metric.REQUEST_RATE: [42.0, 44.0, 43.0, 41.0, 40.0],
        Metric.ERROR_RATE: [0.002, 0.003, 0.41, 0.97, 1.0],
        Metric.ERROR_COUNT: [0, 0, 25, 58, 60],
        Metric.LATENCY_P99_MS: [120, 118, 2400, 5000, 5000],
        Metric.CPU_CORES: [0.35, 0.33, 0.05, 0.02, 0.02],
        Metric.MEMORY_MB: [310, 305, 90, 88, 85],
    },
    "order-service": {
        Metric.CPU_THROTTLED_RATIO: [0.0, 0.01, 0.02, 0.02, 0.01],
        Metric.REQUEST_RATE: [38.0, 40.0, 39.0, 37.0, 38.0],
        Metric.ERROR_RATE: [0.001, 0.002, 0.18, 0.46, 0.51],
        Metric.ERROR_COUNT: [0, 0, 7, 17, 19],
        Metric.LATENCY_P99_MS: [95, 97, 1800, 3100, 3050],
        Metric.CPU_CORES: [0.22, 0.24, 0.26, 0.25, 0.25],
        Metric.MEMORY_MB: [260, 262, 270, 275, 274],
    },
    "user-service": {
        Metric.CPU_THROTTLED_RATIO: [0.0, 0.0, 0.0, 0.0, 0.0],
        Metric.REQUEST_RATE: [65.0, 66.0, 64.0, 67.0, 65.0],
        Metric.ERROR_RATE: [0.001, 0.0, 0.001, 0.0, 0.001],
        Metric.ERROR_COUNT: [0, 0, 0, 0, 0],
        Metric.LATENCY_P99_MS: [30, 28, 31, 29, 30],
        Metric.CPU_CORES: [0.12, 0.11, 0.13, 0.12, 0.12],
        Metric.MEMORY_MB: [180, 181, 180, 182, 181],
    },
}
