"""Rebuild every corridor in its own transaction to force surface boundary clipping."""

from __future__ import annotations

import clr
import datetime
import os
import sys
import traceback
from typing import Any

clr.AddReference("AecBaseMgd")
clr.AddReference("AeccDbMgd")
clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import OpenMode
from Autodesk.Civil.ApplicationServices import CivilApplication

_LIB_ROOT = r"C:\Arhyz\automation\scripts"
if _LIB_ROOT not in sys.path:
    sys.path.insert(0, _LIB_ROOT)

from civil.utils import safe_iter  # noqa: E402

LOG_DIR = r"C:\Arhyz\automation\scripts\help_rebuild_corridors\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, f"rebuild_{datetime.datetime.now():%Y%m%d_%H%M%S}.log")


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


log("=== help_rebuild_corridors ===")
log(f"started: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n")

doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
civil_db = CivilApplication.ActiveDocument

# Collect corridor ObjectIds first (read-only, single tx)
corr_ids: list[Any] = []
lock = doc.LockDocument()
try:
    tx0 = db.TransactionManager.StartTransaction()
    try:
        for raw in safe_iter(civil_db.CorridorCollection):
            corr_ids.append(raw)
        tx0.Commit()
    except Exception:
        tx0.Abort()
    finally:
        tx0.Dispose()

    log(f"Corridors to rebuild: {len(corr_ids)}\n")

    ok = skip = fail = 0
    for raw in corr_ids:
        tx = db.TransactionManager.StartTransaction()
        name = "?"
        try:
            corr = tx.GetObject(raw, OpenMode.ForWrite)
            name = corr.Name
            corr.Rebuild()
            tx.Commit()
            log(f"  {name:30s} OK")
            ok += 1
        except Exception as e:
            log(f"  {name:30s} FAIL: {type(e).__name__}: {e}")
            log(traceback.format_exc())
            fail += 1
            try:
                tx.Abort()
            except Exception:
                pass
        finally:
            try:
                tx.Dispose()
            except Exception:
                pass

    log(f"\n--- {ok} OK, {skip} skipped, {fail} failed ---")
finally:
    try:
        lock.Dispose()
    except Exception:
        pass

log("=== DONE ===")
OUT = LOG_FILE
