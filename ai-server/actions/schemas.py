from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from actions.constants import ActionStatus
from investigation.models import ProposedAction


class ActionRequest(BaseModel):
    action: ProposedAction
    namespace: str | None = Field(default=None, description="Defaults to the configured namespace")


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
