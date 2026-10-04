"""Bearer tokens (Phase 19): short-lived JWTs that the AI server signs for its signed-in
user. `sub` is the person, `client_id` the agent acting for them, `scope` what the token
allows (k8s:read, k8s:write). The SDK calls `verify_token` on every HTTP request and
answers 401 when it returns None.

Tokens are signed with the AI server's private key (RS256, Phase 22); this server only
holds the public keys (a JWKS file), so it can check tokens but never mint them."""

import json
import logging
from pathlib import Path

import jwt
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings

from auth.config import AccessSettings
from auth.constants import TOKEN_ALGORITHM, TOKEN_REQUIRED_CLAIMS, Scope

logger = logging.getLogger(__name__)


class SignedTokenVerifier:
    def __init__(self, jwks_path: Path, issuer: str, audience: str):
        self._keys = jwt.PyJWKSet.from_dict(json.loads(jwks_path.read_text(encoding="utf-8")))
        self._issuer = issuer
        self._audience = audience

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            signing_key = self._keys[jwt.get_unverified_header(token).get("kid", "")]
            claims = jwt.decode(token, signing_key, algorithms=[TOKEN_ALGORITHM], issuer=self._issuer,
                                audience=self._audience, options={"require": list(TOKEN_REQUIRED_CLAIMS)})
        except (jwt.InvalidTokenError, KeyError) as error:
            logger.info("Rejected bearer token: %s", error)
            return None
        return AccessToken(token=token, client_id=claims.get("client_id", claims["sub"]),
                           scopes=claims["scope"].split(), expires_at=claims["exp"], subject=claims["sub"],
                           claims=claims)


def build_token_auth(settings: AccessSettings, public_url: str) -> dict:
    """MCPServer arguments for bearer-token authentication: every HTTP request needs a
    valid token with scope k8s:read, else 401 pointing to the protected resource metadata
    (/.well-known/oauth-protected-resource/mcp). Empty without MCP_AUTH_JWKS_PATH."""
    if not settings.auth_jwks_path:
        logger.warning("MCP_AUTH_JWKS_PATH is not set: no authentication, anyone who reaches the port may call the tools")
        return {}
    return {
        "token_verifier": SignedTokenVerifier(settings.auth_jwks_path, settings.auth_issuer_url,
                                              settings.auth_audience),
        "auth": AuthSettings(issuer_url=settings.auth_issuer_url, resource_server_url=public_url,
                             required_scopes=[Scope.READ],
                             validate_token_resource=False),  # SignedTokenVerifier checks the audience
    }
