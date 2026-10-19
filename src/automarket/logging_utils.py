"""Structured JSON logging. Every log line carries run_id and step."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record."""

    def __init__(self, run_id: str = "", step: str = "") -> None:
        super().__init__()
        self._run_id = run_id
        self._step = step

    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "run_id": self._run_id,
            "step": self._step,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload)


_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(JsonFormatter())

logger = logging.getLogger("automarket")
logger.addHandler(_handler)
logger.setLevel(logging.INFO)
logger.propagate = False


def configure(run_id: str, step: str = "") -> None:
    """Bind run_id and step to every subsequent log line."""
    fmt = JsonFormatter(run_id=run_id, step=step)
    for h in logger.handlers:
        h.setFormatter(fmt)
