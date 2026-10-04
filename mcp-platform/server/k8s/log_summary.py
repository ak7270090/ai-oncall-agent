"""Log summaries through MCP sampling.

get_pod_logs(summarize=true) asks the *client's* LLM to condense the lines, so this
server needs no LLM, no API key and no model choice. The request carries model
preferences (cheap and fast matter more than intelligence); the client picks a model
it has that fits.

With protocol 2026-07-28 the SDK asks the client through an "input required" result and
runs the tool again when the client answers, and the second run must ask the identical
question. Live logs keep growing between the two runs, so both read the same lines from
RecentLogs."""

import threading
import time
from collections.abc import Callable

from mcp.server.mcpserver import Context
from mcp.server.mcpserver.resolve import Sample
from mcp_types import (
    CreateMessageResult,
    ModelPreferences,
    SamplingMessage,
    TextContent,
)

from config import Settings
from k8s.backend import ClusterBackend
from k8s.constants import (
    LOG_SUMMARY_COST_PRIORITY,
    LOG_SUMMARY_INTELLIGENCE_PRIORITY,
    LOG_SUMMARY_SPEED_PRIORITY,
    LOG_SUMMARY_TASK,
)

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

    def __init__(self, backend: ClusterBackend, ttl_seconds: float, clock: Callable[[], float] = time.monotonic):
        self._backend = backend
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
        fetched = self._backend.get_pod_logs(namespace, pod, lines, previous)
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
