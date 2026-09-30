"""Place anchor circles at same-colour grid crossings (staggered), Ø1.

Reads the coloured horizontals (inf_md_anchor) and the coloured perpendiculars
(inf_md_anchor_grid), keeps only same-colour crossings, fills row gaps wider than
the grid step, merges overlaps, and draws Ø1 circles on inf_md_anchor_pts.
No interactive pick — re-run while tuning.
"""

from __future__ import annotations

import datetime
import json
import os
import traceback
from typing import Any

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.Colors import Color, ColorMethod
from Autodesk.AutoCAD.DatabaseServices import Circle, OpenMode, Polyline
from Autodesk.AutoCAD.Geometry import Point3d, Vector3d

from anchor_04_place_anchors.circles import place_anchors
from anchor_04_place_anchors.layers import (
    ensure_pts_filter,
    ensure_pts_layers,
    pts_layer_name,
)
from anchor_core.config import CONFIG

_HERE = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(_HERE, "logs")
JSON_FILE = os.path.join(_HERE, "anchor_points.json")
GRID_JSON = os.path.join(
    os.path.dirname(_HERE), "anchor_03_build_grid", "anchor_grid.json"
)

HORIZ_LAYER = CONFIG.horiz_layer  # coloured horizontals (anchor_01)
GRID_LAYER = CONFIG.grid_layer  # coloured perpendiculars (anchor_03)
DIAMETER = CONFIG.diameter
RADIUS = DIAMETER / 2.0
LINE_STEP = CONFIG.line_step  # actual perpendicular spacing (alternating colours)
ROW_SPACING = CONFIG.step  # target spacing of anchors along a row (same-colour step)
MAX_ROW_GAP = ROW_SPACING * CONFIG.max_gap_factor  # a gap above this is a hole -> fill
CENTER_BELOW = ROW_SPACING * 0.7  # relax an anchor crammed closer than this
MAX_SHIFT = CONFIG.max_shift  # cap on how far relaxing may move an anchor
MERGE_DIST = ROW_SPACING / 2.0  # merge a same-row pair (doubling) closer than this


class AnchorPointsBuilder:
    def __init__(self) -> None:
        os.makedirs(LOG_DIR, exist_ok=True)
        self.log_file = os.path.join(
            LOG_DIR, f"build_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
        )

    def log(self, msg: str = "", level: str = "INFO") -> None:
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(f"{level}: {msg}\n" if level != "INFO" else f"{msg}\n")

    def _read_horizontals(self, tx: Any, db: Any) -> list[Any]:
        """Return the coloured horizontals (pts, colour, elevation)."""
        horizontals: list[Any] = []
        ms = tx.GetObject(db.CurrentSpaceId, OpenMode.ForRead)
        for oid in ms:
            ent = tx.GetObject(oid, OpenMode.ForRead)
            if isinstance(ent, Polyline) and ent.Layer == HORIZ_LAYER:
                pts = [
                    (ent.GetPoint2dAt(i).X, ent.GetPoint2dAt(i).Y)
                    for i in range(int(ent.NumberOfVertices))
                ]
                horizontals.append((pts, ent.Color.ColorIndex, float(ent.Elevation)))
        return horizontals

    def _read_grid(self):
        """Load the grid lines + axis + divider normals from anchor_03's JSON."""
        with open(GRID_JSON, encoding="utf-8") as f:
            data = json.load(f)
        lines = [
            {
                "a": (ln["a"][0], ln["a"][1]),
                "b": (ln["b"][0], ln["b"][1]),
                "seg": ln["seg"],
                "color": ln["color"],
            }
            for ln in data.get("lines", [])
        ]
        axis = [(p[0], p[1]) for p in data.get("axis", [])]
        dnorms = {
            int(k): (v[0], v[1]) for k, v in data.get("divider_normals", {}).items()
        }
        return lines, axis, dnorms

    def _draw(
        self,
        db: Any,
        circles: list[tuple[float, float, int, float]],
        layer: str,
    ) -> list[str]:
        handles: list[str] = []
        tx = db.TransactionManager.StartTransaction()
        try:
            ms = tx.GetObject(db.CurrentSpaceId, OpenMode.ForWrite)
            # Idempotent re-run: clear existing circles on the layer first.
            for oid in ms:
                ent = tx.GetObject(oid, OpenMode.ForRead)
                if isinstance(ent, Circle) and ent.Layer == layer:
                    ent.UpgradeOpen()
                    ent.Erase()
            for x, y, color, elev in circles:
                c = Circle(Point3d(x, y, elev), Vector3d.ZAxis, RADIUS)
                c.Layer = layer
                c.Color = Color.FromColorIndex(ColorMethod.ByAci, color)
                ms.AppendEntity(c)
                tx.AddNewlyCreatedDBObject(c, True)
                handles.append(c.Handle.ToString())
            tx.Commit()
        except Exception:
            tx.Abort()
            raise
        finally:
            tx.Dispose()
        return handles

    def run(self) -> str:
        self.log("=== anchor_04_place_anchors ===")
        self.log(f"started: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
        line_step = LINE_STEP
        self.log(
            f"horiz: {HORIZ_LAYER}  grid: {GRID_LAYER}  "
            f"line step: {line_step} m  d: {DIAMETER}"
        )

        doc = Application.DocumentManager.MdiActiveDocument
        db = doc.Database

        lock = doc.LockDocument()
        result: dict[str, Any] = {}
        try:
            layer = self._ensure_layers(db)

            tx = db.TransactionManager.StartTransaction()
            try:
                horizontals = self._read_horizontals(tx, db)
                tx.Commit()
            finally:
                tx.Dispose()
            grid_lines, axis, dnorms = self._read_grid()
            self.log(
                f"horizontals: {len(horizontals)}  grid lines: {len(grid_lines)}  "
                f"axis verts: {len(axis)}  dividers: {len(dnorms)}"
            )

            self.log(
                f"row spacing {ROW_SPACING} m  max gap {MAX_ROW_GAP:.2f} m  "
                f"centre below {CENTER_BELOW:.2f} m  max shift {MAX_SHIFT} m"
            )
            circles = place_anchors(
                horizontals,
                grid_lines,
                axis,
                dnorms,
                ROW_SPACING,
                MAX_ROW_GAP,
                CENTER_BELOW,
                MAX_SHIFT,
                MERGE_DIST,
            )
            reds = sum(1 for c in circles if c[2] == 1)
            blues = sum(1 for c in circles if c[2] == 5)
            handles = self._draw(db, circles, layer)
            result = {
                "layer": layer,
                "diameter": DIAMETER,
                "line_step": line_step,
                "row_spacing": ROW_SPACING,
                "count": len(handles),
                "red": reds,
                "blue": blues,
                "handles": handles,
            }
            self.log(f"\ncircles: {len(handles)} ({reds} red, {blues} blue) on {layer}")
        finally:
            try:
                lock.Dispose()
            except Exception:
                pass

        with open(JSON_FILE, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        self.log(f"wrote {JSON_FILE}")
        self.log("=== DONE ===")
        return self.log_file

    def _ensure_layers(self, db: Any) -> str:
        tx = db.TransactionManager.StartTransaction()
        try:
            ensure_pts_layers(db, tx)
            tx.Commit()
        finally:
            tx.Dispose()
        ensure_pts_filter(db)
        return pts_layer_name()
