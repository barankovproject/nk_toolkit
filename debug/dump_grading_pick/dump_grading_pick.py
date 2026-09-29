"""Dump every readable property of a user-picked entity in Civil 3D.

Used to debug why a Grading (профилирование) object silently fails to
create/fill on canal Н-5А-1. Civil 3D does not raise an error, so we
inspect the picked object (or its containing GradingGroup / criteria)
directly via reflection since the static API dump has no properties for
`Grading`.

Priority:
  1. If something is in the current pickfirst selection, dump that.
  2. Otherwise prompt the user to pick one entity in the drawing.
"""

from __future__ import annotations

import datetime
import os
import traceback

import clr

clr.AddReference("AecBaseMgd")
clr.AddReference("AeccDbMgd")
clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import OpenMode, SymbolUtilityServices
from Autodesk.AutoCAD.EditorInput import PromptEntityOptions, PromptStatus
from Autodesk.Civil.ApplicationServices import CivilDocument

_STATUS_OK = int(PromptStatus.OK)

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\dump_grading_pick\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"dump_grading_pick_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def dump_entity(tx, ent, depth: int = 0) -> None:
    """Reflect over every public, non-callable attribute of ent."""
    indent = "  " * depth
    log(
        f"{indent}--- {type(ent).__name__} (mro={[c.__name__ for c in type(ent).__mro__]}) ---"
    )
    for attr in sorted(dir(ent)):
        if attr.startswith("_"):
            continue
        try:
            val = getattr(ent, attr)
        except Exception as e:
            log(f"{indent}  {attr}: <error reading: {e}>")
            continue
        if callable(val):
            continue
        try:
            log(f"{indent}  {attr} = {val!r}")
        except Exception as e:
            log(f"{indent}  {attr} = <unprintable: {e}>")

    # Follow a few likely cross-reference ids one level deep, read-only.
    for id_attr in ("GroupId", "CriteriaId", "StyleId", "SiteId", "LayerId"):
        try:
            oid = getattr(ent, id_attr, None)
        except Exception:
            continue
        if oid is None:
            continue
        try:
            if oid.IsNull:
                continue
            ref = tx.GetObject(oid, OpenMode.ForRead)
            log(f"{indent}  -> following {id_attr}:")
            dump_entity(tx, ref, depth + 2)
        except Exception as e:
            log(f"{indent}  {id_attr}: <follow error: {e}>")


doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
ed = doc.Editor

lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        oid = None

        psr = ed.SelectImplied()
        if int(psr.Status) == _STATUS_OK and psr.Value is not None:
            ids = list(psr.Value.GetObjectIds())
            if ids:
                oid = ids[0]
                log(f"pickfirst selection: {len(ids)} object(s), using first")

        if oid is None:
            opts = PromptEntityOptions("\nВыберите объект профилирования: ")
            per = ed.GetEntity(opts)
            if int(per.Status) != _STATUS_OK:
                log(f"pick cancelled (status {int(per.Status)})")
                oid = None
            else:
                oid = per.ObjectId

        if oid is not None:
            ent = tx.GetObject(oid, OpenMode.ForRead)
            log(f"picked: {type(ent).__name__}  handle={ent.Handle}")
            try:
                log(f"layer = {ent.Layer!r}")
            except Exception:
                pass
            dump_entity(tx, ent)
        else:
            log("no object picked")

        # Scan model space for any Grading entities and dump them all.
        log("\n--- scanning model space for Grading entities ---")
        ms = tx.GetObject(
            SymbolUtilityServices.GetBlockModelSpaceId(db), OpenMode.ForRead
        )
        grading_count = 0
        for oid2 in ms:
            try:
                ent2 = tx.GetObject(oid2, OpenMode.ForRead)
            except Exception:
                continue
            if type(ent2).__name__ == "Grading":
                grading_count += 1
                log(f"\nGrading entity #{grading_count}  handle={ent2.Handle}")
                dump_entity(tx, ent2)
        log(f"\ntotal Grading entities in model space: {grading_count}")

        # Try to reach GradingGroups via CivilDocument -> Sites.
        log("\n--- CivilDocument / Sites / GradingGroups ---")
        try:
            civdoc = CivilDocument.GetCivilDocument(db)
            log(f"CivilDocument sites attr present: {'Sites' in dir(civdoc)}")
            sites = civdoc.Sites
            log(f"Sites count: {sites.Count}")
            for site in sites:
                site_obj = (
                    tx.GetObject(site, OpenMode.ForRead)
                    if hasattr(site, "IsNull")
                    else site
                )
                log(f"  site: {getattr(site_obj, 'Name', site_obj)!r}")
                grading_attrs = [a for a in dir(site_obj) if "grad" in a.lower()]
                log(f"    grading-related attrs on site: {grading_attrs}")
                for ga in grading_attrs:
                    try:
                        log(f"    {ga} = {getattr(site_obj, ga)!r}")
                    except Exception as e:
                        log(f"    {ga}: <error: {e}>")
        except Exception as e:
            log(f"CivilDocument/Sites error: {e}")
            log(traceback.format_exc())

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
