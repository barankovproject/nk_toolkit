"""Diagnose why AlignmentWrapper.station_offset_at returns None for every ditch sample.

Resolves the В-5А-1 alignment, then for a few points that lie EXACTLY on it
(GetPointAtDist at start / mid / end) tries every StationOffset call convention and
logs the result or the exact exception. If an on-alignment point can't be projected,
the bug is in the API call (pythonnet out-params); if it projects fine, the drawn
bottom line is simply not near this alignment.
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

import sys

for p in (r"C:\Arhyz\automation", r"C:\Arhyz\automation\scripts"):
    if p not in sys.path:
        sys.path.insert(0, p)

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import (
    OpenMode,
    Polyline,
    Polyline2d,
    Polyline3d,
    SymbolUtilityServices,
)
from Autodesk.Civil.ApplicationServices import CivilApplication

from civil.utils import find_best_match

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\dump_station_offset\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"dump_station_offset_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)

_QUERY = "В-5А-1"


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def try_tuple(align, x, y, method):
    """Call align.<method>(x, y) expecting a tuple of out-params."""
    fn = getattr(align, method, None)
    if fn is None:
        return f"{method}: NO SUCH METHOD"
    try:
        res = fn(float(x), float(y))
    except Exception as e:
        return f"{method}(tuple): EXC {type(e).__name__}: {e}"
    try:
        return f"{method}(tuple): res_type={type(res).__name__} res={res} -> [0]={float(res[0]):.3f} [1]={float(res[1]):.3f}"
    except Exception as e:
        return f"{method}(tuple): res_type={type(res).__name__} res={res} (index failed: {e})"


def try_seed(align, x, y):
    """Seed-value convention (the one AlignmentWrapper now uses)."""
    try:
        res = align.StationOffsetAcceptOutOfRange(float(x), float(y), 0.0, 0.0, False)
        if isinstance(res, tuple) and len(res) >= 3:
            return f"seed OK: st={float(res[-3]):.3f} of={float(res[-2]):.3f} res={res}"
        return f"seed: unexpected res_type={type(res).__name__} res={res}"
    except Exception as e:
        return f"seed: EXC {type(e).__name__}: {e}"


doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        civil_db = CivilApplication.ActiveDocument
        aligns = []
        for oid in civil_db.GetAlignmentIds():
            try:
                aligns.append(tx.GetObject(oid, OpenMode.ForRead))
            except Exception:
                continue
        names = [a.Name for a in aligns]
        log(f"alignments ({len(names)}): {names}")
        match = find_best_match(_QUERY, names)
        if match is None:
            log(f"NO MATCH for '{_QUERY}'")
        else:
            align = aligns[match[0]]
            log(f"matched '{match[1]}'")
            s0 = float(align.StartingStation)
            s1 = float(align.EndingStation)
            log(f"stations: {s0:.3f} .. {s1:.3f}")

            for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
                sta = s0 + (s1 - s0) * frac
                try:
                    pt = align.GetPointAtDist(sta)
                    x, y = float(pt.X), float(pt.Y)
                except Exception as e:
                    log(f"\nsta {sta:.3f}: GetPointAtDist FAILED {e}")
                    continue
                log(
                    f"\n=== on-alignment point at sta {sta:.3f}: X={x:.3f} Y={y:.3f} ==="
                )
                log("  " + try_seed(align, x, y))

            # --- enumerate every model-space polyline and project its midpoint ---
            log("\n\n=== model-space polylines vs alignment ===")
            ms = tx.GetObject(
                SymbolUtilityServices.GetBlockModelSpaceId(db), OpenMode.ForRead
            )
            n_pl = 0
            for oid in ms:
                ent = tx.GetObject(oid, OpenMode.ForRead)
                if not isinstance(ent, (Polyline, Polyline2d, Polyline3d)):
                    continue
                n_pl += 1
                # collect XY vertices
                pts = []
                if isinstance(ent, Polyline):
                    for i in range(ent.NumberOfVertices):
                        p = ent.GetPoint3dAt(i)
                        pts.append((float(p.X), float(p.Y)))
                else:
                    for vid in ent:
                        try:
                            p = tx.GetObject(vid, OpenMode.ForRead).Position
                            pts.append((float(p.X), float(p.Y)))
                        except Exception:
                            continue
                if len(pts) < 2:
                    continue
                mx, my = pts[len(pts) // 2]
                proj = try_seed(align, mx, my)
                log(
                    f"\n[{ent.GetType().Name} h={ent.Handle} layer='{ent.Layer}' "
                    f"nverts={len(pts)}]"
                )
                log(f"  first={pts[0]} mid=({mx:.2f},{my:.2f}) last={pts[-1]}")
                log(f"  midproj: {proj}")
            log(f"\ntotal polylines scanned: {n_pl}")

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
