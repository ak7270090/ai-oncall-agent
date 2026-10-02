"""Re-runs only the LLM reasoning (find_root_cause + write_report) on evidence saved by an eval run,
so prompt changes can be checked in seconds instead of re-injecting incidents.

Run with `make replay [RUN=evals/results/<file>.json] [NAME=a,b] [TIMES=n]`: it uses the
ai-server virtualenv and settings (LLM_MODEL / LLM_API_KEY from ai-server/.env).
Evidence gathering is not replayed, so this checks reasoning, not which tools ran.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

EVALS_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EVALS_DIR / "results"
sys.path.insert(0, str(EVALS_DIR.parent / "ai-server"))

from incident_cases import INCIDENT_CASES  # noqa: E402

from agent import Evidence, IncidentScope, create_chat_model  # noqa: E402
from agent.investigation import reanalyze_evidence  # noqa: E402
from config import get_settings  # noqa: E402

INCIDENT_CASES_BY_NAME = {s.name: s for s in INCIDENT_CASES}


def latest_run_with_evidence() -> Path:
    runs = sorted(RESULTS_DIR.glob("*.json"), reverse=True)
    for run in runs:
        if any(r.get("response") for r in json.loads(run.read_text())):
            return run
    raise SystemExit("no eval run with saved evidence; run `make eval` first")


async def replay_once(chat_model, question: str, response: dict) -> tuple[str, str, str]:
    evidence = [Evidence(**{k: e.get(k) for k in ("step", "source", "arguments", "error", "result")})
                for e in response["evidence"]]
    _, report = await reanalyze_evidence(
        chat_model, question, IncidentScope(**response["scope"]), response["namespace"],
        evidence, response["notes"],
    )
    return report.cause_category, (report.root_cause_service or "").strip().lower(), report.likely_cause


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, help="eval results file (default: latest with evidence)")
    parser.add_argument("--only", help="comma-separated incident names")
    parser.add_argument("--times", type=int, default=1, help="replays per incident (LLM answers vary)")
    args = parser.parse_args()

    run = args.run or latest_run_with_evidence()
    entries = [r for r in json.loads(run.read_text())
               if r.get("response") and (not args.only or r["incident"] in args.only.split(","))]
    print(f"replaying {len(entries)} incident(s) from {run.name}, {args.times}x each")
    chat_model = create_chat_model(get_settings())
    total = passed = 0
    for entry in entries:
        incident = INCIDENT_CASES_BY_NAME[entry["incident"]]
        expected = (incident.expected_category, incident.expected_service)
        for attempt in range(1, args.times + 1):
            category, service, cause = await replay_once(chat_model, incident.question, entry["response"])
            ok = (category, service) == expected
            total, passed = total + 1, passed + ok
            print(f"{entry['incident']:15} #{attempt} {'PASS' if ok else 'FAIL'}  {category} / {service}"
                  f"{'' if ok else f'   (expected {expected[0]} / {expected[1]})'}")
            if not ok:
                print(f"{'':19}{cause[:220]}")
    print(f"\n{passed}/{total} passed")


if __name__ == "__main__":
    asyncio.run(main())
