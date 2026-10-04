from itertools import count
from typing import Annotated

import anyio
from mcp.server.mcpserver import Context
from pydantic import Field

from constants import NAME_PATTERN
from prometheus.config import PrometheusServerSettings
from prometheus.constants import (
    DEFAULT_HISTORY_MINUTES,
    MAX_HISTORY_MINUTES,
    METRIC_UNITS,
    SERVICE_OVERVIEW_METRICS,
    Metric,
    MetricName,
)
from prometheus.metrics.access import MetricsReader, QueryDone
from prometheus.models import MetricSeries, ServiceOverview
from tool_definitions import READ_ONLY_TOOL, ToolDefinition, namespace_guard


def build_prometheus_tools(reader: MetricsReader, settings: PrometheusServerSettings) -> list[ToolDefinition]:
    Namespace, require_allowed = namespace_guard(settings)
    ServiceName = Annotated[str, Field(pattern=NAME_PATTERN, description="Service name, e.g. payment-service")]

    async def get_service_overview(ctx: Context, namespace: Namespace = settings.default_namespace) -> ServiceOverview:
        """Current request rate, error rate (share of 5xx) and p99 latency for every
        service in the namespace. Start here to see which service is unhealthy.
        Only services with running, scraped pods appear: a service missing here may have
        no pods at all (check list_deployments / list_pods)."""
        require_allowed(namespace)
        on_query_done = query_progress_reporter(ctx, len(SERVICE_OVERVIEW_METRICS))
        services = await anyio.to_thread.run_sync(reader.service_overview, namespace, on_query_done)
        return ServiceOverview(namespace=namespace, window=settings.metrics_rate_window, services=services)

    def get_metrics(
        service: ServiceName,
        metric: MetricName,
        namespace: Namespace = settings.default_namespace,
        minutes: Annotated[int, Field(ge=1, le=MAX_HISTORY_MINUTES, description="How far back to look")] = DEFAULT_HISTORY_MINUTES,
    ) -> MetricSeries:
        """History of one metric for a service, one sample per step, oldest first. Use it to
        see when a problem started (e.g. error_rate jumping after a deploy).
        Metrics: request_rate (req/s), error_rate (0-1 share of 5xx), error_count (5xx per
        window), latency_p99_ms, cpu_cores and memory_mb (both per pod; compare
        with the limits from get_pod_status), cpu_throttled_ratio (share of time the
        container was held at its CPU limit: high values mean CPU-starved even when
        average cpu_cores looks low). Empty samples = no data."""
        require_allowed(namespace)
        return MetricSeries(
            namespace=namespace,
            service=service,
            metric=metric,
            unit=METRIC_UNITS[metric],
            step_seconds=settings.metrics_step_seconds,
            samples=reader.metric_history(namespace, service, metric, minutes),
        )

    return [ToolDefinition(tool, READ_ONLY_TOOL) for tool in (get_service_overview, get_metrics)]


def query_progress_reporter(ctx: Context, total_queries: int) -> QueryDone:
    """A QueryDone callback that sends MCP progress ("2 of 3: error_rate queried in 0.4s").

    The reader runs in a worker thread (anyio.to_thread), so each report is handed back
    to the event loop with anyio.from_thread. Without a progress token from the client,
    report_progress does nothing."""
    finished = count(1)

    def report(metric: Metric, seconds: float) -> None:
        anyio.from_thread.run(ctx.report_progress, next(finished), total_queries, f"{metric} queried in {seconds:.1f}s")

    return report
