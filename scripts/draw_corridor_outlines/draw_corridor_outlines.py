"""Build a closed 2D polyline around each corridor using Daylight feature lines.

For each corridor:
  1. Get the two Daylight CorridorFeatureLine objects (left and right sides).
  2. Read XY from FeatureLinePoint.XYZ on each.
  3. Identify which is right (positive Offset) and which is left (negative Offset).
  4. Build closed Polyline: right side forward + left side reversed.
  5. Fix self-intersections at corridor ends.
  6. Delete any existing polyline tagged with this corridor name (overwrite).
  7. Add new polyline to model space on OUTLINE_LAYER with XData tag.

XData app: ARHYZ_CORR, code 1000 = corridor name.
This tag is used by build_corridor_surfaces to find the boundary polyline per corridor.
"""

from __future__ import annotations

import clr
import datetime
import os
import sys
import traceback
from typing import Any

clr.AddReference("AecBaseMgd")
clr.AddReference("AeccDbMgd")
clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

import json

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import (
    BlockTableRecord,
    LayerTableRecord,
    OpenMode,
    Polyline,
)
from Autodesk.AutoCAD.Geometry import Point2d
from Autodesk.Civil.ApplicationServices import CivilApplication

_LIB_ROOT = r"C:\Arhyz\automation\scripts"
if _LIB_ROOT not in sys.path:
    sys.path.insert(0, _LIB_ROOT)

from civil.utils import safe_iter, safe_resolve  # noqa: E402

LOG_DIR = r"C:\Arhyz\automation\scripts\draw_corridor_outlines\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, f"build_{datetime.datetime.now():%Y%m%d_%H%M%S}.log")

OUTLINE_LAYER = "inf_model_corridors"
FL_CODE = "Daylight"
HANDLES_FILE = (
    r"C:\Arhyz\automation\scripts\draw_corridor_outlines\corridor_outlines.json"
)


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def ensure_layer(db: Any, tx: Any, layer_name: str) -> None:
    lt = tx.GetObject(db.LayerTableId, OpenMode.ForRead)
    if lt.Has(layer_name):
        return
    lt_w = tx.GetObject(db.LayerTableId, OpenMode.ForWrite)
    ltr = LayerTableRecord()
    ltr.Name = layer_name
    lt_w.Add(ltr)
    tx.AddNewlyCreatedDBObject(ltr, True)


def load_handles() -> dict[str, str]:
    try:
        with open(HANDLES_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_handles(data: dict[str, str]) -> None:
    with open(HANDLES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_daylight_fls(corr: Any) -> list[Any]:
    try:
        bl = list(corr.Baselines)[0]
        fl_map = bl.MainBaselineFeatureLines.FeatureLineCollectionMap
        return list(fl_map[FL_CODE])
    except Exception:
        return []


def fl_xy_points(fl: Any) -> list[tuple[float, float]]:
    pts = []
    for fp in fl.FeatureLinePoints:
        xyz = fp.XYZ
        pts.append((xyz.X, xyz.Y))
    return pts


def seg_intersect_2d(
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    p4: tuple[float, float],
) -> tuple[float, float] | None:
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4
    dx12 = x2 - x1
    dy12 = y2 - y1
    dx34 = x4 - x3
    dy34 = y4 - y3
    denom = dx12 * dy34 - dy12 * dx34
    if abs(denom) < 1e-10:
        return None
    t = ((x3 - x1) * dy34 - (y3 - y1) * dx34) / denom
    u = ((x3 - x1) * dy12 - (y3 - y1) * dx12) / denom
    if 0.0 < t < 1.0 and 0.0 < u < 1.0:
        return (x1 + t * dx12, y1 + t * dy12)
    return None


def fix_self_intersections(
    pts: list[tuple[float, float]],
) -> tuple[list[tuple[float, float]], int]:
    """Repair self-intersecting closed polygon: replace crossing segment pair with their intersection point."""
    fixes = 0
    for _ in range(20):
        n = len(pts)
        found = False
        for i in range(n):
            i1 = (i + 1) % n
            for j in range(i + 2, n):
                j1 = (j + 1) % n
                if j1 == i:  # adjacent at wrap-around
                    continue
                p = seg_intersect_2d(pts[i], pts[i1], pts[j], pts[j1])
                if p is None:
                    continue
                # Remove the shorter loop: vertices between the two crossing segments.
                loop_a = j - i  # vertices i+1..j
                loop_b = n - loop_a  # vertices j+1..n-1 + 0..i
                if loop_a <= loop_b:
                    pts = pts[: i + 1] + [p] + pts[j + 1 :]
                else:
                    pts = pts[i + 1 : j + 1] + [p]
                fixes += 1
                found = True
                break
            if found:
                break
        if not found:
            break
    return pts, fixes


def build_outline(
    corr: Any,
    db: Any,
    tx: Any,
    existing_map: dict[str, Any],
    handles: dict[str, str],
) -> str:
    name = corr.Name
    fls = get_daylight_fls(corr)
    if len(fls) < 2:
        return f"SKIP (only {len(fls)} Daylight FL)"

    def first_offset(fl: Any) -> float:
        for fp in fl.FeatureLinePoints:
            return float(fp.Offset)
        return 0.0

    off0 = first_offset(fls[0])
    off1 = first_offset(fls[1])
    if off0 >= 0 and off1 < 0:
        fl_r, fl_l = fls[0], fls[1]
    elif off1 >= 0 and off0 < 0:
        fl_r, fl_l = fls[1], fls[0]
    else:
        fl_r, fl_l = fls[0], fls[1]

    pts_r = fl_xy_points(fl_r)
    pts_l = fl_xy_points(fl_l)
    if not pts_r or not pts_l:
        return "SKIP (empty FL points)"

    outline = pts_r + list(reversed(pts_l))
    outline, n_fixes = fix_self_intersections(outline)

    # delete existing polyline for this corridor (overwrite)
    if name in existing_map:
        old = tx.GetObject(existing_map[name], OpenMode.ForWrite)
        old.Erase()

    pl = Polyline()
    pl.Layer = OUTLINE_LAYER
    for i, (x, y) in enumerate(outline):
        pl.AddVertexAt(i, Point2d(x, y), 0, 0, 0)
    pl.Closed = True

    bt = tx.GetObject(db.BlockTableId, OpenMode.ForRead)
    ms = tx.GetObject(bt.get_Item(BlockTableRecord.ModelSpace), OpenMode.ForWrite)
    ms.AppendEntity(pl)
    tx.AddNewlyCreatedDBObject(pl, True)

    # store handle for use by build_corridor_surfaces
    handles[name] = pl.Handle.ToString()

    fix_note = f"  fixed {n_fixes} crossing(s)" if n_fixes else ""
    return f"OK ({len(outline)} vertices{fix_note})"


log("=== draw_corridor_outlines ===")
log(f"started: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
log(f"layer: {OUTLINE_LAYER}  code: {FL_CODE!r}\n")

doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
civil_db = CivilApplication.ActiveDocument

results: list[str] = []
handles: dict[str, str] = {}
lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        ensure_layer(db, tx, OUTLINE_LAYER)

        # load existing handle map to find polylines to overwrite
        old_handles = load_handles()
        existing_map: dict[str, Any] = {}
        for cname, hstr in old_handles.items():
            try:
                from Autodesk.AutoCAD.DatabaseServices import Handle as AcHandle

                oid = db.GetObjectId(False, AcHandle(int(hstr, 16)), 0)
                if not oid.IsNull:
                    existing_map[cname] = oid
            except Exception:
                pass

        cc = civil_db.CorridorCollection
        log(
            f"Corridors: {cc.Count}  existing outlines to overwrite: {len(existing_map)}\n"
        )

        for raw in safe_iter(cc):
            corr = safe_resolve(raw, tx)
            if corr is None:
                continue
            name = corr.Name
            try:
                status = build_outline(corr, db, tx, existing_map, handles)
            except Exception as e:
                status = f"FAIL: {type(e).__name__}: {e}"
                log(traceback.format_exc())
            line = f"  {name:30s} {status}"
            log(line)
            results.append(line)

        ok = sum(1 for r in results if "OK" in r)
        skip = sum(1 for r in results if "SKIP" in r)
        fail = len(results) - ok - skip
        log(f"\n--- {ok} OK, {skip} skipped, {fail} failed ---")

        tx.Commit()
        log("transaction committed")
        save_handles(handles)
        log(f"handles saved: {len(handles)} corridors")
    except Exception as e:
        log(f"\nERROR: {e}\n{traceback.format_exc()}")
        try:
            tx.Abort()
        except Exception:
            pass
    finally:
        try:
            tx.Dispose()
        except Exception:
            pass
finally:
    try:
        lock.Dispose()
    except Exception:
        pass

log("=== DONE ===")
OUT = "\n".join(results)
