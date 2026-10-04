"""Sign-in (API keys) and MCP token values (Phases 19, 22)."""

from enum import StrEnum


class McpScope(StrEnum):
    """Scopes of the MCP servers' bearer tokens. Investigations only read; actions
    (POST /actions) may also write."""

    READ = "k8s:read"
    WRITE = "k8s:write"


READ_SCOPES = (McpScope.READ,)
WRITE_SCOPES = (McpScope.READ, McpScope.WRITE)
MCP_TOKEN_ALGORITHM = "RS256"
# The agent named in the MCP tokens (`client_id`), and the person it acts for when
# nobody signed in (no API keys configured) or for its own checks (/ready).
AGENT_CLIENT_ID = "oncall-ai-server"
ANONYMOUS_USER = "anonymous"
API_KEY_HEADER = "X-API-Key"
