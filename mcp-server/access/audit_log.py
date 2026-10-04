"""Append-only audit log (Phase 20): one JSON object per line, never rewritten."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AuditLog:
    def __init__(self, path: Path):
        self.path = path

    def record(self, **fields: Any) -> None:
        entry = {"time": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), **fields}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as log:
            log.write(json.dumps(entry, default=str) + "\n")

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as log:
            return [json.loads(line) for line in log if line.strip()]
