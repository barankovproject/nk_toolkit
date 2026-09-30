"""EXPERIMENT: anchor grid built on the SMOOTH median (no segments/seams).

Proposal 1: instead of the angle-simplified axis (sharp vertices -> seam gaps),
build perpendiculars along the dense median centreline using a smoothed local
tangent. The lines rotate gradually, so crossings stay evenly spaced and the
stagger is clean — no dividers, phase-lock, seam-overlap or territory needed.

Draws on its OWN layers (inf_md_anchor_grid2 / inf_md_anchor_pts2) so it can be
compared side by side with the production anchor_03/04 output.
"""

from __future__ import annotations

import datetime
import math
import os
import traceback
from typing import Any

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.Colors import Color, ColorMethod
from Autodesk.AutoCAD.DatabaseServices import (
    Circle,
    LayerTableRecord,
    OpenMode,
    Polyline,
)
from Autodesk.AutoCAD.Geometry import Point2d, Point3d, Vector3d

from anchor_02_build_axis.axis import (
    load_contours_by_elevation,
    longest_run,
    median_centerline,
)
from anchor_03_build_grid.grid import clip_to_band
from anchor_04_place_anchors.circles import fill_row, merge_overlaps, polyline_hits
from anchor_core.config import CONFIG

_HERE = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(_HERE, "logs")

HORIZ_LAYER = CONFIG.horiz_layer
GRID_LAYER = "inf_md_anchor_grid2"
PTS_LAYER = "inf_md_anchor_pts2"
LINE_STEP = CONFIG.line_step  # perpendicular spacing (alternating colours)
ROW_SPACING = CONFIG.step  # same-colour / row spacing
OVERHANG = CONFIG.overhang
DIAMETER = CONFIG.diameter
COLOR_EVEN = CONFIG.color_even
COLOR_ODD = CONFIG.color_odd
_TAN_WIN = CONFIG.line_step  # half-window for the smoothed tangent


def _unit(vx: float, vy: float) -> tuple[float, float]:
    n = math.hypot(vx, vy) or 1.0
    return (vx / n, vy / n)


def _perp(vx: float, vy: float) -> tuple[float, float]:
    return (-vy, vx)


def _cum(pts):
    c = [0.0]
    for i in range(len(pts) - 1):
        c.append(c[-1] + math.dist(pts[i], pts[i + 1]))
    return c


def _point_at(pts, cum, d):
    d = max(0.0, min(cum[-1], d))
    seg = 0
    while seg < len(pts) - 2 and cum[seg + 1] < d:
        seg += 1
    a, b = pts[seg], pts[seg + 1]
    span = cum[seg + 1] - cum[seg]
    t = 0.0 if span < 1e-9 else (d - cum[seg]) / span
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def _smooth_stations(pts, step):
    """Yield (position, smoothed unit tangent) every ``step`` along the line."""
    cum = _cum(pts)
    total = cum[-1]
    d = 0.0
    while d <= total + 1e-9:
        p0 = _point_at(pts, cum, d - _TAN_WIN)
        p1 = _point_at(pts, cum, d + _TAN_WIN)
        yield _point_at(pts, cum, d), _unit(p1[0] - p0[0], p1[1] - p0[1])
        d += step


class SmoothGridBuilder:
    def __init__(self) -> None:
        os.makedirs(LOG_DIR, exist_ok=True)
        self.log_file = os.path.join(
            LOG_DIR, f"exp_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
        )

    def log(self, msg: str = "") -> None:
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(msg + "\n")

    def _ensure_layer(self, db, tx, name, aci):
        lt = tx.GetObject(db.LayerTableId, OpenMode.ForRead)
        for lid in lt:
            if tx.GetObject(lid, OpenMode.ForRead).Name == name:
                return
        lt.UpgradeOpen()
        ltr = LayerTableRecord()
        ltr.Name = name
        ltr.Color = Color.FromColorIndex(ColorMethod.ByAci, aci)
        lt.Add(ltr)
        tx.AddNewlyCreatedDBObject(ltr, True)

    def run(self) -> str:
        self.log("=== anchor_exp_smooth_grid ===")
        self.log(f"started: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
        self.log(f"line step {LINE_STEP} m  row spacing {ROW_SPACING} m")

        doc = Application.DocumentManager.MdiActiveDocument
        db = doc.Database
        lock = doc.LockDocument()
        try:
            tx = db.TransactionManager.StartTransaction()
            try:
                groups = load_contours_by_elevation(tx, db, HORIZ_LAYER)
                tx.Commit()
            finally:
                tx.Dispose()

            elevs = sorted(groups)
            if len(elevs) < 2:
                raise Exception("need >=2 horizontals")
            lines = [longest_run(groups[e]) for e in elevs]
            smooth = median_centerline(lines)
            band = [longest_run(groups[elevs[0]]), longest_run(groups[elevs[-1]])]

            # rows: colour by elevation order (matches anchor_01)
            rows = []
            for i, e in enumerate(elevs):
                rows.append(
                    (longest_run(groups[e]), COLOR_EVEN if i % 2 == 0 else COLOR_ODD, e)
                )

            # perpendiculars along the smooth median
            perps = []  # (a, b, colour)
            for idx, (pos, tan) in enumerate(_smooth_stations(smooth, LINE_STEP)):
                seg = clip_to_band(pos, _perp(*tan), band, OVERHANG)
                if seg is not None:
                    perps.append(
                        (seg[0], seg[1], COLOR_EVEN if idx % 2 == 0 else COLOR_ODD)
                    )
            self.log(f"smooth pts {len(smooth)}  perpendiculars {len(perps)}")

            # anchors: same-colour crossings, simple row fill, merge overlaps
            circles = []
            for poly, h_color, elev in rows:
                hits = []
                for a, b, p_color in perps:
                    if p_color == h_color:
                        hits.extend(polyline_hits(poly, a, b))
                if not hits:
                    continue
                for x, y in fill_row(hits, poly, ROW_SPACING):
                    circles.append((x, y, h_color, elev))
            circles = merge_overlaps(circles, DIAMETER)

            self._draw(db, perps, circles)
            reds = sum(1 for c in circles if c[2] == COLOR_EVEN)
            self.log(
                f"\ncircles {len(circles)} ({reds} red, {len(circles) - reds} blue) "
                f"on {PTS_LAYER}; perps on {GRID_LAYER}"
            )
        finally:
            try:
                lock.Dispose()
            except Exception:
                pass
        self.log("=== DONE ===")
        return self.log_file

    def _draw(self, db, perps, circles):
        tx = db.TransactionManager.StartTransaction()
        try:
            self._ensure_layer(db, tx, GRID_LAYER, 8)
            self._ensure_layer(db, tx, PTS_LAYER, 8)
            ms = tx.GetObject(db.CurrentSpaceId, OpenMode.ForWrite)
            for oid in ms:
                ent = tx.GetObject(oid, OpenMode.ForRead)
                if isinstance(ent, (Polyline, Circle)) and ent.Layer in (
                    GRID_LAYER,
                    PTS_LAYER,
                ):
                    ent.UpgradeOpen()
                    ent.Erase()
            for a, b, col in perps:
                pl = Polyline()
                pl.AddVertexAt(0, Point2d(a[0], a[1]), 0.0, 0.0, 0.0)
                pl.AddVertexAt(1, Point2d(b[0], b[1]), 0.0, 0.0, 0.0)
                pl.Layer = GRID_LAYER
                pl.Color = Color.FromColorIndex(ColorMethod.ByAci, col)
                ms.AppendEntity(pl)
                tx.AddNewlyCreatedDBObject(pl, True)
            for x, y, col, elev in circles:
                c = Circle(Point3d(x, y, elev), Vector3d.ZAxis, DIAMETER / 2.0)
                c.Layer = PTS_LAYER
                c.Color = Color.FromColorIndex(ColorMethod.ByAci, col)
                ms.AppendEntity(c)
                tx.AddNewlyCreatedDBObject(c, True)
            tx.Commit()
        except Exception:
            tx.Abort()
            raise
        finally:
            tx.Dispose()
