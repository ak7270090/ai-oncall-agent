import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from auth.constants import ANONYMOUS_USER, API_KEY_HEADER
from config import SettingsDep

ApiKeyHeader = APIKeyHeader(name=API_KEY_HEADER, auto_error=False, description="Your API key")


def get_current_user(settings: SettingsDep, api_key: Annotated[str | None, Security(ApiKeyHeader)] = None) -> str:
    """The person behind the request, from the X-API-Key header (Phase 19)."""
    if not settings.api_keys:
        return ANONYMOUS_USER
    for known_key, user in settings.api_keys.items():
        if api_key and secrets.compare_digest(api_key.encode(), known_key.encode()):
            return user
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Missing or unknown API key ({API_KEY_HEADER} header)")


CurrentUserDep = Annotated[str, Depends(get_current_user)]
