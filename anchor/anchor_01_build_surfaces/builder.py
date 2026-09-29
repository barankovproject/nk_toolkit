"""Phase 1 orchestration: pick inputs, build one flat surface per CSV elevation.

Flow:
  1. Pick the ground surface and the boundary polyline interactively.
  2. Read the boundary's plan vertices once.
  3. Parse the anchor CSV (elevation -> length).
  4. For each elevation, build a flat TIN surface clipped to the boundary.
  5. Write anchor_surfaces.json (handle + length per elevation) for later phases.

The flat surfaces are the input for the Civil MINIMUMDISTBETWEENSURFACES command,
which the user runs next to draw the horizontal at each elevation. Anchor block
placement and point numbering are later phases.
"""

from __future__ import annotations

import datetime
import json
import os
import traceback
from typing import Any

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import OpenMode, Polyline

from anchor_01_build_surfaces.contours import extract_clipped_contour
from anchor_01_build_surfaces.csv_io import (
    csv_path_next_to,
    fmt_elevation,
    parse_anchor_csv,
)
from anchor_01_build_surfaces.layers import (
    anchor_layer_name,
    ensure_anchor_filter,
    ensure_anchor_layers,
)
from anchor_01_build_surfaces.selection import classify_inputs
from anchor_01_build_surfaces.surfaces import (
    build_flat_surface,
    extract_boundary_points,
)
from anchor_core.config import CONFIG

_HERE = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(_HERE, "logs")
CSV_FILE = csv_path_next_to(__file__)
JSON_FILE = os.path.join(_HERE, "anchor_surfaces.json")
SURFACE_PREFIX = "ANCHOR_PLANE_"
# Alternating horizontal colours by elevation order: even index red, odd blue.
COLOR_EVEN = CONFIG.color_even  # red (ACI)
COLOR_ODD = CONFIG.color_odd  # blue (ACI)


class AnchorSurfaceBuilder:
    def __init__(self) -> None:
        os.makedirs(LOG_DIR, exist_ok=True)
        self.log_file = os.path.join(
            LOG_DIR, f"build_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
        )

    def log(self, msg: str = "", level: str = "INFO") -> None:
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(f"{level}: {msg}\n" if level != "INFO" else f"{msg}\n")

    def _read_inputs(
        self, db: Any, inputs: list[Any]
    ) -> tuple[Any, str, list[tuple[float, float]]]:
        """Resolve the two Select Object picks.

        Returns (ground_oid, boundary_handle, boundary_xy).
        """
        if len(inputs) < 2:
            raise Exception(
                f"Expected 2 selected objects (surface + polyline), got {len(inputs)}."
            )
        tx = db.TransactionManager.StartTransaction()
        try:
            ground_oid, pl_oid = classify_inputs(db, tx, inputs)
            pline = tx.GetObject(pl_oid, OpenMode.ForRead)
            xy = extract_boundary_points(pline)
            bnd_handle = pline.Handle.ToString()
            ground = tx.GetObject(ground_oid, OpenMode.ForRead)
            self.log(f"ground surface: {ground.Name}")
            self.log(f"boundary polyline: {len(xy)} vertices (handle {bnd_handle})")
            tx.Commit()
            return ground_oid, bnd_handle, xy
        finally:
            tx.Dispose()

    def _clear_layer(self, db: Any, layer: str) -> int:
        """Erase every polyline on ``layer`` (idempotent horizontals re-run)."""
        n = 0
        tx = db.TransactionManager.StartTransaction()
        try:
            ms = tx.GetObject(db.CurrentSpaceId, OpenMode.ForWrite)
            for oid in ms:
                ent = tx.GetObject(oid, OpenMode.ForRead)
                if isinstance(ent, Polyline) and ent.Layer == layer:
                    ent.UpgradeOpen()
                    ent.Erase()
                    n += 1
            tx.Commit()
        finally:
            tx.Dispose()
        return n

    def _ensure_layers(self, db: Any) -> str:
        """Create the anchor layer + filter; return the layer name."""
        tx = db.TransactionManager.StartTransaction()
        try:
            ensure_anchor_layers(db, tx)
            tx.Commit()
        finally:
            tx.Dispose()
        ensure_anchor_filter(db)  # outside any transaction (LayerFilters is a struct)
        return anchor_layer_name()

    def _build_one(
        self,
        db: Any,
        name: str,
        xy: list[tuple[float, float]],
        elevation: float,
        ground_oid: Any,
        layer: str,
        color_index: int,
    ) -> tuple[str, list[str]]:
        """Build the flat surface and the clipped ground contour in one transaction.

        Returns (surface_handle, [contour_handle, ...]).
        """
        tx = db.TransactionManager.StartTransaction()
        try:
            surf = build_flat_surface(db, tx, name, xy, elevation)
            surf_handle = surf.Handle.ToString()
            ground = tx.GetObject(ground_oid, OpenMode.ForRead)
            contour_handles = extract_clipped_contour(
                db, tx, ground, elevation, xy, layer, color_index
            )
            tx.Commit()
            return surf_handle, contour_handles
        except Exception:
            tx.Abort()
            raise
        finally:
            tx.Dispose()

    def run(self, inputs: list[Any]) -> str:
        self.log("=== anchor_01_build_surfaces ===")
        self.log(f"started: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")

        doc = Application.DocumentManager.MdiActiveDocument
        db = doc.Database

        lock = doc.LockDocument()
        surfaces: dict[str, Any] = {}
        result: dict[str, Any] = {}
        try:
            ground_oid, bnd_handle, xy = self._read_inputs(db, inputs)
            layer = self._ensure_layers(db)
            cleared = self._clear_layer(db, layer)
            rows = sorted(parse_anchor_csv(CSV_FILE))  # ascending elevation
            self.log(f"CSV rows: {len(rows)} from {CSV_FILE}")
            self.log(f"horizontals layer: {layer} (cleared {cleared} old)\n")

            for idx, (elevation, length) in enumerate(rows):
                key = fmt_elevation(elevation)
                name = f"{SURFACE_PREFIX}{key}"
                color_index = COLOR_EVEN if idx % 2 == 0 else COLOR_ODD
                try:
                    surf_handle, contour_handles = self._build_one(
                        db, name, xy, elevation, ground_oid, layer, color_index
                    )
                    surfaces[key] = {
                        "surface_handle": surf_handle,
                        "length": length,
                        "contour_handles": contour_handles,
                        "color": color_index,
                    }
                    self.log(
                        f"  {name:24s} elev={elevation:<8g} color={color_index} OK "
                        f"surf={surf_handle} contours={len(contour_handles)}"
                    )
                except Exception as e:
                    self.log(traceback.format_exc())
                    self.log(
                        f"  {name:24s} elev={elevation:<8g} FAIL {type(e).__name__}: {e}",
                        "ERROR",
                    )
            result = {
                "boundary": {"handle": bnd_handle, "xy": [list(p) for p in xy]},
                "surfaces": surfaces,
            }
        finally:
            try:
                lock.Dispose()
            except Exception:
                pass

        # JSON write outside any transaction.
        with open(JSON_FILE, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        self.log(f"\nwrote {JSON_FILE} ({len(surfaces)} surfaces + boundary)")
        self.log("=== DONE ===")
        return self.log_file
