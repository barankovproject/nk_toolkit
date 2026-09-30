"""Build Civil 3D Corridors for ALL canals in the arhyz_s2_data repo's config/canals.

Thin wrapper over CorridorBuilder — iterates every canal config and calls run() on each.
Skips canals that start with a trough segment (no assembly) or already have a corridor.
"""

from __future__ import annotations

import clr, importlib, sys, os, datetime

clr.AddReference("AecBaseMgd")
clr.AddReference("AeccDbMgd")
clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

_LIB_ROOT = r"C:\Arhyz\automation\scripts"
if _LIB_ROOT not in sys.path:
    sys.path.insert(0, _LIB_ROOT)

for _name in sorted(
    [m for m in sys.modules if m.startswith("build_corridors")], reverse=True
):
    try:
        importlib.reload(sys.modules[_name])
    except Exception:
        pass

from build_corridors.corridor_builder import CorridorBuilder, CONFIG_DIR

LOG_DIR = r"C:\Arhyz\automation\scripts\build_corridors\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, f"build_{datetime.datetime.now():%Y%m%d_%H%M%S}.log")


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


log("=== build_corridors_all ===")
log(f"started: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")

config_files = sorted(f for f in os.listdir(CONFIG_DIR) if f.lower().endswith(".json"))
log(f"canal configs: {len(config_files)}\n")

results: list[str] = []
for fname in config_files:
    canal_name = fname[:-5]
    try:
        status = CorridorBuilder(canal_name).run()
    except Exception as e:
        status = f"FAIL exception: {type(e).__name__}: {e}"
    line = f"  {canal_name:30s} : {status}"
    log(line)
    results.append(line)

ok = sum(1 for r in results if ": OK" in r)
fail = len(results) - ok
summary = f"--- {ok} OK, {fail} skipped/failed ---"
log(f"\n{summary}")
results.append(summary)

log("=== DONE ===")
OUT = "\n".join(results)
