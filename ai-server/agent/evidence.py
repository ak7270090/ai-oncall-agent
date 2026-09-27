"""Deterministic evidence gathering: which MCP tools to call, decided by code from
what earlier calls returned. The LLM only reasons over the result."""

import asyncio
import re
from dataclasses import dataclass
from typing import Any

from agent.models import Evidence, IncidentScope
from agent.toolbox import MCPToolbox

UPSTREAM_URL = re.compile(r"https?://([a-z0-9]([a-z0-9-]*[a-z0-9])?)(?=[:/.\s]|$)")
UPSTREAM_HINTS = ("upstream", "connection refused", "connecterror", "timed out", "unavailable")


@dataclass(frozen=True)
class GatheringLimits:
    error_rate_threshold: float
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


async def sweep(toolbox: MCPToolbox, namespace: str, notes: list[str]) -> list[Evidence]:
    """Broad, cheap overview of the namespace."""
    return await _call_all(toolbox, [
        ("get_service_overview", {"namespace": namespace}),
        ("list_pods", {"namespace": namespace}),
        ("list_events", {"namespace": namespace, "warnings_only": True}),
        ("list_deployments", {"namespace": namespace}),
    ], "sweep", notes)


def unhealthy_pods(pods: list[dict]) -> list[dict]:
    return [p for p in pods if not p.get("ready") or p.get("restarts", 0) > 0 or p.get("status") != "Running"]


def failing_services(services: list[dict], threshold: float) -> list[str]:
    return [s["service"] for s in services if (s.get("error_rate") or 0) >= threshold]


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

    failing = _prioritized(failing_services(services, limits.error_rate_threshold) + [
        s for s in suspected if any(s == d["name"] for d in deployments)
    ], suspected, limits.max_services)
    inspected_apps = {p.get("app") for p in unhealthy_pods(pods)}
    for service in failing:
        calls.append(("get_metrics", {"namespace": namespace, "service": service,
                                      "metric": "error_rate", "minutes": scope.window_minutes}))
        healthy_pod = next((p for p in pods if p.get("app") == service), None)
        if healthy_pod and service not in inspected_apps:
            # Pods can be Running yet return errors; their logs name the failing dependency.
            calls.append(("get_pod_logs", {"namespace": namespace, "pod": healthy_pod["name"],
                                           "lines": limits.log_lines, "previous": False}))

    for name in _prioritized(troubled_deployments(deployments), suspected, limits.max_services):
        calls.append(("get_deployment", {"namespace": namespace, "name": name}))

    if not calls:
        notes.append("focus: nothing flagged by the sweep; no targeted checks")
    return await _call_all(toolbox, calls, "focus", notes)


def upstream_services(evidence: list[Evidence], known_services: set[str]) -> set[str]:
    """Services named in error log lines about failed calls (e.g. 'upstream unavailable: POST http://payment-service/...')."""
    found: set[str] = set()
    for item in evidence:
        if item.source != "get_pod_logs" or not isinstance(item.result, dict):
            continue
        for line in item.result.get("lines", []):
            if any(hint in line.lower() for hint in UPSTREAM_HINTS):
                found.update(m.group(1) for m in UPSTREAM_URL.finditer(line) if m.group(1) in known_services)
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
