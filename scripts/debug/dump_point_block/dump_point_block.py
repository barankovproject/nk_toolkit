"""Dump the point-number block(s) so we learn the real block name, attribute tags
and whether it is dynamic, before writing ditch_07_draw_point_blocks.

Looks for block definitions whose name contains 'точк' / 'point' (covers both
'Номер_точки_канавы' and 'point_number'), lists every AttributeDefinition tag in
the block table record, and counts model-space references of each.
"""

from __future__ import annotations

import clr, datetime, math, os, traceback
from typing import Any

clr.AddReference("AecBaseMgd")
clr.AddReference("AeccDbMgd")
clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import (
    AttributeDefinition,
    AttributeReference,
    BlockReference,
    BlockTableRecord,
    OpenMode,
    SymbolUtilityServices,
)

BASE = r"C:\Arhyz\automation\scripts\debug\dump_point_block"
os.makedirs(os.path.join(BASE, "logs"), exist_ok=True)
LOG = os.path.join(BASE, "logs", f"dump_{datetime.datetime.now():%Y%m%d_%H%M%S}.log")


def log(m: Any = "") -> None:
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(str(m) + "\n")


def eff_name(br: Any, tx: Any) -> str:
    try:
        if br.IsDynamicBlock:
            return tx.GetObject(br.DynamicBlockTableRecord, OpenMode.ForRead).Name
    except Exception:
        pass
    return tx.GetObject(br.BlockTableRecord, OpenMode.ForRead).Name


def main(tx: Any, db: Any) -> None:
    bt = tx.GetObject(db.BlockTableId, OpenMode.ForRead)
    log("=== block definitions matching 'точк' / 'point' ===")
    matched: list[str] = []
    for btr_id in bt:
        btr = tx.GetObject(btr_id, OpenMode.ForRead)
        if not isinstance(btr, BlockTableRecord):
            continue
        name = btr.Name
        low = name.lower()
        if ("точк" not in low) and ("point" not in low):
            continue
        matched.append(name)
        log(f"\nBLOCK '{name}'")
        log(f"  HasAttributeDefinitions = {btr.HasAttributeDefinitions}")
        log(f"  IsDynamicBlock = {btr.IsDynamicBlock}  IsAnonymous = {btr.IsAnonymous}")
        for ent_id in btr:
            ent = tx.GetObject(ent_id, OpenMode.ForRead)
            if isinstance(ent, AttributeDefinition):
                log(
                    f"    ATTDEF tag='{ent.Tag}' prompt='{ent.Prompt}' "
                    f"default='{ent.TextString}' const={ent.Constant}"
                )
            else:
                log(f"    {ent.GetType().Name}")

    if not matched:
        log("  (no matching block definition found)")

    # Count model-space references, list attribute tags+values on the first of each
    ms = tx.GetObject(SymbolUtilityServices.GetBlockModelSpaceId(db), OpenMode.ForRead)
    counts: dict[str, int] = {}
    sample_done: set[str] = set()
    for oid in ms:
        o = tx.GetObject(oid, OpenMode.ForRead)
        if not isinstance(o, BlockReference):
            continue
        nm = eff_name(o, tx)
        low = nm.lower()
        if ("точк" not in low) and ("point" not in low):
            continue
        counts[nm] = counts.get(nm, 0) + 1
        if nm not in sample_done:
            sample_done.add(nm)
            ins = o.Position
            log(
                f"\nFIRST REF of '{nm}' at ({ins.X:.3f}, {ins.Y:.3f}) layer='{o.Layer}'"
            )
            log(
                f"  rotation_deg={math.degrees(o.Rotation):.2f} scale={o.ScaleFactors.X:.3f}"
            )
            try:
                for attr_oid in o.AttributeCollection:
                    a = tx.GetObject(attr_oid, OpenMode.ForRead)
                    if isinstance(a, AttributeReference):
                        log(f"    ATTREF tag='{a.Tag}' text='{a.TextString}'")
            except Exception as e:
                log(f"  attr read error: {e}")
            try:
                for p in o.DynamicBlockReferencePropertyCollection:
                    log(
                        f"    dyn '{p.PropertyName}' = {p.Value} (readonly={p.ReadOnly})"
                    )
            except Exception:
                pass

    log("\n=== model-space reference counts ===")
    for nm, c in counts.items():
        log(f"  '{nm}': {c}")
    if not counts:
        log("  (no matching references in model space)")


doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        log("=== DUMP POINT BLOCK ===")
        main(tx, db)
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

OUT = LOG
