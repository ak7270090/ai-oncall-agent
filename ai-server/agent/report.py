from agent.models import IncidentReport


def render_markdown(report: IncidentReport) -> str:
    lines = [
        f"**Incident:** {report.incident}",
        f"**Impact:** {report.impact}",
        "",
        "**Evidence:**",
        *(f"- `{e.source}`: {e.finding}" for e in report.evidence),
        "",
        f"**Likely cause** ({report.confidence} confidence): {report.likely_cause}",
        "",
        "**Recommended action:**",
        *(f"- {action}" for action in report.recommended_actions),
    ]
    if report.timeline:
        lines += ["", "**Timeline:**", *(f"- {entry}" for entry in report.timeline)]
    return "\n".join(lines)
