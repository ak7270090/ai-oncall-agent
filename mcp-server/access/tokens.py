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

from constants import TOKEN_ALGORITHM, TOKEN_REQUIRED_CLAIMS

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
