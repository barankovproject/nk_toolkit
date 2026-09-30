from __future__ import annotations

import os
from typing import Any

from build_canal_model.config import CANALS_DIR
from build_canal_model.logger import LOG_DIR, trim_logs


class AllCanalBuilder:
    """Iterates over every canal config and runs CanalBuilder for each one."""

    def run(self) -> list[str]:
        from build_canal_model.canal_builder import (
            CanalBuilder,
        )  # late import: always gets hot-reloaded class

        names = self._canal_names()
        if not names:
            return [f"No canal configs found in {CANALS_DIR}"]

        # clear previous batch so only current run's logs remain
        trim_logs(LOG_DIR, "canal", keep=0)

        results: list[str] = []
        for name in names:
            try:
                result = CanalBuilder(name, log_keep=0).run()
                if isinstance(result, list):
                    results.append(f"FAIL  {name}: {result[0]}")
                else:
                    results.append(f"OK    {name}: {result} solids")
            except Exception as ex:
                results.append(f"FAIL  {name}: {ex}")

        ok = sum(1 for r in results if r.startswith("OK"))
        fail = len(results) - ok
        results.append(f"--- {ok} OK, {fail} FAILED ---")
        return results

    def _canal_names(self) -> list[str]:
        if not os.path.isdir(CANALS_DIR):
            return []
        return [
            os.path.splitext(f)[0]
            for f in sorted(os.listdir(CANALS_DIR))
            if f.lower().endswith(".json")
        ]
