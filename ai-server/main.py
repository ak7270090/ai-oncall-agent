from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from api import action_router, router
from api.errors import PUBLIC_ERRORS, handle_public_error
from config import get_settings
from tracing import shutdown_tracers


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    shutdown_tracers()  # send spans still buffered


def create_app() -> FastAPI:
    app = FastAPI(title=get_settings().app_title, lifespan=lifespan)
    app.include_router(router)
    app.include_router(action_router)
    for error_type in PUBLIC_ERRORS:
        app.add_exception_handler(error_type, handle_public_error)
    return app


app = create_app()


if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(app, host=settings.server_host, port=settings.server_port)
