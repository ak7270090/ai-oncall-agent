from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import uuid4

import httpx2
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, status
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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with httpx2.AsyncClient(timeout=settings.downstream_timeout_seconds) as http_client:
        app.state.http_client = http_client
        yield


app = FastAPI(title=settings.service_name, version=settings.app_version, lifespan=lifespan)


def get_http_client(request: Request) -> httpx2.AsyncClient:
    return request.app.state.http_client


HttpClientDep = Annotated[httpx2.AsyncClient, Depends(get_http_client)]


async def call_downstream(http_client: httpx2.AsyncClient, method: str, url: str, **kwargs) -> dict:
    try:
        response = await http_client.request(method, url, **kwargs)
    except httpx2.HTTPError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"upstream unavailable: {url} ({error!r})")
    if response.status_code == status.HTTP_404_NOT_FOUND:
        raise HTTPException(status.HTTP_404_NOT_FOUND, response.json().get("detail", "not found"))
    if response.is_error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"upstream error {response.status_code}: {url}")
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
