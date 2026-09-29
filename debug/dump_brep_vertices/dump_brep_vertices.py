"""Dump: can BRep (acdbmgdbrep) extract vertices from the GSI-ditch mattress Solid3ds?"""

from __future__ import annotations

import clr, datetime, os, traceback

clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import OpenMode, Solid3d, SymbolUtilityServices

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\dump_brep_vertices\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"dump_brep_vertices_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)

_MAT_LAYER = "inf_gsi_ditch_mat"
_REGAPP = "ARHYZ_GSD"


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        # 1) is the BRep assembly loadable at all?
        try:
            clr.AddReference("acdbmgdbrep")
            log("acdbmgdbrep: AddReference OK")
        except Exception as e:
            log(f"acdbmgdbrep: AddReference FAILED: {e}")
            raise
        from Autodesk.AutoCAD.BoundaryRepresentation import Brep

        log("Brep import OK")

        # 2) find mattress solids
        ms = tx.GetObject(
            SymbolUtilityServices.GetBlockModelSpaceId(db), OpenMode.ForRead
        )
        solids = []
        for oid in ms:
            try:
                ent = tx.GetObject(oid, OpenMode.ForRead)
            except Exception:
                continue
            if not isinstance(ent, Solid3d):
                continue
            if str(ent.Layer) != _MAT_LAYER:
                continue
            solids.append(ent)
        log(f"found {len(solids)} Solid3d on layer '{_MAT_LAYER}'")

        # 3) extract vertices from the first few solids
        for k, ent in enumerate(solids[:3]):
            tagged = ent.GetXDataForApplication(_REGAPP) is not None
            try:
                brep = Brep(ent)
                try:
                    verts = [
                        (float(v.Point.X), float(v.Point.Y), float(v.Point.Z))
                        for v in brep.Vertices
                    ]
                finally:
                    brep.Dispose()
                log(f"solid[{k}] (xdata={tagged}): {len(verts)} BRep vertices")
                for x, y, z in verts[:6]:
                    log(f"    ({x:.3f}, {y:.3f}, {z:.3f})")
            except Exception as e:
                log(f"solid[{k}]: Brep FAILED: {e}")
                log(traceback.format_exc())

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
