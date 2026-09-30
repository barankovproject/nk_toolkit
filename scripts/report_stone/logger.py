from __future__ import annotations

import datetime
import os
from typing import Any

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")


class Logger:
    def __init__(self, keep: int = 10) -> None:
        os.makedirs(_LOG_DIR, exist_ok=True)
        self._path = os.path.join(
            _LOG_DIR,
            f"stone_summary_{datetime.datetime.now():%Y%m%d_%H%M%S}.log",
        )
        self._t0 = datetime.datetime.now()
        self._keep(keep)

    def _keep(self, n: int) -> None:
        logs = sorted(
            [f for f in os.listdir(_LOG_DIR) if f.endswith(".log")],
            reverse=True,
        )
        for old in logs[n:]:
            try:
                os.remove(os.path.join(_LOG_DIR, old))
            except Exception:
                pass

    def __call__(self, msg: str, level: str = "INFO") -> None:
        elapsed = (datetime.datetime.now() - self._t0).total_seconds()
        line = f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] [{elapsed:6.2f}s] [{level:8s}] {msg}"
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
