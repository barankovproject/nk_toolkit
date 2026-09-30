"""TEMP one-shot driver: run both ditch ведомости, then build the Excel workbook.

Why this exists: the two report scripts must run inside Dynamo (they read the open
drawing's property sets), but the Excel merge needs openpyxl, which lives only in the
system Python — not under Dynamo CPython3. So this single Dynamo node:

  1. execs ditch_06_report_cross  -> fresh ditch_volumes_<ts>.csv      (with `zone`)
  2. execs ditch_06_report_long   -> fresh longitudinal_volumes_<ts>.csv (with `zone`)
  3. shells out to the system Python to run ditch_volumes_to_excel.py, which merges
     the two newest CSVs into the arhyz_s2_data repo's data\\reports\\ditch_volumes.xlsx, split by elevation band.

Throwaway: delete automation/scripts/ditch/ditch_99_volumes_to_excel/ once the split Excel
is accepted.
"""

from __future__ import annotations

import os
import subprocess

_SCRIPTS = r"C:\Arhyz\automation\scripts\ditch"
_CROSS = os.path.join(_SCRIPTS, "ditch_06_report_cross", "ditch_06_report_cross.py")
_LONG = os.path.join(_SCRIPTS, "ditch_06_report_long", "ditch_06_report_long.py")
_EXCEL = r"C:\Arhyz\automation\tools\ditch_volumes_to_excel.py"
# System Python (has openpyxl); Dynamo's own interpreter does not.
_PYEXE = r"C:\Users\baran\AppData\Local\Python\pythoncore-3.14-64\python.exe"

_LOG_DIR = os.path.join(_SCRIPTS, "ditch_99_volumes_to_excel", "logs")
os.makedirs(_LOG_DIR, exist_ok=True)
_LOG = os.path.join(_LOG_DIR, "run.log")


def log(msg: object = "") -> None:
    with open(_LOG, "a", encoding="utf-8") as f:
        f.write(str(msg) + "\n")


def _run_report(path: str) -> str:
    """exec a module-level report script in its own __main__ namespace; return its OUT."""
    ns: dict[str, object] = {"__name__": "__main__", "__file__": path}
    with open(path, "r", encoding="utf-8") as f:
        exec(compile(f.read(), path, "exec"), ns)
    return str(ns.get("OUT", ""))


# fresh log each run
open(_LOG, "w", encoding="utf-8").close()
log("=== ditch_99_volumes_to_excel (TEMP) ===")

cross_out = _run_report(_CROSS)
log(f"cross report -> {cross_out}")
long_out = _run_report(_LONG)
log(f"long report  -> {long_out}")

proc = subprocess.run([_PYEXE, _EXCEL], capture_output=True, text=True)
log("\n--- excel build (system python) ---")
log(proc.stdout)
if proc.stderr:
    log("STDERR:\n" + proc.stderr)
log("=== DONE ===")

OUT = (
    proc.stdout.strip() or "(no excel output — see run.log)"
) + f"\ncross: {cross_out}\nlong: {long_out}"
