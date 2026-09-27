"""Fake cluster state, shaped like the real Kubernetes/Prometheus data of Phases 6-7.

Scenario: payment-service v2.4.0 points at a database host that doesn't exist, so
its pods crash-loop; order-service fails downstream; user-service is healthy.
"""

from typing import Literal

Service = Literal["payment-service", "order-service", "user-service"]
Metric = Literal["error_rate", "latency_p99_ms", "cpu_cores", "memory_mb", "request_rate"]

DEPLOYMENTS: list[dict] = [
    {
        "name": "payment-service",
        "namespace": "default",
        "image": "registry.local/payment-service:v2.4.0",
        "replicas_desired": 3,
        "replicas_ready": 0,
        "last_rollout": "2026-09-27T09:42:00Z",
        "previous_image": "registry.local/payment-service:v2.3.1",
    },
    {
        "name": "order-service",
        "namespace": "default",
        "image": "registry.local/order-service:v1.8.2",
        "replicas_desired": 2,
        "replicas_ready": 2,
        "last_rollout": "2026-09-20T14:05:00Z",
        "previous_image": "registry.local/order-service:v1.8.1",
    },
    {
        "name": "user-service",
        "namespace": "default",
        "image": "registry.local/user-service:v3.1.0",
        "replicas_desired": 2,
        "replicas_ready": 2,
        "last_rollout": "2026-09-12T11:30:00Z",
        "previous_image": "registry.local/user-service:v3.0.4",
    },
]

PODS: dict[str, list[dict]] = {
    "payment-service": [
        {"name": "payment-service-7d9f8c6b5-2xkqp", "phase": "Running", "ready": False,
         "status": "CrashLoopBackOff", "restarts": 14, "age": "18m"},
        {"name": "payment-service-7d9f8c6b5-9fzmw", "phase": "Running", "ready": False,
         "status": "CrashLoopBackOff", "restarts": 13, "age": "18m"},
        {"name": "payment-service-7d9f8c6b5-tq4rd", "phase": "Running", "ready": False,
         "status": "CrashLoopBackOff", "restarts": 13, "age": "18m"},
    ],
    "order-service": [
        {"name": "order-service-5b7c9d4f8-hl2vn", "phase": "Running", "ready": True,
         "status": "Running", "restarts": 0, "age": "7d"},
        {"name": "order-service-5b7c9d4f8-x8mjc", "phase": "Running", "ready": True,
         "status": "Running", "restarts": 0, "age": "7d"},
    ],
    "user-service": [
        {"name": "user-service-6c4d8f9a7-kp3ws", "phase": "Running", "ready": True,
         "status": "Running", "restarts": 0, "age": "15d"},
        {"name": "user-service-6c4d8f9a7-r7tbn", "phase": "Running", "ready": True,
         "status": "Running", "restarts": 1, "age": "15d"},
    ],
}

LOGS: dict[str, list[str]] = {
    "payment-service": [
        "2026-09-27T09:59:48Z INFO  Starting payment-service v2.4.0",
        "2026-09-27T09:59:48Z INFO  Loading config from env",
        "2026-09-27T09:59:49Z INFO  Connecting to database payments-db-v2.default.svc:5432",
        "2026-09-27T09:59:54Z WARN  Database connection attempt 1/3 failed: could not resolve host payments-db-v2.default.svc",
        "2026-09-27T09:59:59Z WARN  Database connection attempt 2/3 failed: could not resolve host payments-db-v2.default.svc",
        "2026-09-27T10:00:04Z WARN  Database connection attempt 3/3 failed: could not resolve host payments-db-v2.default.svc",
        "2026-09-27T10:00:04Z ERROR Fatal: unable to connect to database after 3 attempts",
        "2026-09-27T10:00:04Z ERROR Traceback (most recent call last): ... sqlalchemy.exc.OperationalError: could not translate host name \"payments-db-v2.default.svc\"",
        "2026-09-27T10:00:04Z INFO  Shutting down (exit code 1)",
    ],
    "order-service": [
        "2026-09-27T09:58:10Z INFO  POST /orders 201 84ms",
        "2026-09-27T09:58:31Z ERROR POST /orders 502 upstream payment-service unavailable (connection refused)",
        "2026-09-27T09:58:47Z ERROR POST /orders 502 upstream payment-service unavailable (connection refused)",
        "2026-09-27T09:59:02Z INFO  GET /orders/8812 200 12ms",
        "2026-09-27T09:59:15Z ERROR POST /orders 502 upstream payment-service unavailable (connection refused)",
        "2026-09-27T09:59:40Z WARN  circuit breaker OPEN for payment-service",
        "2026-09-27T10:00:05Z ERROR POST /orders 503 circuit breaker open for payment-service",
    ],
    "user-service": [
        "2026-09-27T09:58:02Z INFO  GET /users/1043 200 9ms",
        "2026-09-27T09:58:40Z INFO  GET /users/2210 200 11ms",
        "2026-09-27T09:59:12Z INFO  PATCH /users/1043 200 23ms",
        "2026-09-27T09:59:55Z INFO  GET /users/881 200 8ms",
    ],
}

# Last 5 samples (1-minute resolution, oldest first) per service per metric.
METRICS: dict[str, dict[str, dict]] = {
    "payment-service": {
        "error_rate": {"unit": "ratio", "samples": [0.002, 0.003, 0.41, 0.97, 1.0]},
        "latency_p99_ms": {"unit": "ms", "samples": [120, 118, 2400, 5000, 5000]},
        "cpu_cores": {"unit": "cores", "samples": [0.35, 0.33, 0.05, 0.02, 0.02]},
        "memory_mb": {"unit": "MiB", "samples": [310, 305, 90, 88, 85]},
        "request_rate": {"unit": "req/s", "samples": [42.0, 44.0, 43.0, 41.0, 40.0]},
    },
    "order-service": {
        "error_rate": {"unit": "ratio", "samples": [0.001, 0.002, 0.18, 0.46, 0.51]},
        "latency_p99_ms": {"unit": "ms", "samples": [95, 97, 1800, 3100, 3050]},
        "cpu_cores": {"unit": "cores", "samples": [0.22, 0.24, 0.26, 0.25, 0.25]},
        "memory_mb": {"unit": "MiB", "samples": [260, 262, 270, 275, 274]},
        "request_rate": {"unit": "req/s", "samples": [38.0, 40.0, 39.0, 37.0, 38.0]},
    },
    "user-service": {
        "error_rate": {"unit": "ratio", "samples": [0.001, 0.0, 0.001, 0.0, 0.001]},
        "latency_p99_ms": {"unit": "ms", "samples": [30, 28, 31, 29, 30]},
        "cpu_cores": {"unit": "cores", "samples": [0.12, 0.11, 0.13, 0.12, 0.12]},
        "memory_mb": {"unit": "MiB", "samples": [180, 181, 180, 182, 181]},
        "request_rate": {"unit": "req/s", "samples": [65.0, 66.0, 64.0, 67.0, 65.0]},
    },
}
