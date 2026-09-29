"""Build the median anchor axis from the horizontals drawn by anchor_01.

Reads every polyline on the source layer (inf_md_anchor), groups them by
elevation, builds one median line through the whole set, simplifies it by turn
angle (vertices only where the line bends more than ANGLE_TOL, no segment shorter
than MIN_SEGMENT), and draws it on the axis layer. No interactive pick — fully
driven by what is in the drawing, so it can be re-run while tuning the params;
the previous axis on the layer is cleared each run.
"""

from __future__ import annotations

import datetime
import json
import math
import os
import traceback
from typing import Any

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import OpenMode, Polyline
from Autodesk.AutoCAD.Geometry import Point2d

from anchor_02_build_axis.axis import (
    load_contours_by_elevation,
    longest_run,
    median_centerline,
    simplify_by_angle,
)
from anchor_02_build_axis.layers import (
    axis_layer_name,
    ensure_axis_filter,
    ensure_axis_layers,
)
from anchor_core.config import CONFIG

_HERE = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(_HERE, "logs")
JSON_FILE = os.path.join(_HERE, "anchor_axis.json")

SRC_LAYER = CONFIG.horiz_layer  # horizontals drawn by anchor_01
MIN_SEGMENT = CONFIG.min_segment  # floor on axis segment length (metres)
ANGLE_TOL = CONFIG.angle_tol_deg  # break the axis where it turns more than this


class AnchorAxisBuilder:
    def __init__(self) -> None:
        os.makedirs(LOG_DIR, exist_ok=True)
        self.log_file = os.path.join(
            LOG_DIR, f"build_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
        )

    def log(self, msg: str = "", level: str = "INFO") -> None:
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(f"{level}: {msg}\n" if level != "INFO" else f"{msg}\n")

    def _ensure_layers(self, db: Any) -> str:
        tx = db.TransactionManager.StartTransaction()
        try:
            ensure_axis_layers(db, tx)
            tx.Commit()
        finally:
            tx.Dispose()
        ensure_axis_filter(db)
        return axis_layer_name()

    def _draw_axis(
        self, db: Any, pts: list[tuple[float, float]], elevation: float, layer: str
    ) -> str:
        tx = db.TransactionManager.StartTransaction()
        try:
            ms = tx.GetObject(db.CurrentSpaceId, OpenMode.ForWrite)
            # Idempotent re-run: clear any existing axis on the layer first.
            for oid in ms:
                ent = tx.GetObject(oid, OpenMode.ForRead)
                if isinstance(ent, Polyline) and ent.Layer == layer:
                    ent.UpgradeOpen()
                    ent.Erase()
            pl = Polyline()
            for i, (x, y) in enumerate(pts):
                pl.AddVertexAt(i, Point2d(x, y), 0.0, 0.0, 0.0)
            pl.Elevation = elevation
            pl.Layer = layer
            ms.AppendEntity(pl)
            tx.AddNewlyCreatedDBObject(pl, True)
            handle = pl.Handle.ToString()
            tx.Commit()
            return handle
        except Exception:
            tx.Abort()
            raise
        finally:
            tx.Dispose()

    def run(self) -> str:
        self.log("=== anchor_02_build_axis ===")
        self.log(f"started: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
        self.log(
            f"source layer: {SRC_LAYER}  min segment: {MIN_SEGMENT} m  "
            f"angle tol: {ANGLE_TOL} deg"
        )

        doc = Application.DocumentManager.MdiActiveDocument
        db = doc.Database

        lock = doc.LockDocument()
        result: dict[str, Any] = {}
        try:
            layer = self._ensure_layers(db)

            tx = db.TransactionManager.StartTransaction()
            try:
                groups = load_contours_by_elevation(tx, db, SRC_LAYER)
                tx.Commit()
            finally:
                tx.Dispose()

            elevs = sorted(groups)
            self.log(f"elevations found: {elevs}")
            for e in elevs:
                runs = groups[e]
                if len(runs) > 1:
                    self.log(f"  elev {e}: {len(runs)} runs -> using longest", "WARN")

            if len(elevs) < 2:
                raise Exception(
                    f"Need >=2 horizontals on {SRC_LAYER}; found {len(elevs)}."
                )

            lines = [longest_run(groups[e]) for e in elevs]
            centre = median_centerline(lines)

            # Sweep so the angle tolerance can be picked from the counts.
            self.log("\nangle sweep (min segment kept):")
            for tol in (5, 8, 10, 12, 15, 20):
                sw = simplify_by_angle(centre, float(tol), MIN_SEGMENT)
                seg = min(
                    (math.dist(sw[i], sw[i + 1]) for i in range(len(sw) - 1)),
                    default=0.0,
                )
                self.log(
                    f"  {tol:2d} deg -> {len(sw):2d} vertices, "
                    f"{len(sw) - 1:2d} segments, shortest {seg:.2f} m"
                )

            axis_pts = simplify_by_angle(centre, ANGLE_TOL, MIN_SEGMENT)
            mean_elev = sum(elevs) / len(elevs)

            seg_len = sum(
                math.dist(axis_pts[i], axis_pts[i + 1])
                for i in range(len(axis_pts) - 1)
            )
            handle = self._draw_axis(db, axis_pts, mean_elev, layer)
            result = {
                "axis_handle": handle,
                "layer": layer,
                "elevation": mean_elev,
                "source_elevations": elevs,
                "min_segment": MIN_SEGMENT,
                "angle_tol": ANGLE_TOL,
                "vertices": len(axis_pts),
                "segments": len(axis_pts) - 1,
                "length": seg_len,
            }
            self.log(
                f"\naxis: {len(axis_pts)} vertices, {len(axis_pts) - 1} segments, "
                f"length {seg_len:.3f} m, elev {mean_elev:g}, handle {handle}"
            )
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
