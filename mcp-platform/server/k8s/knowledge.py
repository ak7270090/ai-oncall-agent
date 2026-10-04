"""The team's knowledge as MCP resources: read-only documents addressed by URI, read by
the client (the host decides when), unlike tools, which the model decides to call.

- runbook://{service}: the team's runbook for a service (knowledge/runbooks/*.md)
- topology://{namespace}: which service calls which (knowledge/topology/*.json)
- k8s://{namespace}/deployments/{name}: a deployment's configured spec, live

Plus completions (autocomplete) for their arguments: a client typing runbook://pay...
gets payment-service, payments-db. MCP completions cover prompt and resource-template
arguments; tool arguments have none.
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from mcp.server.mcpserver.exceptions import ResourceError
from mcp_types import (
    Completion,
    CompletionArgument,
    CompletionContext,
    PromptReference,
    ResourceTemplateReference,
)

from config import Settings
from constants import NAME_PATTERN
from k8s.cluster.access import ClusterError, ClusterReader
from k8s.constants import DEPLOYMENT_SPEC_URI, RUNBOOK_URI, TOPOLOGY_URI


@dataclass(frozen=True)
class ResourceDefinition:
    uri: str
    name: str
    description: str
    mime_type: str
    read: Callable[..., Any]


def _require_name(value: str, what: str) -> None:
    # Names end up in file paths: only Kubernetes-style names are allowed.
    if not re.fullmatch(NAME_PATTERN, value):
        raise ResourceError(f"Invalid {what} '{value}'")


def runbook_services(settings: Settings) -> list[str]:
    return sorted(path.stem for path in (settings.knowledge_dir / "runbooks").glob("*.md"))


def build_resources(reader: ClusterReader, settings: Settings) -> list[ResourceDefinition]:
    def require_allowed(namespace: str) -> None:
        if namespace not in settings.allowed_namespaces:
            raise ResourceError(f"Namespace '{namespace}' is not allowed. Allowed: {', '.join(settings.allowed_namespaces)}")

    def read_runbook(service: str) -> str:
        _require_name(service, "service")
        path = settings.knowledge_dir / "runbooks" / f"{service}.md"
        if not path.is_file():
            raise ResourceError(f"No runbook for '{service}'. Runbooks exist for: {', '.join(runbook_services(settings))}")
        return path.read_text(encoding="utf-8")

    def read_topology(namespace: str) -> dict:
        require_allowed(namespace)
        path = settings.knowledge_dir / "topology" / f"{namespace}.json"
        if not path.is_file():
            raise ResourceError(f"No service map for namespace '{namespace}'")
        return json.loads(path.read_text(encoding="utf-8"))

    def read_deployment_spec(namespace: str, name: str) -> dict:
        require_allowed(namespace)
        _require_name(name, "deployment")
        return reader.get_deployment_spec(namespace, name).model_dump(mode="json")

    return [
        ResourceDefinition(RUNBOOK_URI, "runbook", "The team's runbook for a service: dependencies, what its "
                           "log messages mean, known failure modes, safe actions.", "text/markdown", read_runbook),
        ResourceDefinition(TOPOLOGY_URI, "topology", "Which service calls which in a namespace (the dependency "
                           "map).", "application/json", read_topology),
        ResourceDefinition(DEPLOYMENT_SPEC_URI, "deployment-spec", "What a deployment is configured to run: "
                           "image, env var names (never values), CPU/memory requests and limits, probes.",
                           "application/json", read_deployment_spec),
    ]


def build_completion_handler(reader: ClusterReader, settings: Settings):
    def candidates(template: str, argument: str, context: dict[str, str]) -> list[str]:
        if argument == "namespace" and template in (TOPOLOGY_URI, DEPLOYMENT_SPEC_URI):
            return settings.allowed_namespaces
        if argument == "service" and template == RUNBOOK_URI:
            return runbook_services(settings)
        if argument == "name" and template == DEPLOYMENT_SPEC_URI:
            namespace = context.get("namespace", settings.default_namespace)
            if namespace not in settings.allowed_namespaces:
                return []
            try:
                return [d.name for d in reader.list_deployments(namespace)]
            except ClusterError:
                return []
        return []

    async def complete(ref: PromptReference | ResourceTemplateReference, argument: CompletionArgument,
                       context: CompletionContext | None) -> Completion | None:
        if not isinstance(ref, ResourceTemplateReference):
            return None
        known = (context.arguments if context and context.arguments else {})
        matches = sorted(v for v in candidates(ref.uri, argument.name, known) if v.startswith(argument.value))
        return Completion(values=matches[: settings.max_completion_values], total=len(matches),
                          has_more=len(matches) > settings.max_completion_values)

    return complete
