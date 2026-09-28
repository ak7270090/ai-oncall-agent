"""Incident scenarios for the eval: how to recognize the symptom, what to ask the
agent (phrased like a real report, without naming the cause), and the expected answer."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PromCondition:
    """Symptom visible in Prometheus: `query` result compared with `threshold`."""

    query: str
    above: float


@dataclass(frozen=True)
class PodCondition:
    """Symptom visible in pod state: some pod of `app` has at least `min_restarts` restarts."""

    app: str
    min_restarts: int


@dataclass(frozen=True)
class Scenario:
    name: str
    question: str
    expected_category: str
    expected_service: str
    symptom: PromCondition | PodCondition


def _error_rate(service: str) -> str:
    requests = f'http_requests_total{{namespace="shop",service="{service}"'
    return f'(sum(rate({requests},status="5xx"}}[30s])) or vector(0)) / sum(rate({requests}}}[30s]))'


def _p99_ms(service: str) -> str:
    buckets = f'http_request_duration_seconds_bucket{{namespace="shop",service="{service}"}}'
    return f"1000 * histogram_quantile(0.99, sum by (le) (rate({buckets}[30s])))"


SCENARIOS: list[Scenario] = [
    Scenario(
        name="payment-down",
        question="Customers say checkout started failing a few minutes ago. What is wrong?",
        expected_category="dependency_unavailable",
        expected_service="payment-service",
        symptom=PromCondition(_error_rate("order-service"), above=0.5),
    ),
    Scenario(
        name="db-down",
        question="Checkout errors started a few minutes ago. What is going on?",
        expected_category="dependency_unavailable",
        expected_service="payments-db",
        symptom=PromCondition(_error_rate("payment-service"), above=0.5),
    ),
    Scenario(
        name="bad-deploy",
        question="Orders have been failing since the latest release. Please investigate.",
        expected_category="bad_deployment",
        expected_service="payment-service",
        symptom=PromCondition(_error_rate("payment-service"), above=0.5),
    ),
    Scenario(
        name="crash-loop",
        question="Orders are failing. Investigate.",
        expected_category="crash_loop",
        expected_service="payment-service",
        symptom=PodCondition(app="payment-service", min_restarts=2),
    ),
    Scenario(
        name="high-cpu",
        question="Checkout has become very slow. What's wrong?",
        expected_category="resource_exhaustion",
        expected_service="user-service",
        symptom=PromCondition(_p99_ms("user-service"), above=1000),
    ),
    Scenario(
        name="slow-payments",
        question="Placing an order takes several seconds now. Why?",
        expected_category="slow_dependency",
        expected_service="payment-service",
        symptom=PromCondition(_p99_ms("order-service"), above=2000),
    ),
]

# The cluster counts as healthy again (safe to start the next scenario) when all of these hold.
# `bool` makes a comparison return 1/0 instead of filtering, so a healthy 0.0 still counts.
HEALTHY: list[PromCondition] = [
    PromCondition(f"{_error_rate(service)} < bool 0.02", above=0.5) for service in ("order-service", "payment-service")
] + [
    PromCondition(f"{_p99_ms(service)} < bool 500", above=0.5) for service in ("order-service", "user-service")
]
