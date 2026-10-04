"""Pod tools: list_pods, get_pod_status, get_pod_logs.

get_pod_logs(summarize=true) asks the *client's* LLM to condense the lines (MCP
sampling), so this server needs no LLM, no API key and no model choice. The request
carries model preferences (cheap and fast matter more than intelligence); the client
picks a model it has that fits.

With protocol 2026-07-28 the SDK asks the client through an "input required" result and
runs the tool again when the client answers, and the second run must ask the identical
question. Live logs keep growing between the two runs, so both read the same lines from
RecentLogs."""

import threading
import time
from collections.abc import Callable
from typing import Annotated

from mcp.server.mcpserver import Context
from mcp.server.mcpserver.resolve import Resolve, Sample
from mcp_types import (
    CreateMessageResult,
    ModelPreferences,
    SamplingMessage,
    TextContent,
)
from pydantic import Field

from config import Settings
from k8s.cluster.access import ClusterReader
from k8s.constants import (
    DEFAULT_LOG_LINES,
    LOG_LINES_KEPT_WITH_SUMMARY,
    LOG_SUMMARY_COST_PRIORITY,
    LOG_SUMMARY_INTELLIGENCE_PRIORITY,
    LOG_SUMMARY_SPEED_PRIORITY,
    LOG_SUMMARY_TASK,
    MAX_LOG_LINES,
)
from k8s.models import PodDetail, PodList, PodLogs, summarize_pod
from tool_definitions import READ_ONLY_TOOL, ToolDefinition, namespace_guard

LOG_SUMMARY_PROMPT = """You summarize Kubernetes pod logs for an on-call engineer.
Write plain text, at most 12 lines:
- every distinct error or warning (merge repeats), how many times it occurred, and its
  first and last timestamp, quoting the most informative line exactly;
- other services, hosts or URLs the errors mention (dependencies);
- the last 2 lines, verbatim.
If there are no errors or warnings, say so in one line. Don't guess the cause."""

LOG_SUMMARY_PREFERENCES = ModelPreferences(
    cost_priority=LOG_SUMMARY_COST_PRIORITY,
    speed_priority=LOG_SUMMARY_SPEED_PRIORITY,
    intelligence_priority=LOG_SUMMARY_INTELLIGENCE_PRIORITY,
)

LogKey = tuple[str, str, int, bool]  # namespace, pod, lines, previous


class RecentLogs:
    """Log lines fetched in the last few seconds, keyed by request, so the sampling
    retry round sees exactly the lines the first round summarized."""

    def __init__(self, reader: ClusterReader, ttl_seconds: float, clock: Callable[[], float] = time.monotonic):
        self._reader = reader
        self._ttl = ttl_seconds
        self._clock = clock
        self._entries: dict[LogKey, tuple[float, list[str]]] = {}
        self._lock = threading.Lock()  # tools and resolvers run in worker threads

    def get(self, namespace: str, pod: str, lines: int, previous: bool) -> list[str]:
        key, now = (namespace, pod, lines, previous), self._clock()
        with self._lock:
            self._entries = {k: v for k, v in self._entries.items() if now - v[0] < self._ttl}
            if key in self._entries:
                return self._entries[key][1]
        fetched = self._reader.get_pod_logs(namespace, pod, lines, previous)
        with self._lock:
            self._entries[key] = (now, fetched)
        return fetched


def client_can_sample(ctx: Context) -> bool:
    capabilities = ctx.client_capabilities
    return bool(capabilities and capabilities.sampling)


def build_log_summary_request(pod: str, namespace: str, previous: bool, log_lines: list[str],
                              settings: Settings) -> Sample:
    which = "previous (crashed) container" if previous else "current container"
    text = f"Logs of pod {pod} in namespace {namespace}, {which}, oldest first:\n" + "\n".join(log_lines)
    return Sample(
        [SamplingMessage(role="user", content=TextContent(type="text", text=text))],
        system_prompt=LOG_SUMMARY_PROMPT,
        max_tokens=settings.log_summary_max_tokens,
        model_preferences=LOG_SUMMARY_PREFERENCES,
        metadata={"task": LOG_SUMMARY_TASK, "pod": pod},
    )


def summary_text(result: CreateMessageResult) -> str:
    blocks = result.content if isinstance(result.content, list) else [result.content]
    return "\n".join(block.text for block in blocks if isinstance(block, TextContent)).strip()


def build_pod_tools(reader: ClusterReader, settings: Settings) -> list[ToolDefinition]:
    Namespace, require_allowed = namespace_guard(settings)
    recent_logs = RecentLogs(reader, settings.log_cache_seconds)

    def request_log_summary(ctx: Context, pod: str, namespace: str, lines: int, previous: bool,
                            summarize: bool) -> Sample | None:
        """Resolver for get_pod_logs' `summary`: a sampling request, or None for raw lines."""
        if not summarize or not client_can_sample(ctx):
            return None
        require_allowed(namespace)
        log_lines = recent_logs.get(namespace, pod, lines, previous)
        if len(log_lines) < settings.log_summary_min_lines:
            return None
        return build_log_summary_request(pod, namespace, previous, log_lines, settings)

    def list_pods(
        namespace: Namespace = settings.default_namespace,
        app: Annotated[str | None, Field(description="Only pods with this `app` label, e.g. payment-service")] = None,
    ) -> PodList:
        """List pods with phase, readiness, restart count and a one-word status
        (e.g. CrashLoopBackOff, ImagePullBackOff, Running). Start here to find unhealthy pods."""
        require_allowed(namespace)
        return PodList(namespace=namespace, pods=[summarize_pod(p) for p in reader.list_pods(namespace, app)])

    def get_pod_status(pod: str, namespace: Namespace = settings.default_namespace) -> PodDetail:
        """Detailed status of one pod: conditions and, per container, state, reason,
        restart count and the last termination reason / exit code (why it last crashed)."""
        require_allowed(namespace)
        return reader.get_pod(namespace, pod)

    def get_pod_logs(
        pod: str,
        namespace: Namespace = settings.default_namespace,
        lines: Annotated[int, Field(ge=1, le=MAX_LOG_LINES, description="Recent lines to return")] = DEFAULT_LOG_LINES,
        previous: Annotated[bool, Field(description="Logs of the previous (crashed) container instead of the current one")] = False,
        summarize: Annotated[bool, Field(description=(
            "Return a short summary of the lines (distinct errors with counts and first/last "
            "time, dependencies mentioned) plus the newest few lines, instead of all lines. "
            "Useful for many lines; short logs and clients without sampling get raw lines."))] = False,
        summary: Annotated[CreateMessageResult | None, Resolve(request_log_summary)] = None,
    ) -> PodLogs:
        """Recent log lines of a pod (newest last), each starting with its timestamp. For a
        crash-looping pod set previous=true: the current container has usually only just
        started. Compare timestamps with now: old errors may belong to an earlier problem."""
        require_allowed(namespace)
        if summary is None:
            return PodLogs(namespace=namespace, pod=pod, previous=previous,
                           lines=reader.get_pod_logs(namespace, pod, lines, previous))
        log_lines = recent_logs.get(namespace, pod, lines, previous)
        return PodLogs(
            namespace=namespace, pod=pod, previous=previous, lines=log_lines[-LOG_LINES_KEPT_WITH_SUMMARY:],
            summary=summary_text(summary), summarized_by=summary.model, summarized_lines=len(log_lines),
        )

    return [ToolDefinition(tool, READ_ONLY_TOOL) for tool in (list_pods, get_pod_status, get_pod_logs)]
