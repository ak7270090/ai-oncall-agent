"""Fixed values of tokens, roles and the audit log (Phases 19-20, 22)."""

from enum import StrEnum


class Scope(StrEnum):
    """OAuth scopes of the bearer tokens. The gateway decides which tools a scope may reach;
    the servers only require k8s:read on every request."""

    READ = "k8s:read"
    WRITE = "k8s:write"


# Tokens are signed by the AI server (RS256) and checked with its public key.
TOKEN_ALGORITHM = "RS256"
TOKEN_REQUIRED_CLAIMS = ("exp", "iat", "sub", "iss", "aud", "scope")
# Who calls when there is no token: stdio, in-process, or authentication switched off.
ANONYMOUS_USER = "anonymous"

# JSON-RPC error code of a refused request (the -32000..-32099 range is left to servers).
ACCESS_DENIED_ERROR_CODE = -32003
# Methods of the requests inside an `input_required` result.
ELICITATION_METHOD = "elicitation/create"


class AuditEvent(StrEnum):
    TOOL_CALL = "tool_call"
    APPROVAL_REQUESTED = "approval_requested"   # a write tool asked a human (elicitation)
    SAMPLING_REQUESTED = "sampling_requested"   # a tool asked the client's LLM (log summary)
    REFUSED = "refused"


class AuditOutcome(StrEnum):
    OK = "ok"
    ERROR = "error"
    REFUSED = "refused"
