"""How expected failures reach API callers: one table, used by the exception handlers
(main.py) and by the error event of the streaming endpoint."""

import logging
from dataclasses import dataclass

from fastapi import Request, status
from fastapi.responses import JSONResponse

from llm.chat_model import LLMError
from llm.constants import LLM_FAILURE_MESSAGE
from mcp_client.connection import MCPUnavailableError

logger = logging.getLogger(__name__)

UNEXPECTED_FAILURE_MESSAGE = "The investigation failed unexpectedly. See server logs for details."


@dataclass(frozen=True)
class PublicError:
    status_code: int
    message: str | None = None  # None: the error's own message is safe to show


PUBLIC_ERRORS: dict[type[Exception], PublicError] = {
    MCPUnavailableError: PublicError(status.HTTP_503_SERVICE_UNAVAILABLE),
    LLMError: PublicError(status.HTTP_502_BAD_GATEWAY, LLM_FAILURE_MESSAGE),
}


def describe_error(error: Exception) -> tuple[int, str]:
    """Status code and caller-safe message for an error; logs it."""
    logger.error("Request failed: %s", error, exc_info=error)
    public = next((p for kind, p in PUBLIC_ERRORS.items() if isinstance(error, kind)), None)
    if public is None:
        return status.HTTP_500_INTERNAL_SERVER_ERROR, UNEXPECTED_FAILURE_MESSAGE
    return public.status_code, public.message or str(error)


async def handle_public_error(_: Request, error: Exception) -> JSONResponse:
    status_code, detail = describe_error(error)
    return JSONResponse(status_code=status_code, content={"detail": detail})
