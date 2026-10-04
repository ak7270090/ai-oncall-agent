from pathlib import Path

from pydantic import field_validator

from config import McpSettings


class AccessSettings(McpSettings):
    # Authentication (Phases 19, 22): bearer tokens are JWTs the AI server signs (RS256) for
    # its signed-in user; checked with the public keys in this JWKS file (`make mcp-keys`).
    # The gateway checks them first; the servers check again, since they learn the person
    # from the token. Empty = no authentication (tests, in-process only).
    auth_jwks_path: Path | None = None
    # Must match the tokens' `iss` and `aud` claims. The issuer is published as the
    # servers' authorization server (OAuth protected resource metadata).
    auth_issuer_url: str = "http://127.0.0.1:8000"
    auth_audience: str = "oncall-mcp-server"

    # Authorization (Phase 20): each user's role, and the write tools each role may call
    # and approve. Every known role may call the read-only tools; unknown users nothing.
    user_roles: dict[str, str] = {}
    role_write_tools: dict[str, list[str]] = {
        "developer": [],
        "oncall": ["restart_deployment", "scale_deployment"],
        "lead": ["restart_deployment", "scale_deployment", "rollback_deployment"],
    }

    @field_validator("auth_jwks_path", mode="before")
    @classmethod
    def treat_empty_as_unset(cls, value):
        return value or None
