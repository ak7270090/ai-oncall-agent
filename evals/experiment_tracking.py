"""Records `make eval` and `make replay` runs in Langfuse as experiments, so runs can be
compared side by side there (pass rate, cost, latency, per incident).

- The incident cases are a Langfuse dataset (question + expected cause and service).
- Each eval or replay run is one experiment run, named after the kind of run, the LLM
  model and the git commit.
- Each case runs through Langfuse's experiment runner, which records an experiment item
  trace and scores it: correct, category_correct, service_correct (1/0) and the agent's
  confidence. The investigation itself joins that trace: in-process for replay, and
  through the W3C `traceparent` header for eval (the AI server is another process).

Uses the Langfuse keys from ai-server/.env; without them cases simply run untracked.
A Langfuse failure is printed and never stops the run."""

import asyncio
import inspect
import subprocess
import sys
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from config import Settings, get_settings
from langfuse import Evaluation, Langfuse
from opentelemetry import trace as otel_trace

from incident_cases import IncidentCase

DATASET_NAME = "oncall-incidents"
REPO_ROOT = Path(__file__).resolve().parent.parent

# A case returns (or, if async, resolves to) {"report": {...IncidentReport fields...}, ...};
# the scores read the report.
CaseOutput = dict[str, Any]
CaseRunner = Callable[[], CaseOutput | Awaitable[CaseOutput]]


def use_safe_event_loop() -> None:
    """On Windows, use the selector event loop: the default Proactor loop can crash
    (access violation) at exit when Python collects an HTTP connection the LLM client
    left open after the loop closed."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def _resolve(output: CaseOutput | Awaitable[CaseOutput]) -> CaseOutput:
    return asyncio.run(output) if inspect.isawaitable(output) else output


def _git_commit() -> str:
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, check=True,
                                capture_output=True, text=True).stdout.strip()
        changed = subprocess.run(["git", "diff", "--quiet", "HEAD"], cwd=REPO_ROOT).returncode != 0
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return f"{commit}-dirty" if changed else commit


def describe_model_setup(settings: Settings) -> str:
    """Which models ran, e.g. "openai:gpt-5.4-mini + fast openai:gpt-5.4-nano (write_report, summaries)".
    Read from ai-server/.env, which the eval and the AI server share."""
    if not settings.llm_model_fast:
        return settings.llm_model
    uses = [*settings.fast_model_steps, *(["summaries"] if settings.summarize_logs else [])]
    return f"{settings.llm_model} + fast {settings.llm_model_fast} ({', '.join(uses) or 'sampling'})"


def _dataset_item_id(case: IncidentCase) -> str:
    return f"{DATASET_NAME}-{case.name}"


def normalized_service(report: dict[str, Any]) -> str:
    return (report.get("root_cause_service") or "").strip().lower()


def score_correctness(*, output: dict[str, Any] | None, expected_output: dict[str, str], **_: Any) -> list[Evaluation]:
    if not output:
        return []
    report = output["report"]
    category_correct = report.get("cause_category") == expected_output["cause_category"]
    service_correct = normalized_service(report) == expected_output["root_cause_service"]
    return [
        Evaluation(name="correct", value=float(category_correct and service_correct), data_type="BOOLEAN"),
        Evaluation(name="category_correct", value=float(category_correct), data_type="BOOLEAN"),
        Evaluation(name="service_correct", value=float(service_correct), data_type="BOOLEAN"),
    ]


def proposes_expected_action(report: dict[str, Any], expected: list[str] | None) -> bool | None:
    """Whether the report proposes the expected (operation, deployment); None if none is expected."""
    if not expected:
        return None
    return any([a.get("operation"), a.get("deployment")] == list(expected) for a in report.get("proposed_actions") or [])


def score_action(*, output: dict[str, Any] | None, expected_output: dict[str, Any], **_: Any) -> list[Evaluation]:
    graded = output and proposes_expected_action(output["report"], expected_output.get("action"))
    return [] if graded is None else [Evaluation(name="action_correct", value=float(graded), data_type="BOOLEAN")]


def score_confidence(*, output: dict[str, Any] | None, **_: Any) -> list[Evaluation]:
    confidence = output and output["report"].get("confidence")
    return [Evaluation(name="confidence", value=confidence, data_type="CATEGORICAL")] if confidence else []


def current_traceparent() -> str | None:
    """W3C traceparent of the current span, for nesting a remote call's trace under it."""
    context = otel_trace.get_current_span().get_span_context()
    if not context.is_valid:
        return None
    return f"00-{context.trace_id:032x}-{context.span_id:016x}-{context.trace_flags:02x}"


class ExperimentTracker:
    def __init__(self, kind: str):
        """`kind` is "eval" or "replay"; it starts the run name and tags every trace."""
        settings = get_settings()
        self._kind = kind
        self._llm_model = describe_model_setup(settings)
        self._commit = _git_commit()
        self._started = f"{datetime.now():%Y-%m-%d %H:%M}"
        self._client = None
        self._items = {}
        if settings.langfuse_public_key and settings.langfuse_secret_key:
            self._client = Langfuse(public_key=settings.langfuse_public_key,
                                    secret_key=settings.langfuse_secret_key.get_secret_value(),
                                    base_url=settings.langfuse_base_url,
                                    environment=settings.langfuse_environment)

    @property
    def experiment_name(self) -> str:
        return f"{self._kind}: {self._llm_model} @ {self._commit}"

    def trace_tags(self, case: IncidentCase) -> list[str]:
        return [self._kind, f"incident:{case.name}"]

    def register_cases(self, cases: list[IncidentCase]) -> None:
        """Create or update the dataset items (ids are fixed per case, so this is an upsert)."""
        self._safely("register the incident cases", self._register_cases, cases)

    def run_case(self, case: IncidentCase, run_case: CaseRunner, run_suffix: str = "") -> CaseOutput:
        """Run one case as an item of this run's experiment and return its output.
        Exceptions from `run_case` are re-raised after Langfuse has recorded the item.
        Call it outside any running event loop: the experiment runner starts its own."""
        item = self._items.get(case.name)
        if self._client is None or item is None:
            return _resolve(run_case())
        outcome: dict[str, Any] = {}

        async def task(**_: Any) -> CaseOutput | None:
            try:
                output = run_case()
                outcome["output"] = await output if inspect.isawaitable(output) else output
            except Exception as error:
                outcome["error"] = error
                return None
            return outcome["output"]

        self._safely(f"record {case.name}", lambda: self._client.run_experiment(
            name=self.experiment_name, run_name=f"{self.experiment_name} ({self._started}){run_suffix}",
            description=f"{self._kind} of {self._llm_model} at commit {self._commit}",
            data=[item], task=task, evaluators=[score_correctness, score_confidence, score_action], max_concurrency=1,
            metadata={"kind": self._kind, "llm_model": self._llm_model, "commit": self._commit},
        ))
        if "error" in outcome:
            raise outcome["error"]
        return outcome["output"] if "output" in outcome else _resolve(run_case())

    def flush(self) -> None:
        if self._client is not None:
            self._client.flush()

    def _register_cases(self, cases: list[IncidentCase]) -> None:
        self._client.create_dataset(name=DATASET_NAME, description="Injected incidents and their expected root cause")
        for case in cases:
            self._items[case.name] = self._client.create_dataset_item(
                dataset_name=DATASET_NAME, id=_dataset_item_id(case),
                input={"question": case.question},
                expected_output={"cause_category": case.expected_category, "root_cause_service": case.expected_service,
                                 "action": list(case.expected_action) if case.expected_action else None},
                metadata={"incident": case.name},
            )

    def _safely(self, what: str, action: Callable, *args: Any) -> None:
        if self._client is None:
            return
        try:
            action(*args)
        except Exception as error:
            print(f"   (Langfuse: could not {what}: {error!r})", flush=True)
