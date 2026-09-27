from typing import Literal
from uuid import uuid4

import uvicorn
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel, Field

from settings import get_settings


class PaymentRequest(BaseModel):
    order_id: str
    amount: float = Field(gt=0)


class Payment(BaseModel):
    payment_id: str
    order_id: str
    amount: float
    provider: str
    status: Literal["approved"]


settings = get_settings()
app = FastAPI(title=settings.service_name, version=settings.app_version)
Instrumentator(excluded_handlers=["/health", "/metrics"]).instrument(app).expose(app, include_in_schema=False)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": settings.service_name, "version": settings.app_version}


@app.post("/payments", response_model=Payment)
async def create_payment(request: PaymentRequest) -> Payment:
    return Payment(
        payment_id=str(uuid4()),
        order_id=request.order_id,
        amount=request.amount,
        provider=settings.payment_provider,
        status="approved",
    )


if __name__ == "__main__":
    uvicorn.run(app, host=settings.server_host, port=settings.server_port)
