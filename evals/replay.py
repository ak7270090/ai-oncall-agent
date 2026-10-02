"""Re-runs only the LLM reasoning (find_root_cause + write_report) on evidence saved by an eval run,
so prompt changes can be checked in seconds instead of re-injecting incidents.

Run with `make replay [RUN=evals/results/<file>.json] [NAME=a,b] [TIMES=n]`: it uses the
ai-server virtualenv and settings (LLM_MODEL / LLM_API_KEY from ai-server/.env).
Evidence gathering is not replayed, so this checks reasoning, not which tools ran.
With Langfuse keys, each replay round is recorded as an experiment run
(see experiment_tracking.py).
"""

import argparse
import asyncio
import json
import sys
import threading
from pathlib import Path

EVALS_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EVALS_DIR / "results"
sys.path.insert(0, str(EVALS_DIR.parent / "ai-server"))

from experiment_tracking import (  # noqa: E402
    ExperimentTracker,
    current_traceparent,
    normalized_service,
    use_safe_event_loop,
)
from incident_cases import INCIDENT_CASES, IncidentCase  # noqa: E402

from agent import Evidence, IncidentScope, create_model_router  # noqa: E402
from agent.investigation import reanalyze_evidence  # noqa: E402
from config import get_settings  # noqa: E402
from tracing import InvestigationTracer, TraceLabels, create_tracer  # noqa: E402

INCIDENT_CASES_BY_NAME = {s.name: s for s in INCIDENT_CASES}


def latest_run_with_evidence() -> Path:
    runs = sorted(RESULTS_DIR.glob("*.json"), reverse=True)
    for run in runs:
        if any(r.get("response") for r in json.loads(run.read_text())):
            return run
    raise SystemExit("no eval run with saved evidence; run `make eval` first")


class ReasoningLoop:
    """One event loop, on a background thread, for every LLM call of the replay.

    Langfuse runs each experiment item in its own short-lived event loop, but LLM provider
    clients share async HTTP connections that must stay on the loop that opened them."""

    def __init__(self):
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_forever, daemon=True).start()
        self.models = create_model_router(get_settings())

    async def run(self, coroutine) -> dict:
        return await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(coroutine, self._loop))

    def close(self) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)


async def reanalyze(reasoning: ReasoningLoop, incident: IncidentCase, response: dict,
                    tracer: InvestigationTracer, tracker: ExperimentTracker, traceparent: str | None) -> dict:
    evidence = [Evidence(**{k: e.get(k) for k in ("step", "source", "arguments", "error", "result")})
                for e in response["evidence"]]
    result = await reanalyze_evidence(
        reasoning.models, incident.question, IncidentScope(**response["scope"]), response["namespace"],
        evidence, response["notes"], tracer, TraceLabels(tuple(tracker.trace_tags(incident)), traceparent),
    )
    return {"report": result.report.model_dump()}


async def replay_once(reasoning: ReasoningLoop, incident: IncidentCase, response: dict,
                      tracer: InvestigationTracer, tracker: ExperimentTracker) -> dict:
    # Read here, in the experiment item's context: the reasoning loop's thread has no
    # current span, so the trace parent is passed explicitly.
    traceparent = current_traceparent()
    return await reasoning.run(reanalyze(reasoning, incident, response, tracer, tracker, traceparent))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, help="eval results file (default: latest with evidence)")
    parser.add_argument("--only", help="comma-separated incident names")
    parser.add_argument("--times", type=int, default=1, help="replays per incident (LLM answers vary)")
    args = parser.parse_args()

    run = args.run or latest_run_with_evidence()
    entries = [r for r in json.loads(run.read_text())
               if r.get("response") and (not args.only or r["incident"] in args.only.split(","))]
    print(f"replaying {len(entries)} incident(s) from {run.name}, {args.times}x each")
    tracer = create_tracer(get_settings())
    tracker = ExperimentTracker("replay")
    tracker.register_cases([INCIDENT_CASES_BY_NAME[entry["incident"]] for entry in entries])
    reasoning = ReasoningLoop()
    total = passed = 0
    for attempt in range(1, args.times + 1):
        for entry in entries:
            incident = INCIDENT_CASES_BY_NAME[entry["incident"]]
            output = tracker.run_case(
                incident, lambda: replay_once(reasoning, incident, entry["response"], tracer, tracker),
                run_suffix=f" #{attempt}" if args.times > 1 else "",
            )
            report = output["report"]
            category, service = report["cause_category"], normalized_service(report)
            expected = (incident.expected_category, incident.expected_service)
            ok = (category, service) == expected
            total, passed = total + 1, passed + ok
            print(f"{entry['incident']:15} #{attempt} {'PASS' if ok else 'FAIL'}  {category} / {service}"
                  f"{'' if ok else f'   (expected {expected[0]} / {expected[1]})'}")
            if not ok:
                print(f"{'':19}{report['likely_cause'][:220]}")
    print(f"\n{passed}/{total} passed")
    tracker.flush()
    tracer.shutdown()


if __name__ == "__main__":
    use_safe_event_loop()
    main()
