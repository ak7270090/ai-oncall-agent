import logging

import uvicorn
from agent import LLMError
from api import router
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from mcp_client import MCPUnavailableError

from config import get_settings
from constants import LLM_FAILURE_MESSAGE

logger = logging.getLogger(__name__)


def _build_error_handler(status_code: int, public_message: str | None = None):
    async def handle(_: Request, error: Exception) -> JSONResponse:
        logger.error("Request failed: %s", error, exc_info=error)
        return JSONResponse(status_code=status_code, content={"detail": public_message or str(error)})
    return handle


def create_app() -> FastAPI:
    app = FastAPI(title=get_settings().app_title)
    app.include_router(router)
    app.add_exception_handler(MCPUnavailableError, _build_error_handler(status.HTTP_503_SERVICE_UNAVAILABLE))
    app.add_exception_handler(LLMError, _build_error_handler(status.HTTP_502_BAD_GATEWAY, LLM_FAILURE_MESSAGE))
    return app


app = create_app()


if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(app, host=settings.server_host, port=settings.server_port)
