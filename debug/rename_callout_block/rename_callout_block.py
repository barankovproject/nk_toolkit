"""Rename the callout block definition "321" -> "номер_точки" in the active drawing.

One-off maintenance: block references point to the BlockTableRecord by ObjectId,
not by name, so existing inserts keep working after the rename. Aborts (no change)
if a block named "номер_точки" already exists, to avoid a name clash / merge.
"""

from __future__ import annotations

import clr, datetime, os, traceback

clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import BlockTable, OpenMode

OLD_NAME = "321"
NEW_NAME = "номер_точки"

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\rename_callout_block\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"rename_callout_block_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        log("=== RENAME CALLOUT BLOCK ===")
        log(f"'{OLD_NAME}' -> '{NEW_NAME}'")
        bt = tx.GetObject(db.BlockTableId, OpenMode.ForRead)

        names = []
        old_id = None
        clash = False
        for btr_id in bt:
            btr = tx.GetObject(btr_id, OpenMode.ForRead)
            names.append(btr.Name)
            if btr.Name == OLD_NAME:
                old_id = btr_id
            if btr.Name == NEW_NAME:
                clash = True

        if clash:
            log(f"ABORT: a block named '{NEW_NAME}' already exists")
        elif old_id is None:
            log(f"ABORT: no block named '{OLD_NAME}' found")
            log("block names present: " + ", ".join(sorted(names)))
        else:
            btr = tx.GetObject(old_id, OpenMode.ForWrite)
            btr.Name = NEW_NAME
            log(f"OK: renamed (ObjectId={old_id})")

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
