"""Build a TIN surface for every corridor: link code Top, boundary from inf_model_corridors polyline.

Two-pass approach (each corridor in its own transaction):
  Pass 1: configure link code, break line, FL codes → rebuild.
  Pass 2: clear boundaries, add boundary from tagged outline polyline → rebuild.

Prerequisite: draw_corridor_outlines must be run first to create XData-tagged polylines
on layer inf_model_corridors (XDATA_APP='ARHYZ_CORR', code 1000 = corridor name).
"""

from __future__ import annotations

import clr
import datetime
import json
import os
import sys
import traceback
from typing import Any

clr.AddReference("AecBaseMgd")
clr.AddReference("AeccDbMgd")
clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import Handle as AcHandle
from Autodesk.AutoCAD.DatabaseServices import OpenMode
from Autodesk.Civil.ApplicationServices import CivilApplication

_LIB_ROOT = r"C:\Arhyz\automation\scripts"
if _LIB_ROOT not in sys.path:
    sys.path.insert(0, _LIB_ROOT)

from civil.utils import safe_iter  # noqa: E402

LOG_DIR = r"C:\Arhyz\automation\scripts\build_corridor_surfaces\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, f"build_{datetime.datetime.now():%Y%m%d_%H%M%S}.log")

LINK_CODE = "Top"
BOUNDARY_NAME = "outline"
FL_CODES = ("Daylight", "Ditch_Out")
HANDLES_FILE = (
    r"C:\Arhyz\automation\scripts\draw_corridor_outlines\corridor_outlines.json"
)


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def load_outline_map(db: Any) -> dict[str, Any]:
    """Load {corridor_name: ObjectId} from the JSON handle file written by draw_corridor_outlines."""
    try:
        with open(HANDLES_FILE, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        log(f"WARNING: could not read {HANDLES_FILE}: {e}")
        return {}
    result: dict[str, Any] = {}
    for name, hstr in raw.items():
        try:
            oid = db.GetObjectId(False, AcHandle(int(hstr, 16)), 0)
            if not oid.IsNull:
                result[name] = oid
        except Exception:
            pass
    return result


def configure_codes(corr_w: Any) -> str:
    """Pass 1: ensure surface exists with link code, break line, FL codes; rebuild."""
    cs_col = corr_w.CorridorSurfaces
    if cs_col.Count == 0:
        surf_name = f"{corr_w.Name} - Surface"
        try:
            cs_col.Add(surf_name)
        except Exception as e:
            return f"FAIL Add: {type(e).__name__}: {e}"

    for cs in cs_col:
        try:
            existing_lc = list(cs.LinkCodes())
            if LINK_CODE not in existing_lc:
                cs.AddLinkCode(LINK_CODE, False)
        except Exception as e:
            return f"FAIL AddLinkCode: {type(e).__name__}: {e}"
        try:
            cs.SetLinkCodeAsBreakLine(LINK_CODE, True)
        except Exception as e:
            return f"FAIL SetLinkCodeAsBreakLine: {type(e).__name__}: {e}"
        try:
            existing_fl = list(cs.FeatureLineCodes())
            for code in FL_CODES:
                if code not in existing_fl:
                    cs.AddFeatureLineCode(code)
        except Exception as e:
            return f"FAIL AddFeatureLineCode: {type(e).__name__}: {e}"
    try:
        corr_w.Rebuild()
    except Exception as e:
        return f"FAIL Rebuild: {type(e).__name__}: {e}"
    return "OK"


def apply_boundary(corr_w: Any, pl_id: Any) -> str:
    """Pass 2: clear boundaries, add outline polyline as boundary, rebuild."""
    for cs in corr_w.CorridorSurfaces:
        try:
            bnd_col = cs.Boundaries
            while bnd_col.Count > 0:
                bnd_col.RemoveAt(0)
            bnd_col.Add(BOUNDARY_NAME, pl_id)
        except Exception as e:
            return f"FAIL Boundary: {type(e).__name__}: {e}"
    try:
        corr_w.Rebuild()
    except Exception as e:
        return f"FAIL Rebuild: {type(e).__name__}: {e}"
    return "OK"


def run_pass(
    corr_ids: list[Any],
    db: Any,
    fn: Any,
    label: str,
    extra_args: dict[Any, Any] | None = None,
) -> None:
    for raw in corr_ids:
        tx = db.TransactionManager.StartTransaction()
        name = "?"
        try:
            corr = tx.GetObject(raw, OpenMode.ForWrite)
            name = corr.Name
            if extra_args is not None:
                arg = extra_args.get(raw)
                if arg is None:
                    status = f"SKIP (no outline polyline for {name})"
                else:
                    status = fn(corr, arg)
            else:
                status = fn(corr)
            tx.Commit()
        except Exception as e:
            status = f"FAIL: {type(e).__name__}: {e}"
            log(traceback.format_exc())
            try:
                tx.Abort()
            except Exception:
                pass
        finally:
            try:
                tx.Dispose()
            except Exception:
                pass
        log(f"  {name:30s} [{label}] {status}")


log("=== build_corridor_surfaces ===")
log(f"started: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
log(f"link code: {LINK_CODE!r}  handles: {HANDLES_FILE!r}\n")

doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
civil_db = CivilApplication.ActiveDocument

lock = doc.LockDocument()
try:
    # collect corridor ObjectIds
    corr_ids: list[Any] = []
    tx0 = db.TransactionManager.StartTransaction()
    try:
        for raw in safe_iter(civil_db.CorridorCollection):
            corr_ids.append(raw)
        tx0.Commit()
    except Exception:
        tx0.Abort()
    finally:
        tx0.Dispose()

    log(f"Corridors: {len(corr_ids)}\n")

    outline_map = load_outline_map(db)
    log(f"Outline polylines from handle file: {len(outline_map)}\n")

    # build raw → pl_id map for pass 2
    raw_to_pl: dict[Any, Any] = {}
    tx_names = db.TransactionManager.StartTransaction()
    try:
        for raw in corr_ids:
            corr = tx_names.GetObject(raw, OpenMode.ForRead)
            pl_id = outline_map.get(corr.Name)
            if pl_id is not None:
                raw_to_pl[raw] = pl_id
        tx_names.Commit()
    except Exception:
        tx_names.Abort()
    finally:
        tx_names.Dispose()

    log("--- pass 1: link codes + break line + FL codes ---")
    run_pass(corr_ids, db, configure_codes, "codes")

    log("\n--- pass 2: boundary from outline polyline ---")
    run_pass(corr_ids, db, apply_boundary, "boundary", extra_args=raw_to_pl)

    log("\n=== DONE ===")

finally:
    try:
        lock.Dispose()
    except Exception:
        pass

OUT = LOG_FILE
