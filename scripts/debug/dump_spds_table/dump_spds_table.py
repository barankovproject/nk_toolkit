"""Dump: identify the runtime type/API surface of an existing SPDS table in the
current drawing, so build_gsi_ribs (or a new report script) can later fill/create such
a table with the GSI-basket specification (mats/walls/ribs). No prior SPDS usage in
this codebase -- first exploration pass.
"""

from __future__ import annotations

import clr
import datetime
import os
import traceback

clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import (
    BlockReference,
    OpenMode,
    SymbolUtilityServices,
    Table,
)

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\dump_spds_table\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"dump_spds_table_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def dump_table(tbl) -> None:
    log(f"  TableStyle: {tbl.TableStyle}")
    log(f"  Rows x Cols: {tbl.Rows.Count} x {tbl.Columns.Count}")
    for r in range(min(tbl.Rows.Count, 15)):
        row_cells = []
        for c in range(tbl.Columns.Count):
            try:
                txt = tbl.Cells[r, c].TextString
            except Exception as e:
                txt = f"<err:{e}>"
            row_cells.append(txt)
        log(f"    row {r}: {row_cells}")
    if tbl.Rows.Count > 15:
        log(f"    ... ({tbl.Rows.Count - 15} more rows)")


doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        log(f"drawing: {db.Filename}")

        # 1) loaded assemblies -- anything SPDS/nanoCAD related?
        try:
            import System

            log("--- loaded assemblies matching Spds/SPDS/nanocad ---")
            asms = System.AppDomain.CurrentDomain.GetAssemblies()
            hits = [
                a
                for a in asms
                if "spds" in str(a.FullName).lower()
                or "nanocad" in str(a.FullName).lower()
            ]
            if not hits:
                log("  none found")
            for a in hits:
                log(f"  {a.FullName}")
                try:
                    types = a.GetTypes()
                    table_like = [
                        t.FullName for t in types if "table" in t.Name.lower()
                    ]
                    for t in table_like[:40]:
                        log(f"      type: {t}")
                except Exception as e:
                    log(f"      (GetTypes failed: {e})")
        except Exception as e:
            log(f"assembly scan failed: {e}")

        # 2) model space entities -- anything table-like
        log("--- model space scan: table-like entities ---")
        ms = tx.GetObject(
            SymbolUtilityServices.GetBlockModelSpaceId(db), OpenMode.ForRead
        )
        n_scanned = 0
        n_table_type = 0
        n_blockref_table_name = 0
        for oid in ms:
            try:
                o = tx.GetObject(oid, OpenMode.ForRead)
            except Exception:
                continue
            n_scanned += 1
            tname = o.GetType().FullName
            if isinstance(o, Table):
                n_table_type += 1
                log(f"[Table] handle={o.Handle} type={tname}")
                try:
                    dump_table(o)
                except Exception as e:
                    log(f"  dump_table failed: {e}")
                    log(traceback.format_exc())
            elif isinstance(o, BlockReference):
                btr_id = (
                    o.DynamicBlockTableRecord
                    if o.IsDynamicBlock
                    else o.BlockTableRecord
                )
                bname = str(tx.GetObject(btr_id, OpenMode.ForRead).Name)
                if (
                    "table" in bname.lower()
                    or "spds" in bname.lower()
                    or "спдс" in bname.lower()
                ):
                    n_blockref_table_name += 1
                    log(
                        f"[BlockReference] handle={o.Handle} block='{bname}' "
                        f"type={tname}"
                    )
            elif "table" in tname.lower() or "spds" in tname.lower():
                log(f"[other table-like] handle={o.Handle} type={tname}")

        log(f"scanned {n_scanned} model-space entities")
        log(f"  Table-type objects: {n_table_type}")
        log(f"  BlockReferences with table-ish names: {n_blockref_table_name}")
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
