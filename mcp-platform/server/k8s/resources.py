"""MCP resources: read-only documents addressed by URI, read by the client (the host
decides when), unlike tools, which the model decides to call.

- runbook://{service}: the team's runbook for a service (knowledge/runbooks/*.md)
- topology://{namespace}: which service calls which (knowledge/topology/*.json)
- k8s://{namespace}/deployments/{name}: a deployment's configured spec, live
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from mcp.server.mcpserver.exceptions import ResourceError

from config import Settings
from constants import DEPLOYMENT_SPEC_URI, NAME_PATTERN, RUNBOOK_URI, TOPOLOGY_URI
from k8s import ClusterBackend


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


def build_resources(backend: ClusterBackend, settings: Settings) -> list[ResourceDefinition]:
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
        return backend.get_deployment_spec(namespace, name).model_dump(mode="json")

    return [
        ResourceDefinition(RUNBOOK_URI, "runbook", "The team's runbook for a service: dependencies, what its "
                           "log messages mean, known failure modes, safe actions.", "text/markdown", read_runbook),
        ResourceDefinition(TOPOLOGY_URI, "topology", "Which service calls which in a namespace (the dependency "
                           "map).", "application/json", read_topology),
        ResourceDefinition(DEPLOYMENT_SPEC_URI, "deployment-spec", "What a deployment is configured to run: "
                           "image, env var names (never values), CPU/memory requests and limits, probes.",
                           "application/json", read_deployment_spec),
    ]
