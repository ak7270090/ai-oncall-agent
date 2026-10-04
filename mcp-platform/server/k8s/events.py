"""Event tool: list_events."""

from typing import Annotated

from pydantic import Field

from config import Settings
from k8s.cluster.access import ClusterReader
from k8s.constants import DEFAULT_EVENT_LIMIT, MAX_EVENT_LIMIT
from k8s.models import EventList
from tool_definitions import READ_ONLY_TOOL, ToolDefinition, namespace_guard


def build_event_tools(reader: ClusterReader, settings: Settings) -> list[ToolDefinition]:
    Namespace, require_allowed = namespace_guard(settings)

    def list_events(
        namespace: Namespace = settings.default_namespace,
        warnings_only: bool = True,
        limit: Annotated[int, Field(ge=1, le=MAX_EVENT_LIMIT)] = DEFAULT_EVENT_LIMIT,
    ) -> EventList:
        """Recent Kubernetes events, newest first (BackOff, Unhealthy probes, FailedScheduling,
        OOMKilling, image pull errors...). Often the fastest way to see why something fails."""
        require_allowed(namespace)
        return EventList(namespace=namespace, events=reader.list_events(namespace, warnings_only, limit))

    return [ToolDefinition(list_events, READ_ONLY_TOOL)]
