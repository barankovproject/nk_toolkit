from __future__ import annotations

import datetime
import glob
import os
import time

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")


def trim_logs(log_dir: str, prefix: str, keep: int = 10) -> None:
    """Delete oldest log files. keep=0 deletes all; keep>0 keeps the newest N."""
    files = sorted(glob.glob(os.path.join(log_dir, f"{prefix}_*.log")))
    to_delete = files if keep == 0 else files[:-keep]
    for f in to_delete:
        try:
            os.remove(f)
        except OSError:
            pass


class Logger:
    """Timestamped file logger; callable as log(msg) or log(msg, level)."""

    def __init__(self, keep: int = 10) -> None:
        os.makedirs(LOG_DIR, exist_ok=True)
        if keep > 0:
            trim_logs(LOG_DIR, "canal", keep)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = os.path.join(LOG_DIR, f"canal_{ts}.log")
        self._start = time.time()

    def __call__(self, msg: str, level: str = "INFO") -> None:
        """Append one line to the log file with timestamp and elapsed time."""
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        elapsed = time.time() - self._start
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [{elapsed:6.2f}s] [{level}] {msg}\n")

    def mark_errors(self, n: int) -> None:
        """Rename log file to append _ERR{n} so failures are visible in the file listing."""
        new_path = self.path.replace(".log", f"_ERR{n}.log")
        try:
            os.rename(self.path, new_path)
            self.path = new_path
        except OSError:
            pass
