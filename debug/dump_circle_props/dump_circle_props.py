"""Dump dynamic properties and attribute definitions of the point_number_circle block."""

from __future__ import annotations

import clr, datetime, os, traceback

clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import (
    AttributeDefinition,
    BlockReference,
    OpenMode,
)

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\dump_circle_props\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"dump_circle_props_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
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
        bt = tx.GetObject(db.BlockTableId, OpenMode.ForRead)

        # ── block DEFINITION: entities + attribute definitions ────────────────
        if bt.Has(BLOCK):
            btr = tx.GetObject(bt[BLOCK], OpenMode.ForRead)
            log(f"definition '{BLOCK}': IsDynamicBlock={btr.IsDynamicBlock}")
            for ent_id in btr:
                ent = tx.GetObject(ent_id, OpenMode.ForRead)
                tname = type(ent).__name__
                if isinstance(ent, AttributeDefinition):
                    log(f"  entity {tname}: Tag={ent.Tag!r} Constant={ent.Constant}")
                else:
                    log(f"  entity {tname} class={ent_id.ObjectClass.Name}")
        else:
            log(f"definition '{BLOCK}': NOT IN BLOCK TABLE")

        # ── first REFERENCE with matching effective name ──────────────────────
        from Autodesk.AutoCAD.DatabaseServices import SymbolUtilityServices

        ms = tx.GetObject(
            SymbolUtilityServices.GetBlockModelSpaceId(db), OpenMode.ForRead
        )
        found = 0
        for oid in ms:
            if oid.ObjectClass.Name != "AcDbBlockReference":
                continue
            br = tx.GetObject(oid, OpenMode.ForRead)
            try:
                btr_ref = tx.GetObject(br.DynamicBlockTableRecord, OpenMode.ForRead)
                eff = btr_ref.Name
            except Exception:
                eff = br.Name
            if eff != BLOCK:
                continue
            found += 1
            log()
            log(
                f"reference #{found}: Name={br.Name!r} EffectiveName={eff!r} "
                f"IsDynamicBlock={br.IsDynamicBlock} Layer={br.Layer!r}"
            )
            props = br.DynamicBlockReferencePropertyCollection
            log(f"  dynamic properties: {props.Count}")
            for prop in props:
                log(
                    f"    PropertyName={prop.PropertyName!r} Value={prop.Value!r} "
                    f"ReadOnly={prop.ReadOnly} UnitsType={prop.UnitsType} "
                    f"TypeCode={prop.PropertyTypeCode}"
                )
            log(f"  attributes on reference: {br.AttributeCollection.Count}")
            for attr_oid in br.AttributeCollection:
                attr = tx.GetObject(attr_oid, OpenMode.ForRead)
                log(f"    ATTREF Tag={attr.Tag!r} Text={attr.TextString!r}")
            if found >= 3:
                break
        if found == 0:
            log()
            log(f"no reference of '{BLOCK}' found in model space")

        log()
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
