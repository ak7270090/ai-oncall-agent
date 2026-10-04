"""Fixed values of the Prometheus MCP server."""

from enum import StrEnum
from typing import Literal

# Tool argument contract: default and upper bound of a metric history.
DEFAULT_HISTORY_MINUTES = 15
MAX_HISTORY_MINUTES = 120


class Metric(StrEnum):
    """Metrics offered by get_metrics."""

    REQUEST_RATE = "request_rate"
    ERROR_RATE = "error_rate"
    ERROR_COUNT = "error_count"
    LATENCY_P99_MS = "latency_p99_ms"
    CPU_CORES = "cpu_cores"
    CPU_THROTTLED_RATIO = "cpu_throttled_ratio"
    MEMORY_MB = "memory_mb"


# Type of the get_metrics `metric` argument. A Literal gives the model an inline `enum`
# in the tool's JSON Schema; an Enum type would become a `$ref` instead.
MetricName = Literal[tuple(metric.value for metric in Metric)]

METRIC_UNITS: dict[Metric, str] = {
    Metric.REQUEST_RATE: "req/s",
    Metric.ERROR_RATE: "ratio (0-1) of 5xx responses",
    Metric.ERROR_COUNT: "5xx responses in window",
    Metric.LATENCY_P99_MS: "ms",
    Metric.CPU_CORES: "cores per pod (avg); compare with the container cpu_limit",
    Metric.CPU_THROTTLED_RATIO: "ratio (0-1) of CPU periods throttled at the container limit",
    Metric.MEMORY_MB: "MiB per pod (avg)",
}
SERVICE_OVERVIEW_METRICS: tuple[Metric, ...] = (Metric.REQUEST_RATE, Metric.ERROR_RATE, Metric.LATENCY_P99_MS)
METRIC_VALUE_DECIMALS = 4
BYTES_PER_MIB = 1024 * 1024
