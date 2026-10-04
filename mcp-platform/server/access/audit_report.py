"""Answers "who changed what, and who approved it?" from the audit log.

    python -m access.audit_report                      # changes and refusals, newest last
    python -m access.audit_report --deployment payment-service --since-hours 24
    python -m access.audit_report --all                # read-only tool calls too"""

import argparse
from datetime import datetime, timedelta, timezone

from access.audit_log import AuditLog
from access.constants import AuditEvent
from config import get_settings
from k8s.constants import WRITE_TOOLS


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--deployment", help="only calls on this deployment")
    parser.add_argument("--user", help="only calls requested by this person")
    parser.add_argument("--since-hours", type=float, help="only the last N hours")
    parser.add_argument("--all", action="store_true", help="include read-only tool calls")
    return parser.parse_args()


def is_selected(record: dict, options: argparse.Namespace) -> bool:
    if record["event"] in (AuditEvent.APPROVAL_REQUESTED, AuditEvent.SAMPLING_REQUESTED):
        return False
    if not options.all and record["tool"] not in WRITE_TOOLS and record["event"] != AuditEvent.REFUSED:
        return False
    if options.deployment and (record.get("arguments") or {}).get("name") != options.deployment:
        return False
    if options.user and record["user"] != options.user:
        return False
    if options.since_hours is not None:
        since = datetime.now(timezone.utc) - timedelta(hours=options.since_hours)
        return datetime.fromisoformat(record["time"]) >= since
    return True


def describe(record: dict, trace_url_template: str | None) -> str:
    arguments = ", ".join(f"{key}={value}" for key, value in (record.get("arguments") or {}).items())
    line = f"{record['time'][:19]}  {record['user']} via {record['client']}: {record['tool']}({arguments})"
    if record["event"] == AuditEvent.REFUSED or record["outcome"] != "ok":
        line += f"\n    {record['outcome'].upper()}: {record.get('error')}"
    elif record["tool"] in WRITE_TOOLS:
        line += (f"\n    {'DONE' if record.get('done') else 'NOT DONE'}, {record.get('approval')} by "
                 f"{record.get('approved_by') or '-'} ({record.get('approval_reason') or 'no reason'}): "
                 f"{record.get('detail')}")
    if trace_id := record.get("trace_id"):
        link = trace_url_template.format(trace_id=trace_id) if trace_url_template else trace_id
        line += f"\n    trace: {link}"
    return line


def main() -> None:
    options, settings = parse_arguments(), get_settings()
    logs = (settings.k8s_server.audit_log_path, settings.prometheus_server.audit_log_path)
    records = sorted((r for path in logs for r in AuditLog(path).read() if is_selected(r, options)), key=lambda r: r["time"])
    print("\n".join(describe(r, settings.trace_url_template) for r in records) or "No matching audit records.")


if __name__ == "__main__":
    main()
