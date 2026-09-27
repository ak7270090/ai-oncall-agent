import logging
import time
from functools import lru_cache
from typing import Annotated, Literal
from uuid import uuid4

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, status
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel, Field

from settings import get_settings
from store import DatabaseUnavailable, PaymentStore, PostgresPaymentStore


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
# uvicorn's configured logger, so messages appear in the pod log next to access logs.
logger = logging.getLogger("uvicorn.error")
app = FastAPI(title=settings.service_name, version=settings.app_version)
# The library's default labelled-latency buckets stop at 1s, which caps p99 at 1000 ms.
LATENCY_BUCKETS_SECONDS = (0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5, 10)
Instrumentator(excluded_handlers=["/health", "/metrics"]).instrument(
    app, latency_lowr_buckets=LATENCY_BUCKETS_SECONDS
).expose(app, include_in_schema=False)


@lru_cache
def get_store() -> PaymentStore:
    return PostgresPaymentStore(settings)


def inject_fault() -> None:
    """Phase 9 scenarios: `error` simulates a v2 regression, `latency` a slow dependency."""
    if settings.fault_mode == "latency":
        time.sleep(settings.fault_latency_seconds)
    if settings.fault_mode == "error":
        raise KeyError("currency")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": settings.service_name, "version": settings.app_version}


# Sync endpoint: FastAPI runs it in a worker thread, so blocking DB calls don't stall the event loop.
@app.post("/payments", response_model=Payment)
def create_payment(request: PaymentRequest, store: Annotated[PaymentStore, Depends(get_store)]) -> Payment:
    inject_fault()
    payment = Payment(
        payment_id=str(uuid4()),
        order_id=request.order_id,
        amount=request.amount,
        provider=settings.payment_provider,
        status="approved",
    )
    try:
        store.save(payment.payment_id, payment.order_id, payment.amount, payment.provider)
    except DatabaseUnavailable as error:
        logger.error(str(error))
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error))
    return payment


if __name__ == "__main__":
    uvicorn.run(app, host=settings.server_host, port=settings.server_port)
