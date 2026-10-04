"""Fixed values of actions (Phase 18)."""

from enum import StrEnum


class ActionStatus(StrEnum):
    STARTING = "starting"
    AWAITING_APPROVAL = "awaiting_approval"
    DONE = "done"            # approved and made
    NOT_DONE = "not_done"    # rejected, declined or the approval timed out: nothing changed
    FAILED = "failed"        # refused by the MCP server or failed while changing


ACTION_ID_LENGTH = 12
