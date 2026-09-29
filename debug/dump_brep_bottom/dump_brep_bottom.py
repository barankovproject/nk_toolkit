"""Dump: can acdbmgdbrep extract the bottom-face edge loop of a GSI mat Solid3d?"""

from __future__ import annotations

import clr
import datetime
import os
import traceback

clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import OpenMode, Solid3d, SymbolUtilityServices

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\dump_brep_bottom\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"dump_brep_bottom_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)

_LAYER = "inf_gsi_apron_mat"


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        try:
            clr.AddReference("acdbmgdbrep")
            log("acdbmgdbrep reference: OK")
        except Exception as e:
            log(f"acdbmgdbrep reference FAILED: {e}")
            raise
        from Autodesk.AutoCAD.BoundaryRepresentation import Brep

        log("Brep import: OK")

        ms = tx.GetObject(
            SymbolUtilityServices.GetBlockModelSpaceId(db), OpenMode.ForRead
        )
        target = None
        n_mats = 0
        for oid in ms:
            o = tx.GetObject(oid, OpenMode.ForRead)
            if isinstance(o, Solid3d) and o.Layer == _LAYER:
                n_mats += 1
                if target is None:
                    target = o
        log(f"solids on {_LAYER}: {n_mats}")
        if target is None:
            log("no target solid — open the KV drawing")
        else:
            brep = Brep(target)
            log(f"brep type: {type(brep).__name__}")
            faces = list(brep.Faces)
            log(f"faces: {len(faces)}")
            log(
                "dir(face): " + str([a for a in dir(faces[0]) if not a.startswith("_")])
            )
            # iteration 2: is loop.Vertices ORDERED around the loop?
            best = None
            for fi, face in enumerate(faces):
                for loop in face.Loops:
                    vs = [
                        (round(v.Point.X, 3), round(v.Point.Y, 3), round(v.Point.Z, 3))
                        for v in loop.Vertices
                    ]
                    mean_z = sum(v[2] for v in vs) / len(vs)
                    if best is None or mean_z < best[0]:
                        best = (mean_z, fi, vs)
            if best is not None:
                log(f"bottom face by mean z: face {best[1]} mean_z={best[0]:.3f}")
                log(f"loop.Vertices in order: {best[2]}")
            for fi, face in enumerate(faces):
                try:
                    loops = list(face.Loops)
                except Exception as e:
                    log(f"face {fi}: Loops failed: {e}")
                    continue
                log(f"face {fi}: {len(loops)} loop(s)")
                for li, loop in enumerate(loops):
                    if fi == 0 and li == 0:
                        log(
                            "  dir(loop): "
                            + str([a for a in dir(loop) if not a.startswith("_")])
                        )
                    try:
                        verts = []
                        for ed in loop.Edges:
                            if fi == 0 and li == 0 and not verts:
                                log(
                                    "  dir(edge): "
                                    + str([a for a in dir(ed) if not a.startswith("_")])
                                )
                            v1 = ed.Vertex1.Point
                            v2 = ed.Vertex2.Point
                            verts.append(
                                (round(v1.X, 3), round(v1.Y, 3), round(v1.Z, 3))
                            )
                            verts.append(
                                (round(v2.X, 3), round(v2.Y, 3), round(v2.Z, 3))
                            )
                        zs = [v[2] for v in verts]
                        log(
                            f"  face {fi} loop {li}: {len(verts)} edge-verts, "
                            f"z {min(zs):.3f}..{max(zs):.3f}"
                        )
                        log(f"    verts: {verts}")
                    except Exception as e:
                        log(f"  face {fi} loop {li}: edge walk failed: {e}")
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
