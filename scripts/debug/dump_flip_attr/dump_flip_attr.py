"""Experiment: why programmatic flip mirrors point_number clones but not
point_number_circle clones (label / polka stays on the unflipped side).

For BOTH blocks: deep-clone a model-space reference, log the effective BTR name and
every ATTDEF/ATTREF position, set 'Отраженное состояние1' = 1, log everything again
(same tx), commit, log once more in a fresh transaction (post-commit evaluation),
then erase the test clones. Writes to logs/ (never only OUT).
"""

from __future__ import annotations

import clr
import datetime
import os
import traceback
from typing import Any

clr.AddReference("AecBaseMgd")
clr.AddReference("AeccDbMgd")
clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

import System
from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import (
    AttributeDefinition,
    AttributeReference,
    BlockReference,
    IdMapping,
    ObjectIdCollection,
    OpenMode,
    SymbolUtilityServices,
)

BASE = r"C:\Arhyz\automation\scripts\debug\dump_flip_attr"
os.makedirs(os.path.join(BASE, "logs"), exist_ok=True)
LOG = os.path.join(BASE, "logs", f"dump_{datetime.datetime.now():%Y%m%d_%H%M%S}.log")

FLIP_PROP = "Отраженное состояние1"
NAMES = ("point_number", "point_number_circle")


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


def dump_state(label: str, br: Any, tx: Any) -> None:
    cur = tx.GetObject(br.BlockTableRecord, OpenMode.ForRead)
    log(f"  [{label}] cur BTR='{cur.Name}' anon={cur.IsAnonymous}")
    for ent_id in cur:
        ent = tx.GetObject(ent_id, OpenMode.ForRead)
        if isinstance(ent, AttributeDefinition):
            log(
                f"    ATTDEF '{ent.Tag}' pos=({ent.Position.X:.3f},{ent.Position.Y:.3f})"
                f" align=({ent.AlignmentPoint.X:.3f},{ent.AlignmentPoint.Y:.3f})"
                f" just={ent.Justify}"
            )
    for attr_oid in br.AttributeCollection:
        a = tx.GetObject(attr_oid, OpenMode.ForRead)
        log(
            f"    ATTREF '{a.Tag}' pos=({a.Position.X:.3f},{a.Position.Y:.3f})"
            f" align=({a.AlignmentPoint.X:.3f},{a.AlignmentPoint.Y:.3f}) text='{a.TextString}'"
        )
    for p in br.DynamicBlockReferencePropertyCollection:
        if p.PropertyName == FLIP_PROP:
            log(f"    dyn '{p.PropertyName}' = {p.Value}")


def find_ref(ms: Any, tx: Any, name: str) -> Any:
    for oid in ms:
        try:
            ent = tx.GetObject(oid, OpenMode.ForRead)
        except Exception:
            continue
        if not isinstance(ent, BlockReference):
            continue
        if eff_name(ent, tx) == name:
            return oid
    return None


def clone(src_oid: Any, db: Any, ms_id: Any) -> Any:
    ids = ObjectIdCollection()
    ids.Add(src_oid)
    id_map = IdMapping()
    db.DeepCloneObjects(ids, ms_id, id_map, False)
    for pair in id_map:
        if pair.Key == src_oid:
            return pair.Value
    return None


def append_attrs(br: Any, tx: Any) -> int:
    added = 0
    btr = tx.GetObject(br.BlockTableRecord, OpenMode.ForRead)
    for ent_id in btr:
        ent = tx.GetObject(ent_id, OpenMode.ForRead)
        if not isinstance(ent, AttributeDefinition) or ent.Constant:
            continue
        ar = AttributeReference()
        ar.SetAttributeFromBlock(ent, br.BlockTransform)
        br.AttributeCollection.AppendAttribute(ar)
        tx.AddNewlyCreatedDBObject(ar, True)
        added += 1
    return added


def set_flip(br: Any, val: int) -> str:
    for p in br.DynamicBlockReferencePropertyCollection:
        if p.ReadOnly or p.PropertyName != FLIP_PROP:
            continue
        try:
            p.Value = System.Int16(val)
            return "Int16 ok"
        except Exception as e1:
            try:
                p.Value = System.Boolean(bool(val))
                return "Boolean ok"
            except Exception as e2:
                return f"FAILED: {e1} / {e2}"
    return "prop not found"


doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
lock = doc.LockDocument()
test_oids = []
try:
    log("=== DUMP FLIP ATTR ===")
    ms_id = SymbolUtilityServices.GetBlockModelSpaceId(db)

    tx = db.TransactionManager.StartTransaction()
    try:
        ms = tx.GetObject(ms_id, OpenMode.ForRead)
        for name in NAMES:
            log(f"\n### {name} ###")
            src_oid = find_ref(ms, tx, name)
            if src_oid is None:
                log("  (no reference found)")
                continue
            new_oid = clone(src_oid, db, ms_id)
            if new_oid is None:
                log("  clone FAILED")
                continue
            test_oids.append(new_oid)
            br = tx.GetObject(new_oid, OpenMode.ForWrite)
            dump_state("after clone", br, tx)
            if br.AttributeCollection.Count == 0:
                n = append_attrs(br, tx)
                log(f"  appended {n} attref(s) from current BTR")
            res = set_flip(br, 1)
            log(f"  set flip=1: {res}")
            dump_state("after set flip (same tx)", br, tx)
        tx.Commit()
        log("\nTX1 committed")
    except Exception:
        tx.Abort()
        raise
    finally:
        tx.Dispose()

    tx = db.TransactionManager.StartTransaction()
    try:
        for oid in test_oids:
            br = tx.GetObject(oid, OpenMode.ForRead)
            log(f"\n### post-commit: {eff_name(br, tx)} ###")
            dump_state("fresh tx", br, tx)
        tx.Commit()
    finally:
        tx.Dispose()

    tx = db.TransactionManager.StartTransaction()
    try:
        for oid in test_oids:
            br = tx.GetObject(oid, OpenMode.ForWrite)
            br.Erase()
        tx.Commit()
        log(f"\n{len(test_oids)} test clone(s) erased")
    finally:
        tx.Dispose()

    log("=== DONE ===")
except Exception as e:
    log(f"ERROR: {e}")
    log(traceback.format_exc())
finally:
    lock.Dispose()

OUT = LOG
