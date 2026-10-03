"""Runs proposed changes (Phase 18) with a human in the loop.

POST /actions starts one change in the background and returns at once. The MCP write tool
asks for approval (MCP elicitation); the action then waits in `awaiting_approval` with the
server's question until a human answers through POST /actions/{id}/approval, or until the
approval timeout. Only an explicit approval lets the MCP server make the change.

State is kept in memory: one AI server process; actions are lost on restart."""

import asyncio
import json
import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from mcp import Client
from mcp_types import ElicitResult
from pydantic import BaseModel, Field

from agent.models import ProposedAction
from constants import ActionStatus
from mcp_client.langchain_tools import extract_result_text

logger = logging.getLogger(__name__)

ACTION_ID_LENGTH = 12


class ApprovalDecision(BaseModel):
    approve: bool
    reason: str = Field(min_length=1, max_length=500, description="Why; kept with the result")


class ActionState(BaseModel):
    id: str
    action: ProposedAction
    namespace: str
    status: ActionStatus
    question: str | None = Field(default=None, description="What the MCP server asks the human to approve")
    approval_reason: str | None = None
    result: dict[str, Any] | None = Field(default=None, description="The MCP tool's OperationResult")
    error: str | None = None
    updated_at: datetime


class UnknownActionError(Exception):
    pass


class WrongActionStateError(Exception):
    pass


OpenMcp = Callable[..., AbstractAsyncContextManager[Client]]


class _Action:
    def __init__(self, state: ActionState):
        self.state = state
        self.decision: asyncio.Future[ApprovalDecision] | None = None
        self.task: asyncio.Task | None = None

    def update(self, **changes: Any) -> None:
        self.state = self.state.model_copy(update={**changes, "updated_at": datetime.now(timezone.utc)})


class ActionRegistry:
    def __init__(self, approval_timeout_seconds: float):
        self._approval_timeout = approval_timeout_seconds
        self._actions: dict[str, _Action] = {}

    def start(self, action: ProposedAction, namespace: str, open_mcp: OpenMcp) -> ActionState:
        entry = _Action(ActionState(id=uuid4().hex[:ACTION_ID_LENGTH], action=action, namespace=namespace,
                                    status=ActionStatus.STARTING, updated_at=datetime.now(timezone.utc)))
        self._actions[entry.state.id] = entry
        entry.task = asyncio.create_task(self._run(entry, open_mcp))
        return entry.state

    def get(self, action_id: str) -> ActionState:
        return self._entry(action_id).state

    def decide(self, action_id: str, decision: ApprovalDecision) -> ActionState:
        entry = self._entry(action_id)
        if entry.state.status != ActionStatus.AWAITING_APPROVAL or entry.decision is None or entry.decision.done():
            raise WrongActionStateError(f"Action {action_id} is {entry.state.status}, not awaiting approval")
        entry.decision.set_result(decision)
        entry.update(approval_reason=decision.reason)
        return entry.state

    def _entry(self, action_id: str) -> _Action:
        if action_id not in self._actions:
            raise UnknownActionError(f"No action {action_id}")
        return self._actions[action_id]

    async def _run(self, entry: _Action, open_mcp: OpenMcp) -> None:
        action = entry.state.action
        try:
            async with open_mcp(elicitation_callback=self._approval_callback(entry)) as mcp_client:
                result = await mcp_client.call_tool(action.operation, action.tool_arguments(entry.state.namespace))
        except Exception as error:
            logger.warning("Action %s failed: %s", entry.state.id, error)
            entry.update(status=ActionStatus.FAILED, error=str(error))
            return
        text = extract_result_text(result)
        if result.is_error:
            entry.update(status=ActionStatus.FAILED, error=text)
            return
        outcome = json.loads(text)
        entry.update(status=ActionStatus.DONE if outcome.get("done") else ActionStatus.NOT_DONE, result=outcome)

    def _approval_callback(self, entry: _Action):
        async def ask_human(context: Any, params: Any) -> ElicitResult:
            entry.decision = asyncio.get_running_loop().create_future()
            entry.update(status=ActionStatus.AWAITING_APPROVAL, question=params.message)
            try:
                decision = await asyncio.wait_for(entry.decision, self._approval_timeout)
            except TimeoutError:
                entry.update(error=f"No approval within {self._approval_timeout:.0f}s")
                return ElicitResult(action="cancel")
            return ElicitResult(action="accept", content={"approve": decision.approve, "reason": decision.reason})

        return ask_human
