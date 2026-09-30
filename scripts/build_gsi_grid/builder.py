"""Draw the 2D GSI wall layout for one gabion ring, as a visual verification of `layout.py`.

Pick OUTER / MIDDLE / INNER polylines. Draws, on inf_gsi_grid_* layers:
  - construction aids per non-right-angle corner: a BLUE diagonal (outer corner -> inner corner)
    and MAGENTA perpendiculars (dropped from a vertex onto an edge, kept only where the foot
    lands on the actual segment);
  - the straight-layout REGION rectangle per wall, the yellow BLOCK quads, and the corner WEDGE /
    PATCH fills -- all produced by the shared, pure `layout_ring` (so the 2D view and the 3D
    `build_gsi_well` model never diverge).

Draws polylines only and purges its own output on re-run. The OUTER..INNER ring is laid with a
1.0 pitch along the wall (`along=1.0`); the same layout drives the 3D tiers.
"""

from __future__ import annotations

import datetime
import glob
import os
import traceback
from typing import Any, Optional

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import (
    Line,
    OpenMode,
    Polyline,
    SymbolUtilityServices,
)
from Autodesk.AutoCAD.EditorInput import PromptEntityOptions, PromptStatus
from Autodesk.AutoCAD.Geometry import Point2d, Point3d

from .layers import (
    block_layer_name,
    diag_layer_name,
    ensure_filter,
    ensure_layers,
    perp_layer_name,
    region_layer_name,
    wedge_layer_name,
)
from .layout import (
    Pt,
    _best_offset,
    _ccw,
    _foot,
    _interior_angle_deg,
    _ORTHO_TOL,
    layout_ring,
)

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
_LOG_PREFIX = "gsi_grid"
_STATUS_OK = int(PromptStatus.OK)
_ALONG = 1.0  # block pitch along the wall for the 2D OUTER..INNER ring


def _trim_logs(log_dir: str, prefix: str, keep: int = 20) -> None:
    for old in sorted(glob.glob(os.path.join(log_dir, f"{prefix}_*.log")))[:-keep]:
        try:
            os.remove(old)
        except Exception:
            pass


class GsiGridBuilder:
    def __init__(self) -> None:
        os.makedirs(_LOG_DIR, exist_ok=True)
        _trim_logs(_LOG_DIR, _LOG_PREFIX)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self._log_path = os.path.join(_LOG_DIR, f"{_LOG_PREFIX}_{ts}.log")

    def _log(self, msg: str, level: str = "INFO") -> None:
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [{level}] {msg}\n")

    def _pick(self, doc: Any, tx: Any, prompt: str) -> Optional[Any]:
        opts = PromptEntityOptions(f"\n{prompt}")
        opts.SetRejectMessage("\nA closed polyline is required.")
        opts.AddAllowedClass(Polyline, True)
        per = doc.Editor.GetEntity(opts)
        if int(per.Status) != _STATUS_OK:
            return None
        return tx.GetObject(per.ObjectId, OpenMode.ForRead)

    def _ring_xy(self, pl: Any) -> list[Pt]:
        pts: list[Pt] = []
        for i in range(pl.NumberOfVertices):
            p = pl.GetPoint3dAt(i)
            xy = (float(p.X), float(p.Y))
            if (
                pts
                and abs(xy[0] - pts[-1][0]) < 1e-9
                and abs(xy[1] - pts[-1][1]) < 1e-9
            ):
                continue
            pts.append(xy)
        if (
            len(pts) > 1
            and abs(pts[0][0] - pts[-1][0]) < 1e-9
            and abs(pts[0][1] - pts[-1][1]) < 1e-9
        ):
            pts.pop()
        return pts

    def run(self) -> Any:
        log = self._log
        log("=== SCRIPT STARTED ===")
        errors: list[str] = []
        drawn = 0
        try:
            doc = Application.DocumentManager.MdiActiveDocument
            db = doc.Database
            lock = doc.LockDocument()
            try:
                tx = db.TransactionManager.StartTransaction()
                try:
                    ensure_layers(db, tx)
                    diag_layer = diag_layer_name()
                    perp_layer = perp_layer_name()
                    region_layer = region_layer_name()
                    block_layer = block_layer_name()
                    wedge_layer = wedge_layer_name()

                    outer_pl = self._pick(doc, tx, "Select the OUTER contour:")
                    middle_pl = self._pick(doc, tx, "Select the MIDDLE contour:")
                    inner_pl = self._pick(doc, tx, "Select the INNER contour:")
                    if outer_pl is None or middle_pl is None or inner_pl is None:
                        log("selection cancelled", "WARN")
                        tx.Commit()
                        return drawn

                    outer = _ccw(self._ring_xy(outer_pl))
                    inner = _ccw(self._ring_xy(inner_pl))
                    n = len(outer)
                    if len(inner) != n:
                        raise Exception(
                            f"outer has {n} corners but inner has {len(inner)}; "
                            f"contours must have matching corners"
                        )
                    off = _best_offset(outer, inner)
                    log(f"corners={n}, inner offset={off}")

                    ms = tx.GetObject(
                        SymbolUtilityServices.GetBlockModelSpaceId(db),
                        OpenMode.ForWrite,
                    )

                    def add_line(a: Pt, b: Pt, layer: str) -> None:
                        ln = Line(Point3d(a[0], a[1], 0.0), Point3d(b[0], b[1], 0.0))
                        ln.Layer = layer
                        ms.AppendEntity(ln)
                        tx.AddNewlyCreatedDBObject(ln, True)

                    def add_region(quad: list[Pt], layer: str) -> None:
                        pl = Polyline()
                        pl.SetDatabaseDefaults()
                        for j, (x, y) in enumerate(quad):
                            pl.AddVertexAt(j, Point2d(x, y), 0.0, 0.0, 0.0)
                        pl.Closed = True
                        pl.Layer = layer
                        ms.AppendEntity(pl)
                        tx.AddNewlyCreatedDBObject(pl, True)

                    purged = self._purge(
                        ms,
                        tx,
                        {
                            diag_layer,
                            perp_layer,
                            region_layer,
                            block_layer,
                            wedge_layer,
                        },
                    )
                    log(f"purged {purged} existing grid entity(ies)")

                    # construction aids: blue diagonal + magenta perpendiculars per non-ortho corner
                    for c in range(n):
                        o_prev, o_cur, o_next = (
                            outer[(c - 1) % n],
                            outer[c],
                            outer[(c + 1) % n],
                        )
                        ang = _interior_angle_deg(o_prev, o_cur, o_next)
                        if abs(ang - 90.0) <= _ORTHO_TOL:
                            log(f"corner {c}: angle={ang:.1f} deg -> right angle, skip")
                            continue
                        ci = (c + off) % n
                        i_prev, i_cur, i_next = (
                            inner[(ci - 1) % n],
                            inner[ci],
                            inner[(ci + 1) % n],
                        )
                        add_line(o_cur, i_cur, diag_layer)
                        drawn += 1
                        cand = [
                            (i_cur, o_prev, o_cur),  # inner vertex -> outer edge (prev)
                            (i_cur, o_cur, o_next),  # inner vertex -> outer edge (next)
                            (o_cur, i_prev, i_cur),  # outer vertex -> inner edge (prev)
                            (o_cur, i_cur, i_next),  # outer vertex -> inner edge (next)
                        ]
                        kept = 0
                        for src, ea, eb in cand:
                            foot, t = _foot(src, ea, eb)
                            if foot is not None and -1e-9 <= t <= 1.0 + 1e-9:
                                add_line(src, foot, perp_layer)
                                drawn += 1
                                kept += 1
                        log(f"corner {c}: angle={ang:.1f} deg, perpendiculars={kept}")

                    # fill polygons from the shared pure layout (regions + blocks + wedges/patches)
                    layer_of = {
                        "region": region_layer,
                        "block": block_layer,
                        "wedge": wedge_layer,
                        "patch": wedge_layer,
                    }
                    counts = {"region": 0, "block": 0, "wedge": 0, "patch": 0}
                    for kind, poly in layout_ring(outer, inner, _ALONG):
                        add_region(poly, layer_of[kind])
                        counts[kind] += 1
                        drawn += 1
                    log(
                        f"layout: regions={counts['region']} blocks={counts['block']} "
                        f"wedges={counts['wedge']} patches={counts['patch']}"
                    )

                    tx.Commit()
                    log("transaction committed")
                except Exception:
                    tx.Abort()
                    raise
                finally:
                    tx.Dispose()

                try:
                    fname = ensure_filter(db)
                    log(f"layer filter '{fname}' ensured")
                except Exception as e:
                    log(f"layer filter warning: {e}", "WARN")
            finally:
                lock.Dispose()
        except Exception as ex:
            errors.insert(0, f"ERROR: {ex}")
            log(f"ERROR: {ex}", "CRITICAL")
            log(traceback.format_exc(), "CRITICAL")

        log(f"=== DONE: lines={drawn}, errors={len(errors)} ===")
        return drawn if not errors else errors

    def _purge(self, ms: Any, tx: Any, layers: set) -> int:
        count = 0
        for oid in ms:
            o = tx.GetObject(oid, OpenMode.ForRead)
            if isinstance(o, (Line, Polyline)) and o.Layer in layers:
                tx.GetObject(oid, OpenMode.ForWrite).Erase()
                count += 1
        return count
