import hashlib
import logging
import time

import uvicorn
from fastapi import FastAPI, HTTPException, status
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel

from settings import get_settings


class User(BaseModel):
    id: int
    name: str
    email: str


USERS = {
    user.id: user
    for user in (
        User(id=1, name="Asha Rao", email="asha@example.com"),
        User(id=2, name="Ben Ortiz", email="ben@example.com"),
        User(id=3, name="Chen Li", email="chen@example.com"),
    )
}

settings = get_settings()
app = FastAPI(title=settings.service_name, version=settings.app_version)


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


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": settings.service_name, "version": settings.app_version}


def burn_cpu(milliseconds: int) -> None:
    """Phase 9 high-CPU scenario: hash in a loop until this much CPU time is used."""
    deadline = time.process_time() + milliseconds / 1000
    digest = b"seed"
    while time.process_time() < deadline:
        digest = hashlib.sha256(digest).digest()


# Sync endpoint: CPU work runs in a worker thread, so /health keeps answering.
@app.get("/users/{user_id}", response_model=User)
def get_user(user_id: int) -> User:
    if settings.fault_mode == "cpu":
        burn_cpu(settings.fault_cpu_milliseconds)
    if user_id not in USERS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"user {user_id} not found")
    return USERS[user_id]


if __name__ == "__main__":
    uvicorn.run(app, host=settings.server_host, port=settings.server_port)
