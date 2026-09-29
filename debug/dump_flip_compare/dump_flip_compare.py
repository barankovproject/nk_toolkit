"""Compare UI-flipped vs script-flipped point_number_circle references entity by entity."""

from __future__ import annotations

import clr, datetime, os, traceback

clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import (
    AttributeDefinition,
    OpenMode,
    SymbolUtilityServices,
)

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\dump_flip_compare\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"dump_flip_compare_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)

BLOCK = "point_number_circle"


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        ms = tx.GetObject(
            SymbolUtilityServices.GetBlockModelSpaceId(db), OpenMode.ForRead
        )
        n = 0
        for oid in ms:
            if oid.ObjectClass.Name != "AcDbBlockReference":
                continue
            br = tx.GetObject(oid, OpenMode.ForRead)
            try:
                eff = tx.GetObject(br.DynamicBlockTableRecord, OpenMode.ForRead).Name
            except Exception:
                eff = br.Name
            if eff != BLOCK:
                continue
            n += 1
            log(
                f"--- ref #{n} at ({br.Position.X:.2f}, {br.Position.Y:.2f}) "
                f"Name={br.Name!r} ScaleFactors={br.ScaleFactors} "
                f"Rotation={br.Rotation:.4f}"
            )
            for prop in br.DynamicBlockReferencePropertyCollection:
                log(
                    f"  prop {prop.PropertyName!r} = {prop.Value!r} "
                    f"ReadOnly={prop.ReadOnly}"
                )
            for attr_oid in br.AttributeCollection:
                a = tx.GetObject(attr_oid, OpenMode.ForRead)
                log(
                    f"  ATTREF Tag={a.Tag!r} Text={a.TextString!r} "
                    f"dPos=({a.Position.X - br.Position.X:.3f}, "
                    f"{a.Position.Y - br.Position.Y:.3f}) "
                    f"dAlign=({a.AlignmentPoint.X - br.Position.X:.3f}, "
                    f"{a.AlignmentPoint.Y - br.Position.Y:.3f}) "
                    f"Justify={a.Justify} Rotation={a.Rotation:.4f} "
                    f"IsMirroredInX={a.IsMirroredInX} IsMirroredInY={a.IsMirroredInY} "
                    f"Height={a.Height:.3f} Oblique={a.Oblique:.4f} "
                    f"WidthFactor={a.WidthFactor:.3f}"
                )
            btr = tx.GetObject(br.BlockTableRecord, OpenMode.ForRead)
            log(f"  BTR={btr.Name!r}:")
            for ent_id in btr:
                ent = tx.GetObject(ent_id, OpenMode.ForRead)
                t = ent_id.ObjectClass.Name
                if isinstance(ent, AttributeDefinition):
                    log(
                        f"    ATTDEF Pos=({ent.Position.X:.3f}, {ent.Position.Y:.3f}) "
                        f"Align=({ent.AlignmentPoint.X:.3f}, {ent.AlignmentPoint.Y:.3f}) "
                        f"Justify={ent.Justify} Rotation={ent.Rotation:.4f} "
                        f"IsMirroredInX={ent.IsMirroredInX} "
                        f"IsMirroredInY={ent.IsMirroredInY} "
                        f"Oblique={ent.Oblique:.4f}"
                    )
                else:
                    log(f"    {t}")
            if n >= 12:
                log("... stopped at 12 refs")
                break
        log()
        log(f"total refs dumped: {n}")
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
