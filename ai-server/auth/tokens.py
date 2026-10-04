"""Bearer tokens for the MCP server (Phase 19).

The AI server acts for a signed-in person, so every MCP HTTP request carries a JWT that
says who (`sub`), which agent (`client_id`) and what it may do (`scope`), signed with the
AI server's private key (RS256); the MCP servers and the gateway hold only the public key. A fresh token is minted per request and lives only
seconds, so a stolen one is soon useless, even while an action waits minutes for its
approval."""

import logging
import time
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import httpx2
import jwt

from auth.constants import AGENT_CLIENT_ID, MCP_TOKEN_ALGORITHM
from auth.token_keys import load_private_key

logger = logging.getLogger(__name__)
UNAUTHORIZED = 401


@dataclass(frozen=True)
class McpTokenIssuer:
    private_key: str
    key_id: str
    issuer: str
    audience: str
    ttl_seconds: float

    @classmethod
    def from_key_file(cls, path: Path, issuer: str, audience: str, ttl_seconds: float) -> "McpTokenIssuer":
        private_key, key_id = load_private_key(path)
        return cls(private_key, key_id, issuer, audience, ttl_seconds)

    def mint(self, user: str, scopes: tuple[str, ...]) -> str:
        now = int(time.time())
        claims = {"iss": self.issuer, "aud": self.audience, "sub": user, "client_id": AGENT_CLIENT_ID,
                  "scope": " ".join(scopes), "iat": now, "exp": now + int(self.ttl_seconds), "jti": uuid4().hex}
        return jwt.encode(claims, self.private_key, algorithm=MCP_TOKEN_ALGORITHM, headers={"kid": self.key_id})


class McpTokenAuth(httpx2.Auth):
    """httpx auth flow: adds `Authorization: Bearer <fresh token>` to every request."""

    def __init__(self, issuer: McpTokenIssuer, user: str, scopes: tuple[str, ...]):
        self._issuer = issuer
        self._user = user
        self._scopes = scopes

    def auth_flow(self, request: httpx2.Request) -> Generator[httpx2.Request, httpx2.Response, None]:
        request.headers["Authorization"] = f"Bearer {self._issuer.mint(self._user, self._scopes)}"
        response = yield request
        if response.status_code == UNAUTHORIZED:
            # The MCP client only reports "Server returned an error response".
            logger.warning("The MCP server rejected our token (%s): check that the MCP server's JWKS holds "
                           "our public key (make mcp-keys) and that issuer and audience match", response.headers.get("www-authenticate"))
