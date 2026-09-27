"""Deterministic evidence gathering: which MCP tools to call, decided by code from
what earlier calls returned. The LLM only reasons over the result."""

import asyncio
import re
from dataclasses import dataclass
from typing import Any

from agent.models import Evidence, IncidentScope
from agent.toolbox import MCPToolbox

FAILED_CALL_HINTS = ("upstream", "unavailable", "connection refused", "connecterror", "timed out", "timeout",
                     "could not connect")


@dataclass(frozen=True)
class GatheringLimits:
    error_rate_threshold: float
    latency_threshold_ms: float
    max_pods: int
    max_services: int
    log_lines: int


def first_result(evidence: list[Evidence], source: str) -> dict[str, Any]:
    for item in evidence:
        if item.source == source and isinstance(item.result, dict):
            return item.result
    return {}


def _matches(name: str, suspected: list[str]) -> bool:
    return any(s and (s in name or name in s) for s in suspected)


def _prioritized(names: list[str], suspected: list[str], limit: int) -> list[str]:
    unique = list(dict.fromkeys(names))
    return sorted(unique, key=lambda n: not _matches(n, suspected))[:limit]


async def _call_all(toolbox: MCPToolbox, calls: list[tuple[str, dict]], step: str, notes: list[str]) -> list[Evidence]:
    available = []
    for name, arguments in calls:
        if toolbox.has(name):
            available.append((name, arguments))
        else:
            notes.append(f"{step}: skipped {name} (tool not offered by the MCP server)")
    return list(await asyncio.gather(*(toolbox.call(n, a, step) for n, a in available)))


PROBE_FAILURE_REASON = "Unhealthy"


def without_routine_startup_events(events: list[dict], pods: list[dict]) -> tuple[list[dict], int]:
    """Drop probe failures that are just pods booting: the pod is now ready and never
    restarted, or it no longer exists (replaced by a rollout). They otherwise read as
    'connection refused' outages."""
    settled = {p["name"] for p in pods if p.get("ready") and p.get("restarts", 0) == 0}
    current = {p["name"] for p in pods}
    kept = []
    for event in events:
        pod = event.get("object", "").removeprefix("Pod/")
        if event.get("reason") == PROBE_FAILURE_REASON and (pod in settled or pod not in current):
            continue
        kept.append(event)
    return kept, len(events) - len(kept)


async def sweep(toolbox: MCPToolbox, namespace: str, notes: list[str]) -> list[Evidence]:
    """Broad, cheap overview of the namespace."""
    evidence = await _call_all(toolbox, [
        ("get_service_overview", {"namespace": namespace}),
        ("list_pods", {"namespace": namespace}),
        ("list_events", {"namespace": namespace, "warnings_only": True}),
        ("list_deployments", {"namespace": namespace}),
    ], "sweep", notes)
    pods = first_result(evidence, "list_pods").get("pods", [])
    for item in evidence:
        if item.source == "list_events" and isinstance(item.result, dict):
            kept, dropped = without_routine_startup_events(item.result.get("events", []), pods)
            if dropped:
                item.result = {**item.result, "events": kept, "routine_startup_probe_failures_hidden": dropped}
                notes.append(f"sweep: hid {dropped} probe-failure events from pods that were only starting up")
    return evidence


def unhealthy_pods(pods: list[dict]) -> list[dict]:
    return [p for p in pods if not p.get("ready") or p.get("restarts", 0) > 0 or p.get("status") != "Running"]


def failing_services(services: list[dict], threshold: float) -> list[str]:
    return [s["service"] for s in services if (s.get("error_rate") or 0) >= threshold]


def slow_services(services: list[dict], threshold_ms: float) -> list[str]:
    return [s["service"] for s in services if (s.get("latency_p99_ms") or 0) >= threshold_ms]


def troubled_deployments(deployments: list[dict]) -> list[str]:
    return [
        d["name"] for d in deployments
        if d.get("ready_replicas", 0) < d.get("desired_replicas", 0)
        or d.get("updated_replicas", 0) < d.get("desired_replicas", 0)
        or d.get("desired_replicas", 0) == 0
    ]


async def focus(
    toolbox: MCPToolbox, namespace: str, scope: IncidentScope, sweep_evidence: list[Evidence],
    limits: GatheringLimits, notes: list[str],
) -> list[Evidence]:
    """Targeted checks on whatever the sweep (or the question) flagged."""
    pods = first_result(sweep_evidence, "list_pods").get("pods", [])
    services = first_result(sweep_evidence, "get_service_overview").get("services", [])
    deployments = first_result(sweep_evidence, "list_deployments").get("deployments", [])
    suspected = scope.suspected_services

    calls: list[tuple[str, dict]] = []
    for pod in sorted(unhealthy_pods(pods), key=lambda p: not _matches(p.get("app") or "", suspected))[:limits.max_pods]:
        crashed_before = pod.get("restarts", 0) > 0
        calls.append(("get_pod_status", {"namespace": namespace, "pod": pod["name"]}))
        calls.append(("get_pod_logs", {"namespace": namespace, "pod": pod["name"],
                                       "lines": limits.log_lines, "previous": crashed_before}))

    failing = failing_services(services, limits.error_rate_threshold)
    slow = slow_services(services, limits.latency_threshold_ms)
    suspected_deployed = [s for s in suspected if any(s == d["name"] for d in deployments)]
    degraded = _prioritized(failing + slow + suspected_deployed, suspected, limits.max_services)
    inspected_apps = {p.get("app") for p in unhealthy_pods(pods)}
    for service in degraded:
        metrics = ["error_rate"] if service in failing or service not in slow else []
        if service in slow:
            metrics += ["latency_p99_ms", "cpu_cores", "cpu_throttled_ratio"]
        for metric in metrics:
            calls.append(("get_metrics", {"namespace": namespace, "service": service,
                                          "metric": metric, "minutes": scope.window_minutes}))
        running_pod = next((p for p in pods if p.get("app") == service), None)
        if running_pod and service not in inspected_apps:
            # Pods can be Running yet fail or crawl; logs name the failing dependency and
            # status shows the resource limits to compare CPU/memory against.
            calls.append(("get_pod_logs", {"namespace": namespace, "pod": running_pod["name"],
                                           "lines": limits.log_lines, "previous": False}))
            if service in slow:
                calls.append(("get_pod_status", {"namespace": namespace, "pod": running_pod["name"]}))

    for name in _prioritized(troubled_deployments(deployments), suspected, limits.max_services):
        calls.append(("get_deployment", {"namespace": namespace, "name": name}))

    if not calls:
        notes.append("focus: nothing flagged by the sweep; no targeted checks")
    return await _call_all(toolbox, calls, "focus", notes)


def _service_names_in(line: str, known_services: set[str]) -> set[str]:
    return {name for name in known_services if re.search(rf"(?<![a-z0-9-]){re.escape(name)}(?![a-z0-9-])", line)}


def upstream_services(evidence: list[Evidence], known_services: set[str]) -> set[str]:
    """Other services named in log lines about failed calls, e.g.
    'upstream unavailable: POST http://payment-service/...' or 'database unavailable: payments-db:5432'."""
    found: set[str] = set()
    for item in evidence:
        if item.source != "get_pod_logs" or not isinstance(item.result, dict):
            continue
        pod = str(item.arguments.get("pod", ""))
        own = {name for name in known_services if pod.startswith(f"{name}-")}
        for line in item.result.get("lines", []):
            if any(hint in line.lower() for hint in FAILED_CALL_HINTS):
                found |= _service_names_in(line, known_services) - own
    return found


async def follow_dependencies(
    toolbox: MCPToolbox, namespace: str, evidence: list[Evidence], notes: list[str]
) -> list[Evidence]:
    """One hop down the dependency chain: inspect services that failing services can't reach."""
    deployments = first_result(evidence, "list_deployments").get("deployments", [])
    targets = sorted(upstream_services(evidence, {d["name"] for d in deployments}))
    if not targets:
        return []
    notes.append(f"follow_dependencies: logs point at {', '.join(targets)}")
    pods_checked = {e.arguments.get("app") for e in evidence if e.source == "list_pods"}
    deployments_checked = {e.arguments.get("name") for e in evidence if e.source == "get_deployment"}
    calls: list[tuple[str, dict]] = []
    for service in targets:
        if service not in pods_checked:
            calls.append(("list_pods", {"namespace": namespace, "app": service}))
        if service not in deployments_checked:
            calls.append(("get_deployment", {"namespace": namespace, "name": service}))
    return await _call_all(toolbox, calls, "follow_dependencies", notes)
