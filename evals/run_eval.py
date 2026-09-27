"""Runs each incident scenario against the live stack and grades the agent's report.

Needs: kind cluster up (`make cluster-up`), MCP server and AI server running.
For every scenario: inject -> wait for the symptom -> POST /investigate -> grade -> reset
-> wait until healthy. Results are printed and saved to evals/results/<timestamp>.json.
Standard library only, so it runs with any Python 3.11+.
"""

import argparse
import json
import os
import subprocess
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from scenarios import HEALTHY, SCENARIOS, PodCondition, PromCondition, Scenario

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = Path(__file__).resolve().parent / "results"
AI_SERVER_URL = os.environ.get("EVAL_AI_SERVER_URL", "http://127.0.0.1:8000")
PROMETHEUS_URL = os.environ.get("EVAL_PROMETHEUS_URL", "http://127.0.0.1:9090")
NAMESPACE = os.environ.get("EVAL_NAMESPACE", "shop")
SYMPTOM_TIMEOUT_SECONDS = 300
HEALTHY_TIMEOUT_SECONDS = 420
INVESTIGATE_TIMEOUT_SECONDS = 600
POLL_SECONDS = 5


@dataclass
class Result:
    scenario: str
    passed: bool
    expected: str
    got: str
    confidence: str | None
    llm_calls: int | None
    checks: int | None
    seconds: float
    likely_cause: str
    error: str | None = None


def kubectl(*args: str) -> str:
    return subprocess.run(["kubectl", *args], check=True, capture_output=True, text=True).stdout


def http_json(url: str, body: dict | None = None, timeout: float = 30) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, headers={"content-type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def prometheus_value(query: str) -> float | None:
    url = f"{PROMETHEUS_URL}/api/v1/query?{urllib.parse.urlencode({'query': query})}"
    result = http_json(url)["data"]["result"]
    return float(result[0]["value"][1]) if result else None


def holds(condition: PromCondition | PodCondition) -> bool:
    if isinstance(condition, PromCondition):
        value = prometheus_value(condition.query)
        return value is not None and value > condition.above
    pods = json.loads(kubectl("get", "pods", "-n", NAMESPACE, "-l", f"app={condition.app}", "-o", "json"))["items"]
    restarts = [sum(c.get("restartCount", 0) for c in p["status"].get("containerStatuses", [])) for p in pods]
    return any(r >= condition.min_restarts for r in restarts)


def wait_until(check, timeout: float, what: str) -> None:
    deadline = time.monotonic() + timeout
    while not check():
        if time.monotonic() > deadline:
            raise TimeoutError(f"timed out after {timeout:.0f}s waiting for {what}")
        time.sleep(POLL_SECONDS)


def reset_and_wait_healthy() -> None:
    kubectl("apply", "-k", str(REPO_ROOT / "kubernetes" / "base"))
    kubectl("wait", "deployment", "--all", "-n", NAMESPACE, "--for=condition=Available", "--timeout=300s")
    wait_until(lambda: all(holds(c) for c in HEALTHY), HEALTHY_TIMEOUT_SECONDS, "a healthy cluster")


def grade(scenario: Scenario, report: dict) -> tuple[bool, str]:
    category = report.get("cause_category")
    service = (report.get("root_cause_service") or "").strip().lower()
    passed = category == scenario.expected_category and service == scenario.expected_service
    return passed, f"{category} / {service or '-'}"


def run_scenario(scenario: Scenario) -> Result:
    expected = f"{scenario.expected_category} / {scenario.expected_service}"
    started = time.monotonic()
    try:
        kubectl("apply", "-k", str(REPO_ROOT / "kubernetes" / "scenarios" / scenario.name))
        wait_until(lambda: holds(scenario.symptom), SYMPTOM_TIMEOUT_SECONDS, f"{scenario.name} symptom")
        started = time.monotonic()
        body = http_json(f"{AI_SERVER_URL}/investigate", {"question": scenario.question}, INVESTIGATE_TIMEOUT_SECONDS)
        report = body["report"]
        passed, got = grade(scenario, report)
        return Result(scenario.name, passed, expected, got, report.get("confidence"), body.get("llm_calls"),
                      len(body.get("evidence", [])), round(time.monotonic() - started, 1), report.get("likely_cause", ""))
    except Exception as error:
        return Result(scenario.name, False, expected, "-", None, None, None,
                      round(time.monotonic() - started, 1), "", error=repr(error))


def print_table(results: list[Result]) -> None:
    print(f"\n{'scenario':15} {'result':6} {'expected':40} {'got':40} {'conf':6} {'llm':>3} {'checks':>6} {'secs':>6}")
    for r in results:
        print(f"{r.scenario:15} {'PASS' if r.passed else 'FAIL':6} {r.expected:40} {r.got:40} "
              f"{r.confidence or '-':6} {r.llm_calls or '-':>3} {r.checks or '-':>6} {r.seconds:>6}")
        if r.error:
            print(f"{'':15} error: {r.error}")
    print(f"\n{sum(r.passed for r in results)}/{len(results)} passed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="comma-separated scenario names")
    args = parser.parse_args()
    selected = [s for s in SCENARIOS if not args.only or s.name in args.only.split(",")]
    if not selected:
        raise SystemExit(f"no such scenario; choose from: {', '.join(s.name for s in SCENARIOS)}")

    http_json(f"{AI_SERVER_URL}/ready")
    print("Preparing a healthy cluster...", flush=True)
    reset_and_wait_healthy()
    results = []
    for scenario in selected:
        print(f"== {scenario.name}", flush=True)
        results.append(run_scenario(scenario))
        print(f"   {'PASS' if results[-1].passed else 'FAIL'}: {results[-1].got}", flush=True)
        try:
            reset_and_wait_healthy()
        except Exception as error:
            # An unrecovered cluster would poison every later scenario: stop, keep what we have.
            print(f"   cluster did not recover after {scenario.name}: {error!r}; stopping", flush=True)
            break
    print_table(results)

    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps([asdict(r) for r in results], indent=2))
    print(f"saved {path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
