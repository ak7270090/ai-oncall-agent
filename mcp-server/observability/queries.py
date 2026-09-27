"""PromQL for every metric the tools expose. Series come from the sample services'
/metrics (prometheus-fastapi-instrumentator + prometheus_client process collector),
labelled by Prometheus with `namespace`, `service` (pod label app), `version`, `pod`.

    rate(counter[w])          per-second increase of a counter, averaged over window w
    increase(counter[w])      total increase over w (≈ rate × seconds in w)
    sum(...) / sum by (x)     add series together, optionally keeping label x
    avg(...)                  average across series (here: across pods)
    histogram_quantile(q, …)  estimate a percentile from histogram buckets (needs `le`)
"""

from typing import Literal

Metric = Literal["request_rate", "error_rate", "error_count", "latency_p99_ms", "cpu_cores", "memory_mb"]

UNITS: dict[str, str] = {
    "request_rate": "req/s",
    "error_rate": "ratio (0-1) of 5xx responses",
    "error_count": "5xx responses in window",
    "latency_p99_ms": "ms",
    "cpu_cores": "cores",
    "memory_mb": "MiB per pod (avg)",
}

BYTES_PER_MIB = 1024 * 1024


def label_selector(namespace: str, service: str | None = None) -> str:
    labels = f'namespace="{namespace}"'
    return f'{labels},service="{service}"' if service else labels


def _by(*labels: str) -> str:
    return f" by ({', '.join(labels)})" if labels else ""


def build_query(metric: Metric, selector: str, window: str, group_by: tuple[str, ...] = ()) -> str:
    by = _by(*group_by)
    requests = f"http_requests_total{{{selector}}}"
    server_errors = f'http_requests_total{{{selector},status="5xx"}}'
    match metric:
        case "request_rate":
            return f"sum{by}(rate({requests}[{window}]))"
        case "error_rate":
            numerator = f"sum{by}(rate({server_errors}[{window}]))"
            if not group_by:
                # No 5xx series at all means zero errors, not "no data".
                numerator = f"({numerator} or vector(0))"
            return f"{numerator} / sum{by}(rate({requests}[{window}]))"
        case "error_count":
            return f"sum{by}(increase({server_errors}[{window}])) or vector(0)"
        case "latency_p99_ms":
            buckets = f"http_request_duration_seconds_bucket{{{selector}}}"
            return f"1000 * histogram_quantile(0.99, sum{_by(*group_by, 'le')}(rate({buckets}[{window}])))"
        case "cpu_cores":
            return f"sum{by}(rate(process_cpu_seconds_total{{{selector}}}[{window}]))"
        case "memory_mb":
            return f"avg{by}(process_resident_memory_bytes{{{selector}}}) / {BYTES_PER_MIB}"
    raise ValueError(f"unknown metric {metric}")
