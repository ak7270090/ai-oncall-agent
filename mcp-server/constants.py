"""Fixed values of the MCP server. Anything an operator may want to tune per
environment (URLs, timeouts, allowed namespaces, rate windows) lives in
config/settings.py instead. Fake incident data lives in fake/incident_data.py."""

from typing import Literal

# Tool argument contract: defaults and upper bounds published in each tool's JSON Schema.
DEFAULT_LOG_LINES = 50
MAX_LOG_LINES = 500
DEFAULT_EVENT_LIMIT = 20
MAX_EVENT_LIMIT = 100
DEFAULT_HISTORY_MINUTES = 15
MAX_HISTORY_MINUTES = 120

# Kubernetes object/label value syntax; also keeps values safe to embed in PromQL.
NAME_PATTERN = r"^[a-z0-9]([a-z0-9.-]{0,61}[a-z0-9])?$"

# Kubernetes vocabulary.
REVISION_ANNOTATION = "deployment.kubernetes.io/revision"
WARNING_EVENT_TYPE = "Warning"

# Metrics offered by get_metrics, and the unit each is reported in.
Metric = Literal[
    "request_rate", "error_rate", "error_count", "latency_p99_ms", "cpu_cores", "cpu_throttled_ratio", "memory_mb"
]
METRIC_UNITS: dict[str, str] = {
    "request_rate": "req/s",
    "error_rate": "ratio (0-1) of 5xx responses",
    "error_count": "5xx responses in window",
    "latency_p99_ms": "ms",
    "cpu_cores": "cores per pod (avg); compare with the container cpu_limit",
    "cpu_throttled_ratio": "ratio (0-1) of CPU periods throttled at the container limit",
    "memory_mb": "MiB per pod (avg)",
}
SERVICE_OVERVIEW_METRICS: tuple[Metric, ...] = ("request_rate", "error_rate", "latency_p99_ms")
METRIC_VALUE_DECIMALS = 4
BYTES_PER_MIB = 1024 * 1024

HEALTH_STATUS_OK = "ok"
