"""Prompt texts for the three LLM steps, and the functions that build each step's messages."""

import json
from datetime import datetime, timezone

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from agent.models import Evidence, IncidentScope

SCOPE_PROMPT = """\
You triage incident reports for an on-call engineer. Extract the scope of the
investigation from the report. Only name a service if the report clearly refers to
it; product words like "checkout" are not service names. Use a 15 minute window
unless the report says otherwise.
"""

ROOT_CAUSE_PROMPT = """\
You are an on-call engineer investigating a production incident. Evidence has
already been gathered automatically from Kubernetes and Prometheus; it is below as
JSON, one item per tool call (errors included).

Work out the most likely root cause:
- Follow the dependency chain: a service returning errors is often a victim of a
  dependency it calls. Logs naming a failing upstream are strong evidence.
- Distinguish symptoms from causes, and current problems from old or routine events
  (e.g. probe failures while pods were starting).
- "Computed findings" are facts derived by code from the evidence; don't contradict them.
- Evidence from `topology` (who calls whom) and `runbook` (per service) is the team's
  documented knowledge: use it to interpret the live evidence; when they disagree, the
  live evidence wins.
- Explain what is happening NOW. Compare log and event timestamps with the current
  time, and a metric's `latest` value with its `max`: errors that stopped minutes ago
  belong to an earlier, resolved problem and are not the cause of the current one.
- Check timing: did an error-rate increase coincide with a rollout or scaling change?

If a specific piece of evidence is missing and would change your conclusion, call a
tool to get it. Otherwise answer without tools. State your conclusion, the evidence
for and against it, and your confidence. All tools are read-only.
"""

REPORT_PROMPT = """\
Write the final incident report from the investigation below. Every evidence item
must cite the tool it came from and quote concrete values or log lines. Do not claim
anything the evidence does not show. Recommended actions are for a human to take.

Classify the ROOT cause (not the symptom) with cause_category, by HOW the root-cause
service is failing right now (the mechanism), not by what change preceded it:
- crash_loop: its containers keep crashing/restarting (startup failure, missing config, OOM)
- resource_exhaustion: it is held at a CPU or memory limit (high cpu_throttled_ratio, OOM kills)
- dependency_unavailable: it is down, has no ready pods, or refuses connections
- slow_dependency: it answers, but too slowly (high latency, few or no errors), without
  being CPU/memory limited
- bad_deployment: it runs and is reachable, but returns errors since a new version or
  image was rolled out while the previous revision worked, and no mechanism above fits
- no_incident: the evidence shows everything healthy
- other: none of the above
Check them in that order and pick the first that fits. A rollout often precedes any of
them (config changes restart pods too); mention it in likely_cause, but it does not make
the category bad_deployment.
root_cause_service is where the fix belongs (e.g. the database, not the services failing because of it).
"""


def evidence_as_json(evidence: list[Evidence]) -> str:
    return json.dumps([e.model_dump(exclude_none=True) for e in evidence], default=str, separators=(",", ":"))


def scope_messages(question: str) -> list[BaseMessage]:
    return [SystemMessage(SCOPE_PROMPT), HumanMessage(question)]


def _findings_line(findings: list[str]) -> str:
    return "Computed findings: " + (" ".join(findings) if findings else "none")


def root_cause_messages(question: str, scope: IncidentScope, namespace: str, evidence: list[Evidence],
                        findings: list[str]) -> list[BaseMessage]:
    return [
        SystemMessage(ROOT_CAUSE_PROMPT),
        HumanMessage("\n".join([
            f"Current time (UTC): {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
            f"Incident report: {question}",
            f"Understood scope: {scope.model_dump_json()}",
            f"Namespace: {namespace}",
            _findings_line(findings),
            f"Evidence: {evidence_as_json(evidence)}",
        ])),
    ]


def report_messages(question: str, evidence: list[Evidence], notes: list[str], analysis: str,
                    findings: list[str]) -> list[BaseMessage]:
    return [
        SystemMessage(REPORT_PROMPT),
        HumanMessage("\n".join([
            f"Incident report: {question}",
            f"Evidence: {evidence_as_json(evidence)}",
            f"Investigation notes: {'; '.join(notes) or 'none'}",
            _findings_line(findings),
            f"Analysis: {analysis or '(no analysis produced)'}",
        ])),
    ]
