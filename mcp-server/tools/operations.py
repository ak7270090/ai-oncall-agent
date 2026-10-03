"""Write tools (Phase 18): restart, scale or roll back a Deployment. Off unless
MCP_ENABLE_WRITE_TOOLS=true.

Every call asks a human first (MCP elicitation): "Roll back payment-service in shop to
revision 4?" with an approve/reject answer and a reason. No approval, no change; the
result says what was or wasn't done. Arguments are checked before anyone is asked: a
replica count out of bounds or a revision that doesn't exist is refused right away.

With protocol 2026-07-28 the question travels as an "input required" result and the tool
runs again with the answer; the question is built from the arguments only, so both runs
ask exactly the same thing."""

from typing import Annotated

from mcp.server.elicitation import (
    AcceptedElicitation,
    CancelledElicitation,
    ElicitationResult,
)
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.resolve import Elicit, Resolve
from pydantic import BaseModel, Field

from cluster import ClusterBackend, ClusterOperations
from cluster.models import OperationResult
from config import Settings
from tools.helpers import ToolDefinition, change_tool, namespace_guard


class Approval(BaseModel):
    approve: bool = Field(description="Approve this change to the cluster?")
    reason: str = Field(description="Why (kept with the result)")


def _outcome(approval: ElicitationResult[Approval]) -> tuple[bool, str, str | None]:
    """(approved?, approval state, reason)."""
    if isinstance(approval, AcceptedElicitation):
        return approval.data.approve, "approved" if approval.data.approve else "rejected", approval.data.reason
    return False, "cancelled" if isinstance(approval, CancelledElicitation) else "declined", None


def build_operation_tools(cluster: ClusterBackend, operations: ClusterOperations,
                          settings: Settings) -> list[ToolDefinition]:
    Namespace, require_allowed = namespace_guard(settings)
    Deployment = Annotated[str, Field(description="Deployment name, e.g. payment-service")]

    def require_deployment(namespace: str, name: str):
        require_allowed(namespace)
        return cluster.get_deployment(namespace, name)  # raises a readable error if missing

    def ask_restart(name: str, namespace: str) -> Elicit[Approval]:
        require_deployment(namespace, name)
        return Elicit(f"Restart deployment {name} in {namespace}? All its pods are replaced, one by one.", Approval)

    def ask_scale(name: str, replicas: int, namespace: str) -> Elicit[Approval]:
        require_deployment(namespace, name)
        return Elicit(f"Scale deployment {name} in {namespace} to {replicas} replicas?", Approval)

    def ask_rollback(name: str, revision: int, namespace: str) -> Elicit[Approval]:
        deployment = require_deployment(namespace, name)
        target = next((r for r in deployment.revisions if r.revision == revision), None)
        if target is None:
            known = ", ".join(str(r.revision) for r in deployment.revisions) or "none"
            raise ToolError(f"Deployment '{name}' has no revision {revision} (revisions: {known})")
        return Elicit(f"Roll back deployment {name} in {namespace} to revision {revision} "
                      f"(image {target.image})?", Approval)

    def perform(operation: str, namespace: str, name: str, approval: ElicitationResult[Approval], change) -> OperationResult:
        approved, state, reason = _outcome(approval)
        detail = change() if approved else f"Not done: the change was {state}."
        return OperationResult(operation=operation, namespace=namespace, deployment=name, done=approved,
                               detail=detail, approval=state, approval_reason=reason)

    def restart_deployment(
        name: Deployment,
        namespace: Namespace = settings.default_namespace,
        approval: Annotated[ElicitationResult[Approval], Resolve(ask_restart)] = None,
    ) -> OperationResult:
        """Restart all pods of a deployment (rolling). Asks a human for approval first."""
        return perform("restart_deployment", namespace, name, approval,
                       lambda: operations.restart_deployment(namespace, name))

    def scale_deployment(
        name: Deployment,
        replicas: Annotated[int, Field(ge=0, le=settings.max_replicas, description="Desired number of pods")],
        namespace: Namespace = settings.default_namespace,
        approval: Annotated[ElicitationResult[Approval], Resolve(ask_scale)] = None,
    ) -> OperationResult:
        """Set a deployment's number of pods, e.g. scale back up a service someone scaled to
        0. Asks a human for approval first."""
        return perform("scale_deployment", namespace, name, approval,
                       lambda: operations.scale_deployment(namespace, name, replicas))

    def rollback_deployment(
        name: Deployment,
        revision: Annotated[int, Field(ge=1, description="Revision to go back to (see get_deployment)")],
        namespace: Namespace = settings.default_namespace,
        approval: Annotated[ElicitationResult[Approval], Resolve(ask_rollback)] = None,
    ) -> OperationResult:
        """Roll a deployment back to an earlier revision (its image and configuration), e.g.
        after a bad release. Asks a human for approval first."""
        return perform("rollback_deployment", namespace, name, approval,
                       lambda: operations.rollback_deployment(namespace, name, revision))

    return [
        ToolDefinition(restart_deployment, change_tool(idempotent=False)),
        ToolDefinition(scale_deployment, change_tool(idempotent=True)),
        ToolDefinition(rollback_deployment, change_tool(idempotent=False)),
    ]
