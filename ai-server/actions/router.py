"""Proposed changes, run with a human's approval (Phase 18)."""

from fastapi import APIRouter, HTTPException, status

from actions.dependencies import ActionRegistryDep
from actions.registry import SelfApprovalError, UnknownActionError, WrongActionStateError
from actions.schemas import ActionRequest, ActionState, ApprovalDecision
from auth.dependencies import CurrentUserDep
from config import SettingsDep
from mcp_client.dependencies import MCPConnectorDep
from tracing import TracerDep

router = APIRouter(prefix="/actions", tags=["actions"])


@router.post("", response_model=ActionState, status_code=status.HTTP_202_ACCEPTED)
async def start_action(request: ActionRequest, settings: SettingsDep, open_mcp: MCPConnectorDep,
                       registry: ActionRegistryDep, user: CurrentUserDep, tracer: TracerDep) -> ActionState:
    """Start one proposed change (e.g. from a report's proposed_actions). It waits for a
    human's approval: poll GET /actions/{id} for status `awaiting_approval` and the question,
    then answer with POST /actions/{id}/approval. With sign-in on, someone other than the
    requester must approve, and the MCP server checks both people's roles."""
    return registry.start(request.action, request.namespace or settings.default_namespace, open_mcp, user, tracer)


@router.get("/{action_id}", response_model=ActionState)
async def get_action(action_id: str, registry: ActionRegistryDep, _: CurrentUserDep) -> ActionState:
    try:
        return registry.get(action_id)
    except UnknownActionError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error


@router.post("/{action_id}/approval", response_model=ActionState)
async def approve_action(action_id: str, decision: ApprovalDecision, registry: ActionRegistryDep,
                         approver: CurrentUserDep) -> ActionState:
    """Approve or reject an action that is awaiting approval, as the signed-in user."""
    try:
        return registry.decide(action_id, decision, approver)
    except UnknownActionError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except WrongActionStateError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    except SelfApprovalError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error
