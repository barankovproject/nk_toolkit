"""Verify inf_gl_* entities for НК-1А-5 are in the drawing and not hidden."""

from __future__ import annotations

import clr, datetime, os, traceback

clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import OpenMode

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\dump_gl_check\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"dump_gl_check_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)

REGAPP = "ARHYZ_GL"
CANAL = "НК-1А-5"


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
log(f"active document: {doc.Name}")

lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        # layer states
        lt = tx.GetObject(db.LayerTableId, OpenMode.ForRead)
        log("\n=== inf_gl_* layers ===")
        for lid in lt:
            ltr = tx.GetObject(lid, OpenMode.ForRead)
            if ltr.Name.startswith("inf_gl_"):
                log(f"  {ltr.Name}: off={ltr.IsOff} frozen={ltr.IsFrozen}")

        # entities in current space
        ms = tx.GetObject(db.CurrentSpaceId, OpenMode.ForWrite)
        per_layer: dict = {}
        tagged_canal = 0
        sample = None
        for oid in ms:
            ent = tx.GetObject(oid, OpenMode.ForRead)
            if not ent.Layer.startswith("inf_gl_"):
                continue
            per_layer[ent.Layer] = per_layer.get(ent.Layer, 0) + 1
            rb = ent.GetXDataForApplication(REGAPP)
            nm = None
            if rb is not None:
                nm = next((str(tv.Value) for tv in rb if tv.TypeCode == 1000), None)
            if nm == CANAL:
                tagged_canal += 1
                if sample is None:
                    try:
                        ext = ent.GeometricExtents
                        sample = f"{type(ent).__name__} on {ent.Layer}  min={ext.MinPoint} max={ext.MaxPoint}"
                    except Exception:
                        sample = f"{type(ent).__name__} on {ent.Layer} (no extents)"

        log(
            f"\n=== inf_gl_* entities in current space ({db.CurrentSpaceId == db.BlockTableId}) ==="
        )
        for lay in sorted(per_layer.keys()):
            log(f"  {lay}: {per_layer[lay]}")
        log(f"\ntotal inf_gl_* tagged '{CANAL}': {tagged_canal}")
        log(f"sample: {sample}")

        log("\n=== DONE ===")
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
