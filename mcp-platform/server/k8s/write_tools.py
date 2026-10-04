"""Write tools (Phase 18): restart, scale or roll back a Deployment. Off unless
MCP_ENABLE_WRITE_TOOLS=true.

Every call asks a human first (MCP elicitation): "Roll back payment-service in shop to
revision 4?" with an approve/reject answer and a reason. No approval, no change; the
result says what was or wasn't done. Arguments are checked before anyone is asked: a
replica count out of bounds or a revision that doesn't exist is refused right away.

With protocol 2026-07-28 the question travels as an "input required" result and the tool
runs again with the answer; the question is built from the arguments only, so both runs
ask exactly the same thing.

With authentication on (Phase 20) the approver must be someone other than the requester
whose role may run the tool; otherwise the approval is refused and nothing changes."""

from typing import Annotated

from mcp.server.elicitation import (
    AcceptedElicitation,
    CancelledElicitation,
    ElicitationResult,
)
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.resolve import Elicit, Resolve
from pydantic import BaseModel, Field

from access import AccessPolicy, get_caller
from config import Settings
from constants import Operation
from k8s import ClusterBackend, ClusterOperations
from k8s.models import OperationResult
from tool_helpers import ToolDefinition, change_tool, namespace_guard


class Approval(BaseModel):
    approve: bool = Field(description="Approve this change to the cluster?")
    reason: str = Field(description="Why (kept with the result)")
    approver: str = Field(min_length=1, description="Your user name (the AI server fills in the signed-in user)")


def build_operation_tools(cluster: ClusterBackend, operations: ClusterOperations, settings: Settings,
                          policy: AccessPolicy | None = None) -> list[ToolDefinition]:
    """Write tools; with a `policy` (authentication on) approvers are checked too."""
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

    def perform(operation: Operation, namespace: str, name: str, approval: ElicitationResult[Approval],
                change) -> OperationResult:
        requester = get_caller().user
        result = OperationResult(operation=operation, namespace=namespace, deployment=name, done=False,
                                 detail="", approval="declined", requested_by=requester)
        if not isinstance(approval, AcceptedElicitation):
            state = "cancelled" if isinstance(approval, CancelledElicitation) else "declined"
            return result.model_copy(update={"approval": state, "detail": f"Not done: the change was {state}."})
        answer = approval.data
        result = result.model_copy(update={"approval_reason": answer.reason, "approved_by": answer.approver})
        if not answer.approve:
            return result.model_copy(update={"approval": "rejected", "detail": "Not done: the change was rejected."})
        if policy and (refusal := policy.refusal_for_approval(requester, answer.approver, operation)):
            return result.model_copy(update={"approval": "refused", "detail": f"Not done: approval refused, {refusal}."})
        return result.model_copy(update={"approval": "approved", "done": True, "detail": change()})

    def restart_deployment(
        name: Deployment,
        namespace: Namespace = settings.default_namespace,
        approval: Annotated[ElicitationResult[Approval], Resolve(ask_restart)] = None,
    ) -> OperationResult:
        """Restart all pods of a deployment (rolling). Asks a human for approval first."""
        return perform(Operation.RESTART_DEPLOYMENT, namespace, name, approval,
                       lambda: operations.restart_deployment(namespace, name))

    def scale_deployment(
        name: Deployment,
        replicas: Annotated[int, Field(ge=0, le=settings.max_replicas, description="Desired number of pods")],
        namespace: Namespace = settings.default_namespace,
        approval: Annotated[ElicitationResult[Approval], Resolve(ask_scale)] = None,
    ) -> OperationResult:
        """Set a deployment's number of pods, e.g. scale back up a service someone scaled to
        0. Asks a human for approval first."""
        return perform(Operation.SCALE_DEPLOYMENT, namespace, name, approval,
                       lambda: operations.scale_deployment(namespace, name, replicas))

    def rollback_deployment(
        name: Deployment,
        revision: Annotated[int, Field(ge=1, description="Revision to go back to (see get_deployment)")],
        namespace: Namespace = settings.default_namespace,
        approval: Annotated[ElicitationResult[Approval], Resolve(ask_rollback)] = None,
    ) -> OperationResult:
        """Roll a deployment back to an earlier revision (its image and configuration), e.g.
        after a bad release. Asks a human for approval first."""
        return perform(Operation.ROLLBACK_DEPLOYMENT, namespace, name, approval,
                       lambda: operations.rollback_deployment(namespace, name, revision))

    return [
        ToolDefinition(restart_deployment, change_tool(idempotent=False)),
        ToolDefinition(scale_deployment, change_tool(idempotent=True)),
        ToolDefinition(rollback_deployment, change_tool(idempotent=False)),
    ]
