from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from actions.router import router as actions_router
from config import get_settings
from errors import PUBLIC_ERRORS, handle_public_error
from health import router as health_router
from investigation.router import router as investigation_router
from tracing import shutdown_tracers


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    shutdown_tracers()  # send spans still buffered


def create_app() -> FastAPI:
    app = FastAPI(title=get_settings().app_title, lifespan=lifespan)
    for router in (health_router, investigation_router, actions_router):
        app.include_router(router)
    for error_type in PUBLIC_ERRORS:
        app.add_exception_handler(error_type, handle_public_error)
    return app


app = create_app()


if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(app, host=settings.server_host, port=settings.server_port)
