from datetime import datetime

from pydantic import BaseModel, Field, model_validator


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
    latest: float | None = Field(default=None, description="Most recent value: is the problem still happening now?")
    min: float | None = None
    max: float | None = Field(
        default=None, description="Peak over the window; compare with `latest` to tell a past spike from an ongoing problem")

    @model_validator(mode="after")
    def summarize(self) -> "MetricSeries":
        values = [s.value for s in self.samples if s.value is not None]
        self.latest = values[-1] if values else None
        self.min = min(values, default=None)
        self.max = max(values, default=None)
        return self


class ServiceHealth(BaseModel):
    service: str
    request_rate_per_second: float | None = None
    error_rate: float | None = None
    latency_p99_ms: float | None = None


class ServiceOverview(BaseModel):
    namespace: str
    window: str
    services: list[ServiceHealth]
