"""Recompute longitudinal-ditch volume property sets from the current drawn geometry.

Run after manually editing longitudinal ditches (3D polylines on inf_ct_toe) in the
drawing: it re-reads every ditch's live geometry and rewrites the volume fields of its
Arhyz_LongDitch property set, so the quantities match what is actually drawn. Cut-toe
lines (ARHYZ_CT) share the same layer and are left untouched. Rates live in
ditch_03_build_long/volumes.py; this script never recomputes them inline. The ведомость
(ditch_06_report_long) then sums the refreshed values.
"""

from __future__ import annotations

import clr
import datetime
import os
import sys
import traceback

clr.AddReference("AecBaseMgd")
clr.AddReference("AeccDbMgd")
clr.AddReference("acmgd")
clr.AddReference("acdbmgd")
clr.AddReference("AecPropDataMgd")

_SCRIPTS_ROOT = r"C:\Arhyz\automation\scripts\ditch"
if _SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, _SCRIPTS_ROOT)

# Drop cached package modules so edits to volumes.py / refresh.py take effect.
for _m in [
    m
    for m in list(sys.modules)
    if m.startswith("ditch_03_build_long") or m.startswith("ditch_core")
]:
    del sys.modules[_m]

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import OpenMode, SymbolUtilityServices

from ditch_03_build_long.property_sets import ensure_ld_psd
from ditch_03_build_long.refresh import refresh_long_volumes

LOG_DIR = r"C:\Arhyz\automation\scripts\ditch\ditch_05_build_long_volumes\logs"
os.makedirs(LOG_DIR, exist_ok=True)
TIMESTAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILE = os.path.join(LOG_DIR, f"refresh_{TIMESTAMP}.log")


def log(msg: str = "", level: str = "INFO") -> None:
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] [{level}] {msg}\n")


log("=== ditch_05_build_long_volumes (refresh PS from geometry) ===")

updated = 0
errors = 0
doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database

lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        psd_id = ensure_ld_psd(db, tx)
        ms_id = SymbolUtilityServices.GetBlockModelSpaceId(db)
        ms = tx.GetObject(ms_id, OpenMode.ForRead)
        updated = refresh_long_volumes(ms, tx, psd_id, log)
        log(f"refreshed {updated} longitudinal ditch(es) from current geometry")
        tx.Commit()
    except Exception as e:
        errors += 1
        log(f"ERROR: {e}\n{traceback.format_exc()}", "CRITICAL")
        try:
            tx.Abort()
        except Exception:
            pass
    finally:
        try:
            tx.Dispose()
        except Exception:
            pass
finally:
    try:
        lock.Dispose()
    except Exception:
        pass

log(f"=== DONE: updated={updated}, errors={errors} ===")
OUT = updated if errors == 0 else f"errors={errors}"
