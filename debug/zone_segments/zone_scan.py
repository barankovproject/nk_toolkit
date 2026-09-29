"""DB-wide scan: per-block-record entity histogram; locate Hatch / Region / Solid anywhere."""

from __future__ import annotations

import clr, datetime, os, traceback

clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import (
    OpenMode,
    BlockTable,
    BlockTableRecord,
    Hatch,
)

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\zone_segments\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"zone_scan_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
log(f"active doc: {doc.Name}")
lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        bt = tx.GetObject(db.BlockTableId, OpenMode.ForRead)
        for btr_id in bt:
            btr = tx.GetObject(btr_id, OpenMode.ForRead)
            name = btr.Name
            hist: dict = {}
            hatches = []
            for oid in btr:
                try:
                    ent = tx.GetObject(oid, OpenMode.ForRead)
                except Exception:
                    continue
                tn = type(ent).__name__
                hist[tn] = hist.get(tn, 0) + 1
                if isinstance(ent, Hatch):
                    try:
                        c = None
                        for li in range(ent.NumberOfLoops):
                            pass
                        hatches.append(
                            (ent.Layer, ent.PatternName, ent.NumberOfLoops, ent.Area)
                        )
                    except Exception:
                        hatches.append((ent.Layer, "?", -1, -1))
            if hist:
                parts = ", ".join(f"{k}={v}" for k, v in sorted(hist.items()))
                flag = (
                    "  <-- has entities"
                    if name.lower() in ("*model_space", "*paper_space") or True
                    else ""
                )
                log(f"[{name}] {parts}")
            for h in hatches:
                log(f"    HATCH layer=[{h[0]}] pattern={h[1]} loops={h[2]} area={h[3]}")
        log("=== DONE ===")
        tx.Commit()
    except Exception as e:
        log(f"ERROR: {e}")
        log(traceback.format_exc())
        tx.Abort()
    finally:
        tx.Dispose()
finally:
    lock.Dispose()

OUT = LOG_FILE
