"""Pure functions that read evidence and pick out problem signals: which pods are
unhealthy, which services fail or are slow, which deployments are degraded, which
other services error logs blame. No I/O; the collection steps decide what to do
with the answers."""

import re
from typing import Any

from investigation.constants import (
    FAILED_CALL_LOG_HINTS,
    POD_OBJECT_PREFIX,
    PROBE_FAILURE_EVENT_REASON,
    RUNNING_POD_STATUS,
)
from investigation.models import Evidence
from mcp_client.constants import McpTool, Metric


def first_result(evidence: list[Evidence], tool: McpTool) -> dict[str, Any]:
    """The result of the first successful call of `tool`, or {} if there is none."""
    for item in evidence:
        if item.source == tool and isinstance(item.result, dict):
            return item.result
    return {}


def is_suspected(name: str, suspected: list[str]) -> bool:
    return any(s and (s in name or name in s) for s in suspected)


def suspected_first(names: list[str], suspected: list[str], limit: int) -> list[str]:
    """Unique names, those the user mentioned first, at most `limit`."""
    unique = list(dict.fromkeys(names))
    return sorted(unique, key=lambda name: not is_suspected(name, suspected))[:limit]


def unhealthy_pods(pods: list[dict]) -> list[dict]:
    return [
        p for p in pods
        if not p.get("ready") or p.get("restarts", 0) > 0 or p.get("status") != RUNNING_POD_STATUS
    ]


def failing_services(services: list[dict], error_rate_threshold: float) -> list[str]:
    return [s["service"] for s in services if (s.get("error_rate") or 0) >= error_rate_threshold]


def slow_services(services: list[dict], latency_threshold_ms: float) -> list[str]:
    return [s["service"] for s in services if (s.get("latency_p99_ms") or 0) >= latency_threshold_ms]


def degraded_deployments(deployments: list[dict]) -> list[str]:
    """Not all replicas ready or updated, or deliberately scaled to zero."""
    return [
        d["name"] for d in deployments
        if d.get("ready_replicas", 0) < d.get("desired_replicas", 0)
        or d.get("updated_replicas", 0) < d.get("desired_replicas", 0)
        or d.get("desired_replicas", 0) == 0
    ]


def without_stale_pod_events(events: list[dict], pods: list[dict]) -> tuple[list[dict], int]:
    """Drop pod events that describe the past, not the present:
    - any event about a pod that no longer exists (replaced or scaled away; current pods,
      deployments and metrics show today's state), and
    - probe failures of pods that are now ready and never restarted (they were booting).
    Both otherwise read as current outages. Returns the kept events and how many were dropped."""
    current = {p["name"] for p in pods}
    settled = {p["name"] for p in pods if p.get("ready") and p.get("restarts", 0) == 0}
    kept = []
    for event in events:
        involved = event.get("object", "")
        pod = involved.removeprefix(POD_OBJECT_PREFIX)
        is_pod_event = involved.startswith(POD_OBJECT_PREFIX)
        booting_probe_failure = event.get("reason") == PROBE_FAILURE_EVENT_REASON and pod in settled
        if is_pod_event and (pod not in current or booting_probe_failure):
            continue
        kept.append(event)
    return kept, len(events) - len(kept)


def _service_names_in(line: str, known_services: set[str]) -> set[str]:
    return {name for name in known_services if re.search(rf"(?<![a-z0-9-]){re.escape(name)}(?![a-z0-9-])", line)}


def services_blamed_in_logs(evidence: list[Evidence], known_services: set[str]) -> set[str]:
    """Other services named in log lines about failed or slow calls, e.g.
    'upstream unavailable: POST http://payment-service/...' or 'database unavailable: payments-db:5432'.
    A pod's own service is never counted as its dependency."""
    found: set[str] = set()
    for item in evidence:
        if item.source != McpTool.GET_POD_LOGS or not isinstance(item.result, dict):
            continue
        pod = str(item.arguments.get("pod", ""))
        own_service = {name for name in known_services if pod.startswith(f"{name}-")}
        for line in item.result.get("lines", []):
            if any(hint in line.lower() for hint in FAILED_CALL_LOG_HINTS):
                found |= _service_names_in(line, known_services) - own_service
    return found


def cpu_quantity_in_cores(quantity: str | None) -> float | None:
    """Kubernetes CPU quantity ("250m", "1", "0.5") in cores; None if missing or unreadable."""
    try:
        return float(quantity[:-1]) / 1000 if quantity and quantity.endswith("m") else float(quantity)
    except (TypeError, ValueError):
        return None


def _cpu_limits_by_service(evidence: list[Evidence]) -> dict[str, str]:
    limits = {}
    for item in evidence:
        result = item.result if isinstance(item.result, dict) else {}
        containers = result.get("containers") or []
        if item.source == McpTool.GET_POD_STATUS and result.get("app") and containers:
            limits[result["app"]] = containers[0].get("cpu_limit")
    return limits


def _latest_metric(evidence: list[Evidence], metric: Metric) -> dict[str, float]:
    latest: dict[str, float] = {}
    for item in evidence:
        result = item.result if isinstance(item.result, dict) else {}
        if (item.source == McpTool.GET_METRICS and item.arguments.get("metric") == metric
                and result.get("latest") is not None):
            service = item.arguments.get("service", "unknown")
            latest[service] = max(result["latest"], latest.get(service, 0.0))
    return latest


def cpu_starved_services(evidence: list[Evidence], throttled_ratio_threshold: float,
                         min_usage_of_limit: float) -> dict[str, float]:
    """Services held at their CPU limit: latest cpu_throttled_ratio at or above the
    threshold AND real CPU use of at least `min_usage_of_limit` of the limit. The ratio
    only counts periods in which the container ran, so a mostly idle container with short
    bursts can look heavily throttled without being CPU-starved."""
    limits = _cpu_limits_by_service(evidence)
    usage = _latest_metric(evidence, Metric.CPU_CORES)
    starved = {}
    for service, ratio in _latest_metric(evidence, Metric.CPU_THROTTLED_RATIO).items():
        limit = cpu_quantity_in_cores(limits.get(service))
        if ratio >= throttled_ratio_threshold and limit and usage.get(service, 0.0) >= min_usage_of_limit * limit:
            starved[service] = ratio
    return starved


def latency_now_and_earlier(evidence: list[Evidence], latency_threshold_ms: float) -> tuple[dict[str, float], dict[str, tuple[float, float]]]:
    """Services slow right now (latest p99 in the service overview) and services that were
    slow earlier in the window but have recovered (history max above, latest below)."""
    slow_now = {s["service"]: s["latency_p99_ms"]
                for s in first_result(evidence, McpTool.GET_SERVICE_OVERVIEW).get("services", [])
                if (s.get("latency_p99_ms") or 0) >= latency_threshold_ms}
    recovered = {}
    for item in evidence:
        result = item.result if isinstance(item.result, dict) else {}
        latest, peak = result.get("latest"), result.get("max")
        service = item.arguments.get("service")
        if (item.source == McpTool.GET_METRICS and item.arguments.get("metric") == Metric.LATENCY_P99_MS
                and service not in slow_now and latest is not None and peak is not None
                and peak >= latency_threshold_ms > latest):
            recovered[service] = (peak, latest)
    return slow_now, recovered


def computed_findings(evidence: list[Evidence], cpu_throttled_ratio_threshold: float,
                      cpu_min_usage_of_limit: float, latency_threshold_ms: float) -> list[str]:
    """Conclusions code can draw from the evidence for certain, stated plainly for the LLM
    so it doesn't have to infer them (it doesn't reliably at moderate signal levels, or when
    an earlier incident is still in the metric history)."""
    limits = _cpu_limits_by_service(evidence)
    findings = [
        f"{service} is held at its CPU limit ({limits.get(service) or 'limit unknown'}): throttled in "
        f"{ratio:.0%} of CPU periods (latest). If {service} is the slow or failing service, the root cause "
        f"is resource_exhaustion in {service}, not slow_dependency."
        for service, ratio in sorted(
            cpu_starved_services(evidence, cpu_throttled_ratio_threshold, cpu_min_usage_of_limit).items())
    ]
    slow_now, recovered = latency_now_and_earlier(evidence, latency_threshold_ms)
    if slow_now:
        findings.append("Slow right now (latest p99): " + ", ".join(
            f"{service} {latency:.0f} ms" for service, latency in sorted(slow_now.items())) + ".")
    findings += [
        f"{service} was slow earlier in the window (p99 up to {peak:.0f} ms) but has recovered (latest "
        f"{latest:.0f} ms): that was an earlier problem, not the cause of the current one."
        for service, (peak, latest) in sorted(recovered.items())
    ]
    return findings
