"""Build the perpendicular anchor grid from the median axis + boundary.

Reads the axis off layer inf_md_anchor_axis and the boundary polygon from
anchor_01's anchor_surfaces.json, then draws a normal line every STEP metres
along the axis, clipped to the boundary and extended by OVERHANG. Lines alternate
red/blue like the horizontals. No interactive pick — re-run while tuning.
"""

from __future__ import annotations

import datetime
import json
import math
import os
import traceback
from typing import Any

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.Colors import Color, ColorMethod
from Autodesk.AutoCAD.DatabaseServices import OpenMode, Polyline
from Autodesk.AutoCAD.Geometry import Point2d

from anchor_03_build_grid.grid import (
    build_dividers,
    build_phase_locked,
    divider_dirs,
    divider_normals,
    load_axis,
    load_band_contours,
)
from anchor_03_build_grid.layers import (
    ensure_grid_filter,
    ensure_grid_layers,
    grid_layer_name,
)
from anchor_core.config import CONFIG

_HERE = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(_HERE, "logs")
JSON_FILE = os.path.join(_HERE, "anchor_grid.json")

AXIS_LAYER = CONFIG.axis_layer  # median axis drawn by anchor_02
HORIZ_LAYER = CONFIG.horiz_layer  # horizontals; outer ones bound the band
DIV_LAYER = CONFIG.div_layer  # region separators (bisectors at axis vertices)
STEP = CONFIG.step  # spacing of SAME-colour lines (m); lines alternate at STEP/2
OVERHANG = CONFIG.overhang  # extension past the outer contours (m/end)
SEAM_OVERLAP = CONFIG.seam_overlap  # how far lines run past their territory
COLOR_EVEN = CONFIG.color_even  # red (ACI)
COLOR_ODD = CONFIG.color_odd  # blue (ACI)


class AnchorGridBuilder:
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
            ensure_grid_layers(db, tx)
            tx.Commit()
        finally:
            tx.Dispose()
        ensure_grid_filter(db)
        return grid_layer_name()

    def _draw(
        self,
        db: Any,
        perps: list[tuple[tuple[float, float], tuple[float, float]]],
        dividers: list[tuple[tuple[float, float], tuple[float, float]]],
        elevation: float,
        layer: str,
    ) -> list[str]:
        handles: list[str] = []
        tx = db.TransactionManager.StartTransaction()
        try:
            ms = tx.GetObject(db.CurrentSpaceId, OpenMode.ForWrite)
            # Idempotent re-run: clear grid + divider layers first.
            for oid in ms:
                ent = tx.GetObject(oid, OpenMode.ForRead)
                if isinstance(ent, Polyline) and ent.Layer in (layer, DIV_LAYER):
                    ent.UpgradeOpen()
                    ent.Erase()

            def _add(a, b, lyr, color_index=None):
                pl = Polyline()
                pl.AddVertexAt(0, Point2d(a[0], a[1]), 0.0, 0.0, 0.0)
                pl.AddVertexAt(1, Point2d(b[0], b[1]), 0.0, 0.0, 0.0)
                pl.Elevation = elevation
                pl.Layer = lyr
                if color_index is not None:
                    pl.Color = Color.FromColorIndex(ColorMethod.ByAci, color_index)
                ms.AppendEntity(pl)
                tx.AddNewlyCreatedDBObject(pl, True)
                return pl.Handle.ToString()

            for ln in perps:
                ci = COLOR_EVEN if ln["parity"] == 0 else COLOR_ODD
                handles.append(_add(ln["a"], ln["b"], layer, ci))
            for a, b in dividers:
                _add(a, b, DIV_LAYER)  # ByLayer colour/linetype (dashed)
            tx.Commit()
        except Exception:
            tx.Abort()
            raise
        finally:
            tx.Dispose()
        return handles

    def run(self) -> str:
        self.log("=== anchor_03_build_grid ===")
        self.log(f"started: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
        self.log(
            f"axis layer: {AXIS_LAYER}  same-colour step: {STEP} m  "
            f"line step: {STEP / 2.0} m  overhang: {OVERHANG} m"
        )

        doc = Application.DocumentManager.MdiActiveDocument
        db = doc.Database

        lock = doc.LockDocument()
        result: dict[str, Any] = {}
        try:
            layer = self._ensure_layers(db)

            tx = db.TransactionManager.StartTransaction()
            try:
                axis, elev = load_axis(tx, db, AXIS_LAYER)
                band = load_band_contours(tx, db, HORIZ_LAYER)
                tx.Commit()
            finally:
                tx.Dispose()

            if len(axis) < 2:
                raise Exception(f"No axis polyline on {AXIS_LAYER}.")
            if len(band) < 2:
                raise Exception(f"Need >=2 horizontals on {HORIZ_LAYER} to bound band.")

            line_step = STEP / 2.0  # red/blue alternate, so same-colour spacing = STEP
            perps = build_phase_locked(axis, band, line_step, OVERHANG, SEAM_OVERLAP)
            dividers = build_dividers(axis, band, divider_dirs(axis))
            lengths = [math.dist(ln["a"], ln["b"]) for ln in perps]
            handles = self._draw(db, perps, dividers, elev, layer)
            dnorms = divider_normals(axis)
            result = {
                "layer": layer,
                "div_layer": DIV_LAYER,
                "elevation": elev,
                "step": STEP,
                "line_step": line_step,
                "overhang": OVERHANG,
                "count": len(handles),
                "dividers": len(dividers),
                "axis": [list(p) for p in axis],
                # divider forward-normals keyed by axis vertex index (territory test)
                "divider_normals": {str(i): list(m) for i, m in dnorms.items()},
                "lines": [
                    {
                        "a": list(ln["a"]),
                        "b": list(ln["b"]),
                        "seg": ln["seg"],
                        "color": COLOR_EVEN if ln["parity"] == 0 else COLOR_ODD,
                    }
                    for ln in perps
                ],
            }
            self.log(
                f"\ngrid: {len(handles)} perpendiculars, {len(dividers)} dividers, "
                f"len {min(lengths, default=0):.1f}..{max(lengths, default=0):.1f} m, "
                f"elev {elev:g}"
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
