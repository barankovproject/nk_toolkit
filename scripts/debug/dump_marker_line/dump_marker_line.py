"""Dump user-drawn 3D lines/polylines on inf_md_marker: geometry, slope, station/offset.

The user drew the desired ditch axis by hand at a problem station. This reads every
Line / Polyline3d / Polyline on inf_md_marker, logs its vertices (x,y,z), 2D length,
longitudinal slope (dz / 2D-length), bearing, and projects both ends onto the active
alignment to get their station + offset — so we can see exactly what orientation and
end points achieve the OK slope, vs what the solver produces.
"""

from __future__ import annotations

import clr
import datetime
import math
import os
import sys
import traceback

clr.AddReference("AeccDbMgd")
clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import (
    OpenMode,
    Line,
    Polyline,
    Polyline3d,
    SymbolUtilityServices,
)

_SCRIPTS_ROOT = r"C:\Arhyz\automation\scripts\ditch"
if _SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, _SCRIPTS_ROOT)
_AUTOMATION = r"C:\Arhyz\automation"
if _AUTOMATION not in sys.path:
    sys.path.insert(0, _AUTOMATION)

from ditch_core.config import CONFIG
from ditch_core.selection import find_alignment_and_surface

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\dump_marker_line\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"dump_marker_line_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)
MARKER_LAYER = "inf_md_marker"


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def _verts(ent, tx):
    pts = []
    if isinstance(ent, Line):
        s, e = ent.StartPoint, ent.EndPoint
        pts = [(s.X, s.Y, s.Z), (e.X, e.Y, e.Z)]
    elif isinstance(ent, Polyline3d):
        for vid in ent:
            v = tx.GetObject(vid, OpenMode.ForRead)
            p = v.Position
            pts.append((p.X, p.Y, p.Z))
    elif isinstance(ent, Polyline):
        for i in range(ent.NumberOfVertices):
            p = ent.GetPoint3dAt(i)
            pts.append((p.X, p.Y, p.Z))
    return pts


def _station_offset(align, x, y):
    try:
        res = align.StationOffsetAcceptOutOfRange(x, y, 0.0, 0.0, False)
        if isinstance(res, tuple) and len(res) >= 3:
            return float(res[-3]), float(res[-2])
    except Exception:
        pass
    try:
        res = align.StationOffset(x, y, 0.0, 0.0)
        if isinstance(res, tuple) and len(res) >= 2:
            return float(res[-2]), float(res[-1])
    except Exception:
        pass
    return None, None


def _safe_elev(surface, x, y):
    try:
        return float(surface.FindElevationAtXY(x, y))
    except Exception:
        return None


doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
log(f"=== dump_marker_line {datetime.datetime.now():%Y-%m-%d %H:%M:%S} ===")

lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        align, surface = find_alignment_and_surface(
            tx, CONFIG.alignment_name, CONFIG.surface_name
        )
        log(f"alignment '{align.Name}', surface '{surface.Name}'")

        ms = tx.GetObject(
            SymbolUtilityServices.GetBlockModelSpaceId(db), OpenMode.ForRead
        )
        found = 0
        for oid in ms:
            ent = tx.GetObject(oid, OpenMode.ForRead)
            try:
                layer = ent.Layer
            except Exception:
                continue
            if layer != MARKER_LAYER:
                continue
            if not isinstance(ent, (Line, Polyline3d, Polyline)):
                log(
                    f"\n[{type(ent).__name__}] on {layer}: not a line/polyline, skipped"
                )
                continue
            pts = _verts(ent, tx)
            if len(pts) < 2:
                continue
            found += 1
            log("")
            log("-" * 70)
            log(f"#{found} {type(ent).__name__} on {layer}, {len(pts)} vertices")
            for i, (x, y, z) in enumerate(pts):
                sta, off = _station_offset(align, x, y)
                surf_z = _safe_elev(surface, x, y)
                sta_s = f"{sta:.2f}" if sta is not None else "None"
                off_s = f"{off:+.2f}" if off is not None else "None"
                sz_s = f"{surf_z:.2f}" if surf_z is not None else "None"
                log(
                    f"  v{i}: ({x:.2f},{y:.2f}, z={z:.3f})  station={sta_s} "
                    f"offset={off_s}  surface_z={sz_s}"
                )
            a, b = pts[0], pts[-1]
            len2d = math.hypot(b[0] - a[0], b[1] - a[1])
            len3d = math.sqrt(
                (b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2 + (b[2] - a[2]) ** 2
            )
            dz = a[2] - b[2]
            slope = abs(dz) / len2d if len2d > 1e-6 else float("nan")
            bearing = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
            sta_a, _ = _station_offset(align, a[0], a[1])
            sta_b, _ = _station_offset(align, b[0], b[1])
            d_sta = (
                (sta_b - sta_a)
                if (sta_a is not None and sta_b is not None)
                else float("nan")
            )
            log(
                f"  end-to-end: len2d={len2d:.2f} len3d={len3d:.2f} dz={dz:+.3f} "
                f"slope={slope:.4f}"
            )
            log(
                f"  bearing={bearing:.1f}deg  d_station(end-start)={d_sta:+.2f} "
                f"(how far along the trasse the far end sits)"
            )
            # skew vs the alignment normal at the start station
            try:
                from civil.alignment import AlignmentWrapper

                aw = AlignmentWrapper(align, float(align.EndingStation))
                if sta_a is not None:
                    nx, ny = aw.cross_axis_at(
                        max(
                            float(align.StartingStation),
                            min(float(align.EndingStation), sta_a),
                        )
                    )
                    dx, dy = (b[0] - a[0]), (b[1] - a[1])
                    dn = math.hypot(dx, dy)
                    if dn > 1e-6:
                        cosang = abs((dx * nx + dy * ny) / dn)
                        cosang = max(-1.0, min(1.0, cosang))
                        skew = math.degrees(math.acos(cosang))
                        log(f"  skew from axis-normal at start: ~{skew:.1f}deg")
            except Exception as e:
                log(f"  (skew calc failed: {e})")

        log(f"\nfound {found} marker line(s) on {MARKER_LAYER}")
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
