"""Runs proposed changes (Phase 18) with a human in the loop.

POST /actions starts one change in the background and returns at once. The MCP write tool
asks for approval (MCP elicitation); the action then waits in `awaiting_approval` with the
server's question until a human answers through POST /actions/{id}/approval, or until the
approval timeout. Only an explicit approval lets the MCP server make the change.

With sign-in on (Phase 19-20) the action runs with a write-scoped MCP token for the
person who started it, and someone else must approve it (four eyes; the MCP server
checks again). Each action is traced in Langfuse; the MCP server's audit log records the
same trace id.

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
from constants import WRITE_SCOPES, ActionStatus
from mcp_client.langchain_tools import extract_result_text
from tracing import InvestigationTracer

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
    requested_by: str
    approved_by: str | None = None
    approval_reason: str | None = None
    trace_id: str | None = None
    trace_url: str | None = None
    result: dict[str, Any] | None = Field(default=None, description="The MCP tool's OperationResult")
    error: str | None = None
    updated_at: datetime


class UnknownActionError(Exception):
    pass


class WrongActionStateError(Exception):
    pass


class SelfApprovalError(Exception):
    pass


OpenMcp = Callable[..., AbstractAsyncContextManager[Client]]


class _Action:
    def __init__(self, state: ActionState):
        self.state = state
        self.decision: asyncio.Future[tuple[ApprovalDecision, str]] | None = None
        self.task: asyncio.Task | None = None

    def update(self, **changes: Any) -> None:
        self.state = self.state.model_copy(update={**changes, "updated_at": datetime.now(timezone.utc)})


class ActionRegistry:
    def __init__(self, approval_timeout_seconds: float, require_second_person: bool = False):
        self._approval_timeout = approval_timeout_seconds
        self._require_second_person = require_second_person
        self._actions: dict[str, _Action] = {}

    def start(self, action: ProposedAction, namespace: str, open_mcp: OpenMcp, requested_by: str,
              tracer: InvestigationTracer) -> ActionState:
        entry = _Action(ActionState(id=uuid4().hex[:ACTION_ID_LENGTH], action=action, namespace=namespace,
                                    status=ActionStatus.STARTING, requested_by=requested_by,
                                    updated_at=datetime.now(timezone.utc)))
        self._actions[entry.state.id] = entry
        entry.task = asyncio.create_task(self._run(entry, open_mcp, tracer))
        return entry.state

    def get(self, action_id: str) -> ActionState:
        return self._entry(action_id).state

    def decide(self, action_id: str, decision: ApprovalDecision, approver: str) -> ActionState:
        entry = self._entry(action_id)
        if entry.state.status != ActionStatus.AWAITING_APPROVAL or entry.decision is None or entry.decision.done():
            raise WrongActionStateError(f"Action {action_id} is {entry.state.status}, not awaiting approval")
        if self._require_second_person and decision.approve and approver == entry.state.requested_by:
            raise SelfApprovalError(f"{approver} started action {action_id}; someone else must approve it")
        entry.decision.set_result((decision, approver))
        entry.update(approval_reason=decision.reason, approved_by=approver)
        return entry.state

    def _entry(self, action_id: str) -> _Action:
        if action_id not in self._actions:
            raise UnknownActionError(f"No action {action_id}")
        return self._actions[action_id]

    async def _run(self, entry: _Action, open_mcp: OpenMcp, tracer: InvestigationTracer) -> None:
        action = entry.state.action
        try:
            with tracer.trace_action(action.describe(), entry.state.requested_by) as trace:
                entry.update(trace_id=trace.trace_id, trace_url=trace.trace_url)
                async with open_mcp(elicitation_callback=self._approval_callback(entry),
                                    scopes=WRITE_SCOPES) as mcp_client:
                    result = await mcp_client.call_tool(action.operation, action.tool_arguments(entry.state.namespace))
                trace.record_outcome(extract_result_text(result), {"approved_by": entry.state.approved_by})
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
                decision, approver = await asyncio.wait_for(entry.decision, self._approval_timeout)
            except TimeoutError:
                entry.update(error=f"No approval within {self._approval_timeout:.0f}s")
                return ElicitResult(action="cancel")
            return ElicitResult(action="accept", content={"approve": decision.approve, "reason": decision.reason,
                                                          "approver": approver})

        return ask_human
