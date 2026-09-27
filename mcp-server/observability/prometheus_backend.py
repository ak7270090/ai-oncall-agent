import math
from datetime import datetime, timedelta, timezone

import httpx2

from observability.backend import MetricsError
from observability.models import MetricSample, ServiceHealth
from observability.queries import Metric, build_query, label_selector

VALUE_DECIMALS = 4
OVERVIEW_METRICS: tuple[Metric, ...] = ("request_rate", "error_rate", "latency_p99_ms")


def _parse_value(raw: str) -> float | None:
    value = float(raw)
    return None if math.isnan(value) or math.isinf(value) else round(value, VALUE_DECIMALS)


class PrometheusBackend:
    """Metrics from the Prometheus HTTP API (/api/v1/query and /api/v1/query_range)."""

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
        rate_window: str,
        step_seconds: int,
        http_client: httpx2.Client | None = None,
    ):
        self._base_url = base_url
        self._http = http_client or httpx2.Client(base_url=base_url, timeout=timeout_seconds)
        self._window = rate_window
        self._step_seconds = step_seconds

    def _get(self, path: str, params: dict) -> list[dict]:
        try:
            response = self._http.get(path, params=params)
        except httpx2.HTTPError as error:
            raise MetricsError(f"Prometheus unreachable at {self._base_url}. Is the cluster running?") from error
        body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        if response.is_error or body.get("status") != "success":
            detail = body.get("error") or response.text[:200]
            raise MetricsError(f"Prometheus query failed ({response.status_code}): {detail}")
        return body["data"]["result"]

    def metric_history(self, namespace: str, service: str, metric: Metric, minutes: int) -> list[MetricSample]:
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=minutes)
        query = build_query(metric, label_selector(namespace, service), self._window)
        series = self._get("/api/v1/query_range", {
            "query": query, "start": start.timestamp(), "end": end.timestamp(), "step": self._step_seconds,
        })
        if not series:
            return []
        return [
            MetricSample(time=datetime.fromtimestamp(float(timestamp), timezone.utc), value=_parse_value(value))
            for timestamp, value in series[0]["values"]
        ]

    def service_overview(self, namespace: str) -> list[ServiceHealth]:
        values: dict[str, dict[str, float | None]] = {}
        for metric in OVERVIEW_METRICS:
            query = build_query(metric, label_selector(namespace), self._window, group_by=("service",))
            for series in self._get("/api/v1/query", {"query": query}):
                service = series["metric"].get("service", "unknown")
                values.setdefault(service, {})[metric] = _parse_value(series["value"][1])
        return [
            ServiceHealth(
                service=service,
                request_rate_per_second=metrics.get("request_rate"),
                # Requests but no 5xx series means no errors.
                error_rate=metrics.get("error_rate", 0.0 if metrics.get("request_rate") else None),
                latency_p99_ms=metrics.get("latency_p99_ms"),
            )
            for service, metrics in sorted(values.items())
        ]
