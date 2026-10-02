"""Pure functions that read evidence and pick out problem signals: which pods are
unhealthy, which services fail or are slow, which deployments are degraded, which
other services error logs blame. No I/O; the collection steps decide what to do
with the answers."""

import re
from typing import Any

from agent.models import Evidence
from constants import (
    FAILED_CALL_LOG_HINTS,
    POD_OBJECT_PREFIX,
    PROBE_FAILURE_EVENT_REASON,
    RUNNING_POD_STATUS,
    McpTool,
)


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
