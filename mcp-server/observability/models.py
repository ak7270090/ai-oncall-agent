from datetime import datetime

from pydantic import BaseModel


class MetricSample(BaseModel):
    time: datetime
    value: float | None


class MetricSeries(BaseModel):
    namespace: str
    service: str
    metric: str
    unit: str
    step_seconds: int
    samples: list[MetricSample]


class ServiceHealth(BaseModel):
    service: str
    request_rate_per_second: float | None = None
    error_rate: float | None = None
    latency_p99_ms: float | None = None


class ServiceOverview(BaseModel):
    namespace: str
    window: str
    services: list[ServiceHealth]
