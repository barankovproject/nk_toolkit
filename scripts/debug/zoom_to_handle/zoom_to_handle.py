"""Select and zoom to a specific entity by its AutoCAD handle.

One-off helper to visually locate the Grading object found while debugging
why 'Заполнение' (Infill) does not seem to produce a visible bottom on
canal Н-5А-1. Highlights the object with grips and zooms the current
viewport to it, so the user can look without typing any AutoCAD commands.
"""

from __future__ import annotations

import datetime
import os
import traceback

import clr

clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import Handle, OpenMode

HANDLE = "DDA13"

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\zoom_to_handle\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"zoom_to_handle_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
ed = doc.Editor

lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        h = Handle(int(HANDLE, 16))
        oid = db.GetObjectId(False, h, 0)
        ent = tx.GetObject(oid, OpenMode.ForRead)
        log(f"found handle {HANDLE}: {type(ent).__name__}  erased={ent.IsErased}")

        from System import Array
        from Autodesk.AutoCAD.DatabaseServices import ObjectId

        ed.SetImpliedSelection(Array[ObjectId]([oid]))
        log("implied selection set (grips should now be highlighted)")

        tx.Commit()
    except Exception as e:
        log(f"ERROR: {e}")
        log(traceback.format_exc())
        tx.Abort()
    finally:
        tx.Dispose()
finally:
    lock.Dispose()

# Zoom after the transaction closes, using pickfirst selection.
try:
    doc.SendStringToExecute("._zoom _object \n\n", True, False, False)
    log("zoom object sent")
except Exception as e:
    log(f"zoom ERROR: {e}")

log("\n=== DONE ===")
OUT = LOG_FILE
