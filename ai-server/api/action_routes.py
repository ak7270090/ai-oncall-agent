"""Proposed changes, run with a human's approval (Phase 18)."""

from fastapi import APIRouter, HTTPException, status

from actions import (
    ActionState,
    ApprovalDecision,
    UnknownActionError,
    WrongActionStateError,
)
from api.dependencies import ActionRegistryDep, MCPConnectorDep, SettingsDep
from api.schemas import ActionRequest

router = APIRouter(prefix="/actions", tags=["actions"])


@router.post("", response_model=ActionState, status_code=status.HTTP_202_ACCEPTED)
async def start_action(request: ActionRequest, settings: SettingsDep, open_mcp: MCPConnectorDep,
                       registry: ActionRegistryDep) -> ActionState:
    """Start one proposed change (e.g. from a report's proposed_actions). It waits for a
    human's approval: poll GET /actions/{id} for status `awaiting_approval` and the question,
    then answer with POST /actions/{id}/approval."""
    return registry.start(request.action, request.namespace or settings.default_namespace, open_mcp)


@router.get("/{action_id}", response_model=ActionState)
async def get_action(action_id: str, registry: ActionRegistryDep) -> ActionState:
    try:
        return registry.get(action_id)
    except UnknownActionError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error


@router.post("/{action_id}/approval", response_model=ActionState)
async def approve_action(action_id: str, decision: ApprovalDecision, registry: ActionRegistryDep) -> ActionState:
    """Approve or reject an action that is awaiting approval."""
    try:
        return registry.decide(action_id, decision)
    except UnknownActionError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except WrongActionStateError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
