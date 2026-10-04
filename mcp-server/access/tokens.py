"""Bearer tokens (Phase 19): short-lived JWTs that the AI server signs for its signed-in
user. `sub` is the person, `client_id` the agent acting for them, `scope` what the token
allows (k8s:read, k8s:write). The SDK calls `verify_token` on every HTTP request and
answers 401 when it returns None."""

import logging

import jwt
from mcp.server.auth.provider import AccessToken

from constants import TOKEN_ALGORITHM, TOKEN_REQUIRED_CLAIMS

logger = logging.getLogger(__name__)


class SignedTokenVerifier:
    def __init__(self, signing_key: str, issuer: str, audience: str):
        self._signing_key = signing_key
        self._issuer = issuer
        self._audience = audience

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            claims = jwt.decode(token, self._signing_key, algorithms=[TOKEN_ALGORITHM], issuer=self._issuer,
                                audience=self._audience, options={"require": list(TOKEN_REQUIRED_CLAIMS)})
        except jwt.InvalidTokenError as error:
            logger.info("Rejected bearer token: %s", error)
            return None
        return AccessToken(token=token, client_id=claims.get("client_id", claims["sub"]),
                           scopes=claims["scope"].split(), expires_at=claims["exp"], subject=claims["sub"],
                           claims=claims)
