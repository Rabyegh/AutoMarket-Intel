"""Append-only JSONL run log that tracks pipeline step results."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class RunLog:
    """Append-only JSONL run log with resume-support."""

    def __init__(self, path: Path, run_id: str) -> None:
        self._path = path
        self._run_id = run_id
        path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        step: str,
        status: str,
        counts: dict[str, int] | None = None,
        duration_s: float | None = None,
        error: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        row: dict[str, Any] = {
            "run_id": self._run_id,
            "step": step,
            "status": status,
            "ts": datetime.now(UTC).isoformat(),
        }
        if counts:
            row["counts"] = counts
        if duration_s is not None:
            row["duration_s"] = round(duration_s, 3)
        if error:
            row["error"] = error
        if extra:
            row.update(extra)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")

    def get_completed_steps(self) -> set[str]:
        """Return steps that completed OK (for --resume)."""
        if not self._path.exists():
            return set()
        completed: set[str] = set()
        with self._path.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                    if row.get("run_id") == self._run_id and row.get("status") == "ok":
                        completed.add(row["step"])
                except json.JSONDecodeError:
                    pass
        return completed
