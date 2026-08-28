"""Run logging. Every clean writes a JSON record you can review afterwards."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from .cleaner import CleanResult


def log_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    path = Path(base) / "SafeClean" / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write(result: CleanResult) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    kind = "dryrun" if result.dry_run else "clean"
    target = log_dir() / f"{stamp}-{kind}.json"

    payload = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "dry_run": result.dry_run,
        "totals": {
            "freed_bytes": result.freed,
            "files_deleted": result.deleted,
            "files_locked": result.locked,
            "files_refused_by_guard": result.refused,
        },
        "rules": [
            {
                "id": r.rule_id,
                "label": r.label,
                "freed_bytes": r.freed,
                "deleted": r.deleted,
                "locked": r.locked,
                "refused": r.refused,
                "refusals": [{"path": p, "reason": reason} for p, reason in r.refusals],
                "errors": r.errors,
            }
            for r in result.rules
        ],
    }
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return target
