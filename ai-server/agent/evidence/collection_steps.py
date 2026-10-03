"""The fixed evidence-collection steps: which MCP tools to call, decided by code from
what earlier calls returned (see agent/evidence/helpers.py for the rules). The LLM only reasons
over the result. Calls within a step run in parallel."""

import asyncio
from dataclasses import dataclass

from agent.evidence.helpers import (
    degraded_deployments,
    failing_services,
    first_result,
    is_suspected,
    services_blamed_in_logs,
    slow_services,
    suspected_first,
    unhealthy_pods,
    without_stale_pod_events,
)
from agent.evidence.mcp_toolbox import MCPToolbox
from agent.models import Evidence, IncidentScope
from constants import SUMMARIZE_ARGUMENT, McpResource, McpTool, Metric, Step

ToolCall = tuple[McpTool, dict]


@dataclass(frozen=True)
class CollectionLimits:
    error_rate_threshold: float
    latency_threshold_ms: float
    max_pods: int
    max_services: int
    log_lines: int
    summarize_logs: bool = False
    use_service_knowledge: bool = False


def _log_arguments(namespace: str, pod: str, previous: bool, limits: CollectionLimits) -> dict:
    arguments = {"namespace": namespace, "pod": pod, "lines": limits.log_lines, "previous": previous}
    if limits.summarize_logs:
        arguments[SUMMARIZE_ARGUMENT] = True
    return arguments


async def run_tool_calls(toolbox: MCPToolbox, calls: list[ToolCall], step: Step, notes: list[str]) -> list[Evidence]:
    """Run all calls concurrently; tools the MCP server doesn't offer are skipped and noted."""
    available = []
    for tool, arguments in calls:
        if toolbox.has(tool):
            available.append((tool, arguments))
        else:
            notes.append(f"{step}: skipped {tool} (tool not offered by the MCP server)")
    return list(await asyncio.gather(*(toolbox.call(tool, arguments, step) for tool, arguments in available)))


async def read_service_knowledge(toolbox: MCPToolbox, template: McpResource, parameters: list[dict[str, str]],
                                 step: Step, notes: list[str]) -> list[Evidence]:
    """Read team knowledge (MCP resources) in parallel. Knowledge is optional: missing
    items (no runbook for a service) are noted, not kept as evidence."""
    if not toolbox.offers(template):
        return []
    read = await asyncio.gather(*(toolbox.read_resource(template, step, **p) for p in parameters))
    for item in read:
        if item.error:
            notes.append(f"{step}: no {item.source} for {item.arguments['uri']}")
    return [item for item in read if not item.error]


async def collect_namespace_overview(toolbox: MCPToolbox, namespace: str, limits: CollectionLimits,
                                     notes: list[str]) -> list[Evidence]:
    """Broad, cheap first look: service health, pods, warning events and deployments, plus
    the service map (who calls whom) when the team knowledge is used."""
    tools_evidence, knowledge = await asyncio.gather(
        run_tool_calls(toolbox, [
            (McpTool.GET_SERVICE_OVERVIEW, {"namespace": namespace}),
            (McpTool.LIST_PODS, {"namespace": namespace}),
            (McpTool.LIST_EVENTS, {"namespace": namespace, "warnings_only": True}),
            (McpTool.LIST_DEPLOYMENTS, {"namespace": namespace}),
        ], Step.COLLECT_NAMESPACE_OVERVIEW, notes),
        read_service_knowledge(toolbox, McpResource.TOPOLOGY, [{"namespace": namespace}] if limits.use_service_knowledge
                               else [], Step.COLLECT_NAMESPACE_OVERVIEW, notes),
    )
    evidence = [*tools_evidence, *knowledge]
    pods = first_result(evidence, McpTool.LIST_PODS).get("pods", [])
    for item in evidence:
        if item.source == McpTool.LIST_EVENTS and isinstance(item.result, dict):
            kept, dropped = without_stale_pod_events(item.result.get("events", []), pods)
            if dropped:
                item.result = {**item.result, "events": kept, "stale_pod_events_hidden": dropped}
                notes.append(f"{Step.COLLECT_NAMESPACE_OVERVIEW}: hid {dropped} events of pods that "
                             "no longer exist or were only starting up")
    return evidence


def _unhealthy_pod_checks(pods: list[dict], namespace: str, suspected: list[str], limits: CollectionLimits) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for pod in sorted(unhealthy_pods(pods), key=lambda p: not is_suspected(p.get("app") or "", suspected))[:limits.max_pods]:
        crashed_before = pod.get("restarts", 0) > 0
        calls.append((McpTool.GET_POD_STATUS, {"namespace": namespace, "pod": pod["name"]}))
        calls.append((McpTool.GET_POD_LOGS, _log_arguments(namespace, pod["name"], crashed_before, limits)))
    return calls


def _degraded_service_checks(
    services: list[dict], pods: list[dict], deployments: list[dict], namespace: str,
    scope: IncidentScope, limits: CollectionLimits,
) -> list[ToolCall]:
    failing = failing_services(services, limits.error_rate_threshold)
    slow = slow_services(services, limits.latency_threshold_ms)
    suspected_deployed = [s for s in scope.suspected_services if any(s == d["name"] for d in deployments)]
    already_inspected_apps = {p.get("app") for p in unhealthy_pods(pods)}
    calls: list[ToolCall] = []
    for service in suspected_first(failing + slow + suspected_deployed, scope.suspected_services, limits.max_services):
        metrics = [Metric.ERROR_RATE] if service in failing or service not in slow else []
        if service in slow:
            metrics += [Metric.LATENCY_P99_MS, Metric.CPU_CORES, Metric.CPU_THROTTLED_RATIO]
        for metric in metrics:
            calls.append((McpTool.GET_METRICS, {"namespace": namespace, "service": service,
                                                "metric": metric, "minutes": scope.window_minutes}))
        running_pod = next((p for p in pods if p.get("app") == service), None)
        if running_pod and service not in already_inspected_apps:
            # Pods can be Running yet fail or crawl; logs name the failing dependency and
            # status shows the resource limits to compare CPU/memory against.
            calls.append((McpTool.GET_POD_LOGS, _log_arguments(namespace, running_pod["name"], False, limits)))
            if service in slow:
                calls.append((McpTool.GET_POD_STATUS, {"namespace": namespace, "pod": running_pod["name"]}))
    return calls


def _degraded_deployment_checks(deployments: list[dict], namespace: str, suspected: list[str],
                                limits: CollectionLimits) -> list[ToolCall]:
    return [
        (McpTool.GET_DEPLOYMENT, {"namespace": namespace, "name": name})
        for name in suspected_first(degraded_deployments(deployments), suspected, limits.max_services)
    ]


async def inspect_flagged_problems(
    toolbox: MCPToolbox, namespace: str, scope: IncidentScope, overview: list[Evidence],
    limits: CollectionLimits, notes: list[str],
) -> list[Evidence]:
    """Targeted checks on whatever the overview (or the question) flagged: unhealthy pods,
    failing or slow services, degraded deployments."""
    pods = first_result(overview, McpTool.LIST_PODS).get("pods", [])
    services = first_result(overview, McpTool.GET_SERVICE_OVERVIEW).get("services", [])
    deployments = first_result(overview, McpTool.LIST_DEPLOYMENTS).get("deployments", [])
    calls = [
        *_unhealthy_pod_checks(pods, namespace, scope.suspected_services, limits),
        *_degraded_service_checks(services, pods, deployments, namespace, scope, limits),
        *_degraded_deployment_checks(deployments, namespace, scope.suspected_services, limits),
    ]
    if not calls:
        notes.append(f"{Step.INSPECT_FLAGGED_PROBLEMS}: nothing flagged by the overview; no targeted checks")
    flagged = suspected_first(
        [*(p.get("app") for p in unhealthy_pods(pods) if p.get("app")),
         *failing_services(services, limits.error_rate_threshold),
         *slow_services(services, limits.latency_threshold_ms),
         *degraded_deployments(deployments)],
        scope.suspected_services, limits.max_services)
    tools_evidence, runbooks = await asyncio.gather(
        run_tool_calls(toolbox, calls, Step.INSPECT_FLAGGED_PROBLEMS, notes),
        read_service_knowledge(toolbox, McpResource.RUNBOOK, [{"service": s} for s in flagged]
                               if limits.use_service_knowledge else [], Step.INSPECT_FLAGGED_PROBLEMS, notes),
    )
    return [*tools_evidence, *runbooks]


async def trace_failing_dependencies(
    toolbox: MCPToolbox, namespace: str, evidence: list[Evidence], window_minutes: int, limits: CollectionLimits,
    notes: list[str],
) -> list[Evidence]:
    """One hop down the dependency chain: inspect the services that error logs blame."""
    deployments = first_result(evidence, McpTool.LIST_DEPLOYMENTS).get("deployments", [])
    blamed = sorted(services_blamed_in_logs(evidence, {d["name"] for d in deployments}))
    if not blamed:
        return []
    notes.append(f"{Step.TRACE_FAILING_DEPENDENCIES}: logs point at {', '.join(blamed)}")
    pods_checked = {e.arguments.get("app") for e in evidence if e.source == McpTool.LIST_PODS}
    deployments_checked = {e.arguments.get("name") for e in evidence if e.source == McpTool.GET_DEPLOYMENT}
    metrics_checked = {(e.arguments.get("service"), e.arguments.get("metric"))
                       for e in evidence if e.source == McpTool.GET_METRICS}
    calls: list[ToolCall] = []
    for service in blamed:
        if service not in pods_checked:
            calls.append((McpTool.LIST_PODS, {"namespace": namespace, "app": service}))
        if service not in deployments_checked:
            calls.append((McpTool.GET_DEPLOYMENT, {"namespace": namespace, "name": service}))
        # Down or just slow? The dependency's own error rate and latency tell them apart.
        for metric in (Metric.ERROR_RATE, Metric.LATENCY_P99_MS):
            if (service, metric) not in metrics_checked:
                calls.append((McpTool.GET_METRICS, {"namespace": namespace, "service": service,
                                                    "metric": metric, "minutes": window_minutes}))
    runbooks_read = {e.arguments.get("uri") for e in evidence}
    unread = [s for s in blamed if McpResource.RUNBOOK.format(service=s) not in runbooks_read]
    tools_evidence, runbooks = await asyncio.gather(
        run_tool_calls(toolbox, calls, Step.TRACE_FAILING_DEPENDENCIES, notes),
        read_service_knowledge(toolbox, McpResource.RUNBOOK, [{"service": s} for s in unread]
                               if limits.use_service_knowledge else [], Step.TRACE_FAILING_DEPENDENCIES, notes),
    )
    return [*tools_evidence, *runbooks]
