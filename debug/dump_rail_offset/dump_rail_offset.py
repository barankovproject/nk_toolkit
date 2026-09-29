"""Dump what Polyline.GetOffsetCurves returns for the НК-1А-3 gabion outline.

draw_gabion_view._rail_placements fell back to fan with 'rail offset produced
nothing' — every offset candidate scored area 0 / <= base. Log, per offset
direction, every returned curve: type, Closed, vertex count, Area (or the
exception text if it throws), extents size, length.
"""

from __future__ import annotations

import clr, datetime, json, os, sys, traceback

clr.AddReference("AecBaseMgd")
clr.AddReference("AeccDbMgd")
clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import Polyline
from Autodesk.AutoCAD.Geometry import Point2d

_LIB_ROOT = r"C:\Arhyz\automation\scripts"
if _LIB_ROOT not in sys.path:
    sys.path.insert(0, _LIB_ROOT)

from civil.utils import normalize  # noqa: E402
from paths import CANALS_DATA_DIR  # noqa: E402

QUERY = "НК-1А-3"
OFFSET = 4.0  # LAYOUT.rail_offset

BASE = r"C:\Arhyz\automation\scripts\debug\dump_rail_offset"
LOG_DIR = os.path.join(BASE, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"dump_rail_offset_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)


def log(msg=""):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(str(msg) + "\n")


def load_outline(query):
    norm = normalize(query)
    path = None
    for fn in os.listdir(CANALS_DATA_DIR):
        if fn.endswith(".json") and normalize(fn[:-5]) == norm:
            path = os.path.join(CANALS_DATA_DIR, fn)
            break
    if path is None:
        return None
    sp = json.load(open(path, encoding="utf-8-sig")).get("section_points", {})
    keys = sorted(sp.keys(), key=lambda k: float(k))
    if len(keys) < 2:
        return None
    return [sp[k][8][:2] for k in keys] + [sp[k][5][:2] for k in reversed(keys)]


def describe(curve, label):
    log(f"  [{label}] type={type(curve).__name__}")
    try:
        log(f"    Closed={curve.Closed}")
    except Exception as e:
        log(f"    Closed -> EXC: {e}")
    try:
        log(f"    NumberOfVertices={curve.NumberOfVertices}")
    except Exception:
        pass
    try:
        log(f"    Area={float(curve.Area):.2f}")
    except Exception as e:
        log(f"    Area -> EXC: {e}")
    try:
        ext = curve.GeometricExtents
        w = ext.MaxPoint.X - ext.MinPoint.X
        h = ext.MaxPoint.Y - ext.MinPoint.Y
        log(f"    Extents {w:.2f} x {h:.2f}")
    except Exception as e:
        log(f"    Extents -> EXC: {e}")
    try:
        ln = float(curve.GetDistanceAtParameter(curve.EndParam))
        log(f"    Length={ln:.2f}")
    except Exception as e:
        log(f"    Length -> EXC: {e}")


def make_pline(pts):
    pl = Polyline()
    pl.SetDatabaseDefaults()
    for i, (x, y) in enumerate(pts):
        pl.AddVertexAt(i, Point2d(x, y), 0.0, 0.0, 0.0)
    pl.Closed = True
    return pl


def decimate(pts, tol):
    """Drop vertices closer than `tol` to the chord of their neighbours (collinear)."""
    out = [pts[0]]
    for k in range(1, len(pts) - 1):
        ax, ay = out[-1]
        bx, by = pts[k]
        cx, cy = pts[k + 1]
        dx, dy = cx - ax, cy - ay
        m = (dx * dx + dy * dy) ** 0.5 or 1.0
        d = abs((bx - ax) * dy - (by - ay) * dx) / m
        if d > tol:
            out.append(pts[k])
    out.append(pts[-1])
    return out


def try_offset(pts, dist, label):
    pl = make_pline(pts)
    try:
        curves = pl.GetOffsetCurves(dist)
        info = []
        for c in curves:
            try:
                a = f"area={float(c.Area):.1f}"
            except Exception as e:
                a = f"area EXC: {e}"
            try:
                cl = c.Closed
            except Exception:
                cl = "?"
            info.append(f"{type(c).__name__}(closed={cl}, {a})")
        log(f"  {label}: dist={dist} -> {len(info)} curve(s) {info}")
    except Exception as e:
        log(f"  {label}: dist={dist} -> EXC: {e}")
    finally:
        pl.Dispose()


def main():
    loop = load_outline(QUERY)
    if not loop:
        log(f"no section_points for '{QUERY}'")
        return
    log(f"'{QUERY}': {len(loop)} outline verts, OFFSET={OFFSET}")

    # 1. does the gap type matter? (1=fillet is what the script uses)
    for gt in (1, 0, 2):
        Application.SetSystemVariable("OFFSETGAPTYPE", gt)
        try_offset(loop, OFFSET, f"gaptype={gt}, full loop")

    # 2. does the distance matter? (fillet)
    Application.SetSystemVariable("OFFSETGAPTYPE", 1)
    for dist in (0.5, 1.0, 2.0, 3.0):
        try_offset(loop, dist, "gaptype=1, full loop")

    # 3. does decimation help? (fillet, full distance)
    for tol in (0.01, 0.05, 0.20):
        dec = decimate(loop, tol)
        log(f"  decimated tol={tol}: {len(loop)} -> {len(dec)} verts")
        try_offset(dec, OFFSET, f"gaptype=1, decimated tol={tol}")


log("=== DUMP RAIL OFFSET ===")
try:
    main()
    log("=== DONE ===")
except Exception as e:
    log(f"ERROR: {e}")
    log(traceback.format_exc())

OUT = LOG_FILE
