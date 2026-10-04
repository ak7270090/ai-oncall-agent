"""Completions (autocomplete) for resource template arguments: a client typing
runbook://pay... gets payment-service, payments-db. MCP completions cover prompt and
resource-template arguments; tool arguments have none."""

from mcp_types import (
    Completion,
    CompletionArgument,
    CompletionContext,
    PromptReference,
    ResourceTemplateReference,
)

from config import Settings
from k8s.backend import ClusterBackend, ClusterError
from k8s.constants import DEPLOYMENT_SPEC_URI, RUNBOOK_URI, TOPOLOGY_URI
from k8s.resources import runbook_services


def build_completion_handler(backend: ClusterBackend, settings: Settings):
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
                return [d.name for d in backend.list_deployments(namespace)]
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
