"""Rebuild NK-1E-2 and NK-3A-1 canal models to verify the PI sliver / miter wedge fixes."""

from __future__ import annotations

import datetime
import importlib
import os
import sys
import traceback

import clr

clr.AddReference("AecBaseMgd")
clr.AddReference("AeccDbMgd")
clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

_LIB_ROOT = r"C:\Arhyz\automation\scripts"
_AUTOMATION_ROOT = os.path.dirname(_LIB_ROOT)
for _p in (_LIB_ROOT, _AUTOMATION_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\run_canal_rebuild\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"run_canal_rebuild_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


# hot-reload (same ordering as build_canal_model launcher)
def _reload_key(n: str) -> tuple[int, str]:
    parts = n.split(".")
    if len(parts) == 1:
        return (2, n)
    if parts[-1] == "canal_builder":
        return (1, n)
    return (0, n)


for _name in sorted(
    [
        m
        for m in sys.modules
        if m.startswith("build_canal_model") or m.startswith("civil") or m == "paths"
    ],
    key=_reload_key,
):
    try:
        importlib.reload(sys.modules[_name])
    except Exception:
        del sys.modules[_name]

from build_canal_model.canal_builder import CanalBuilder

# "NK-1E-2" / "NK-3A-1" with Cyrillic letters as unicode escapes (ASCII-safe for the .dyn)
_NK = chr(0x41D) + chr(0x41A)  # "NK" in Cyrillic
QUERIES = [_NK + "-1A-6"]

for q in QUERIES:
    try:
        result = CanalBuilder(q).run()
        log(f"query={q!r}: {result}")
    except Exception as e:
        log(f"query={q!r} FAILED: {e}")
        log(traceback.format_exc())
log("=== DONE ===")

OUT = LOG_FILE
