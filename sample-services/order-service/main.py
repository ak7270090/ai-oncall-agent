import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import uuid4

import httpx2
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, status
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel, Field

from settings import get_settings


class OrderRequest(BaseModel):
    user_id: int
    amount: float = Field(gt=0)


class Order(BaseModel):
    order_id: str
    user_id: int
    amount: float
    payment_id: str
    status: str


settings = get_settings()
# uvicorn's configured logger, so messages appear in the pod log next to access logs.
logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with httpx2.AsyncClient(timeout=settings.downstream_timeout_seconds) as http_client:
        app.state.http_client = http_client
        yield


app = FastAPI(title=settings.service_name, version=settings.app_version, lifespan=lifespan)


class ProbeAccessLogFilter(logging.Filter):
    """Keep kubelet probes and Prometheus scrapes out of the access log so real traffic stays visible."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not any(path in record.getMessage() for path in (" /health ", " /metrics "))


logging.getLogger("uvicorn.access").addFilter(ProbeAccessLogFilter())

# The library's default labelled-latency buckets stop at 1s, which caps p99 at 1000 ms.
LATENCY_BUCKETS_SECONDS = (0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5, 10)
Instrumentator(excluded_handlers=["/health", "/metrics"]).instrument(
    app, latency_lowr_buckets=LATENCY_BUCKETS_SECONDS
).expose(app, include_in_schema=False)


def get_http_client(request: Request) -> httpx2.AsyncClient:
    return request.app.state.http_client


HttpClientDep = Annotated[httpx2.AsyncClient, Depends(get_http_client)]


def build_upstream_failure(message: str) -> HTTPException:
    logger.error(message)
    return HTTPException(status.HTTP_502_BAD_GATEWAY, message)


async def call_downstream(http_client: httpx2.AsyncClient, method: str, url: str, **kwargs) -> dict:
    started = time.monotonic()
    try:
        response = await http_client.request(method, url, **kwargs)
    except httpx2.HTTPError as error:
        raise build_upstream_failure(f"upstream unavailable: {method} {url} ({error!r})")
    elapsed = time.monotonic() - started
    if elapsed >= settings.slow_call_warning_seconds:
        logger.warning(f"slow upstream call: {method} {url} took {elapsed:.2f}s")
    if response.status_code == status.HTTP_404_NOT_FOUND:
        raise HTTPException(status.HTTP_404_NOT_FOUND, response.json().get("detail", "not found"))
    if response.is_error:
        raise build_upstream_failure(f"upstream error {response.status_code}: {method} {url}")
    return response.json()


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": settings.service_name, "version": settings.app_version}


@app.post("/orders", response_model=Order, status_code=status.HTTP_201_CREATED)
async def create_order(request: OrderRequest, http_client: HttpClientDep) -> Order:
    await call_downstream(http_client, "GET", f"{settings.user_service_url}/users/{request.user_id}")
    order_id = str(uuid4())
    payment = await call_downstream(
        http_client,
        "POST",
        f"{settings.payment_service_url}/payments",
        json={"order_id": order_id, "amount": request.amount},
    )
    return Order(
        order_id=order_id,
        user_id=request.user_id,
        amount=request.amount,
        payment_id=payment["payment_id"],
        status="confirmed",
    )


if __name__ == "__main__":
    uvicorn.run(app, host=settings.server_host, port=settings.server_port)
