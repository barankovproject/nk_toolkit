"""Clone point_number_circle, set flip, log ATTDEF/ATTREF positions before/after."""

from __future__ import annotations

import clr, datetime, os, traceback

clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

import System
from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import (
    AttributeDefinition,
    AttributeReference,
    IdMapping,
    ObjectIdCollection,
    OpenMode,
    SymbolUtilityServices,
)
from Autodesk.AutoCAD.Geometry import Matrix3d, Vector3d

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\dump_flip_circle\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"dump_flip_circle_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)

BLOCK = "point_number_circle"
FLIP_PROP = "Отраженное состояние1"


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def dump_btr_attdefs(tx, btr_id, label):
    btr = tx.GetObject(btr_id, OpenMode.ForRead)
    log(f"  {label}: BTR name={btr.Name!r}")
    for ent_id in btr:
        ent = tx.GetObject(ent_id, OpenMode.ForRead)
        if isinstance(ent, AttributeDefinition):
            log(
                f"    ATTDEF Tag={ent.Tag!r} Position=({ent.Position.X:.3f}, "
                f"{ent.Position.Y:.3f}) Justify={ent.Justify}"
            )


def dump_attrefs(tx, br, label):
    log(f"  {label}: ATTREF count={br.AttributeCollection.Count}")
    for attr_oid in br.AttributeCollection:
        attr = tx.GetObject(attr_oid, OpenMode.ForRead)
        log(
            f"    ATTREF Tag={attr.Tag!r} Position=({attr.Position.X:.3f}, "
            f"{attr.Position.Y:.3f}) Alignment=({attr.AlignmentPoint.X:.3f}, "
            f"{attr.AlignmentPoint.Y:.3f}) Justify={attr.Justify} "
            f"Text={attr.TextString!r}"
        )


doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        bt = tx.GetObject(db.BlockTableId, OpenMode.ForRead)
        ms_id = SymbolUtilityServices.GetBlockModelSpaceId(db)
        ms = tx.GetObject(ms_id, OpenMode.ForRead)

        # find template reference
        src_oid = None
        for oid in ms:
            if oid.ObjectClass.Name != "AcDbBlockReference":
                continue
            br = tx.GetObject(oid, OpenMode.ForRead)
            try:
                eff = tx.GetObject(br.DynamicBlockTableRecord, OpenMode.ForRead).Name
            except Exception:
                eff = br.Name
            if eff == BLOCK:
                src_oid = oid
                break
        if src_oid is None:
            log(f"no reference of '{BLOCK}' in model space")
            raise SystemExit

        src = tx.GetObject(src_oid, OpenMode.ForRead)
        log(
            f"template: Name={src.Name!r} IsDynamic={src.IsDynamicBlock} "
            f"pos=({src.Position.X:.3f}, {src.Position.Y:.3f})"
        )
        dump_btr_attdefs(tx, src.BlockTableRecord, "template current BTR")
        dump_attrefs(tx, src, "template")

        # clone
        ids = ObjectIdCollection()
        ids.Add(src_oid)
        id_map = IdMapping()
        db.DeepCloneObjects(ids, ms_id, id_map, False)
        new_oid = None
        for pair in id_map:
            if pair.Key == src_oid:
                new_oid = pair.Value
        br = tx.GetObject(new_oid, OpenMode.ForWrite)
        br.TransformBy(Matrix3d.Displacement(Vector3d(5.0, 5.0, 0.0)))
        log()
        log("clone created at +5,+5")
        dump_btr_attdefs(tx, br.BlockTableRecord, "clone BTR BEFORE anything")

        # ensure attributes (same as _ensure_attributes)
        if br.AttributeCollection.Count == 0:
            btr = tx.GetObject(br.BlockTableRecord, OpenMode.ForRead)
            for ent_id in btr:
                ent = tx.GetObject(ent_id, OpenMode.ForRead)
                if not isinstance(ent, AttributeDefinition) or ent.Constant:
                    continue
                ar = AttributeReference()
                ar.SetAttributeFromBlock(ent, br.BlockTransform)
                br.AttributeCollection.AppendAttribute(ar)
                tx.AddNewlyCreatedDBObject(ar, True)
        dump_attrefs(tx, br, "clone AFTER ensure_attributes, BEFORE flip")

        # set flip
        set_ok = False
        for prop in br.DynamicBlockReferencePropertyCollection:
            if prop.ReadOnly or prop.PropertyName != FLIP_PROP:
                continue
            try:
                prop.Value = System.Int16(1)
            except Exception:
                prop.Value = System.Boolean(True)
            set_ok = True
        log()
        log(f"flip set: {set_ok}")

        # re-read after flip
        for prop in br.DynamicBlockReferencePropertyCollection:
            if prop.PropertyName == FLIP_PROP:
                log(f"  flip value now = {prop.Value!r}")
        dump_btr_attdefs(tx, br.BlockTableRecord, "clone BTR AFTER flip")
        dump_attrefs(tx, br, "clone AFTER flip")

        # label the flip-only clone
        for attr_oid in br.AttributeCollection:
            attr = tx.GetObject(attr_oid, OpenMode.ForWrite)
            attr.TextString = "т.А"

        # ── second clone: flip + re-sync ATTREF from the flipped ATTDEF ───────
        db.DeepCloneObjects(ids, ms_id, id_map2 := IdMapping(), False)
        oid2 = None
        for pair in id_map2:
            if pair.Key == src_oid:
                oid2 = pair.Value
        br2 = tx.GetObject(oid2, OpenMode.ForWrite)
        br2.TransformBy(Matrix3d.Displacement(Vector3d(5.0, 10.0, 0.0)))
        if br2.AttributeCollection.Count == 0:
            btr2 = tx.GetObject(br2.BlockTableRecord, OpenMode.ForRead)
            for ent_id in btr2:
                ent = tx.GetObject(ent_id, OpenMode.ForRead)
                if not isinstance(ent, AttributeDefinition) or ent.Constant:
                    continue
                ar = AttributeReference()
                ar.SetAttributeFromBlock(ent, br2.BlockTransform)
                br2.AttributeCollection.AppendAttribute(ar)
                tx.AddNewlyCreatedDBObject(ar, True)
        for prop in br2.DynamicBlockReferencePropertyCollection:
            if not prop.ReadOnly and prop.PropertyName == FLIP_PROP:
                try:
                    prop.Value = System.Int16(1)
                except Exception:
                    prop.Value = System.Boolean(True)
        # FIX under test (final callout_rail logic): re-anchor on the evaluated
        # BTR's ATTDEF, then swap justification to the mirrored side.
        from Autodesk.AutoCAD.DatabaseServices import AttachmentPoint

        mirror = {
            AttachmentPoint.TopLeft: AttachmentPoint.TopRight,
            AttachmentPoint.MiddleLeft: AttachmentPoint.MiddleRight,
            AttachmentPoint.BottomLeft: AttachmentPoint.BottomRight,
            AttachmentPoint.BaseLeft: AttachmentPoint.BaseRight,
            AttachmentPoint.TopRight: AttachmentPoint.TopLeft,
            AttachmentPoint.MiddleRight: AttachmentPoint.MiddleLeft,
            AttachmentPoint.BottomRight: AttachmentPoint.BottomLeft,
            AttachmentPoint.BaseRight: AttachmentPoint.BaseLeft,
        }
        btr2f = tx.GetObject(br2.BlockTableRecord, OpenMode.ForRead)
        defs = {}
        for ent_id in btr2f:
            ent = tx.GetObject(ent_id, OpenMode.ForRead)
            if isinstance(ent, AttributeDefinition) and not ent.Constant:
                defs[str(ent.Tag).upper()] = ent
        for attr_oid in br2.AttributeCollection:
            attr = tx.GetObject(attr_oid, OpenMode.ForWrite)
            d = defs.get(str(attr.Tag).upper())
            if d is not None:
                attr.SetAttributeFromBlock(d, br2.BlockTransform)
                m = mirror.get(attr.Justify)
                if m is not None:
                    anchor = attr.AlignmentPoint
                    attr.Justify = m
                    attr.AlignmentPoint = anchor
                    attr.AdjustAlignment(db)
            attr.TextString = "т.Б"
        log()
        dump_attrefs(tx, br2, "clone2 AFTER flip + resync + justify swap")

        log()
        log("=== DONE === (т.А=flip only at +5,+5; т.Б=full fix at +5,+10)")
        tx.Commit()
    except SystemExit:
        tx.Abort()
    except Exception as e:
        log(f"ERROR: {e}")
        log(traceback.format_exc())
        tx.Abort()
    finally:
        tx.Dispose()
finally:
    lock.Dispose()

OUT = LOG_FILE
