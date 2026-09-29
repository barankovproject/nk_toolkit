from __future__ import annotations

import datetime
import glob
import math
import os
import traceback
from typing import Any, Optional

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import (
    AttributeDefinition,
    AttributeReference,
    BlockReference,
    BlockTableRecord,
    OpenMode,
    Polyline3d,
    RegAppTable,
    RegAppTableRecord,
    ResultBuffer,
    SymbolUtilityServices,
    TypedValue,
)
from Autodesk.AutoCAD.Geometry import Point3d

from ditch_core.config import CROSS_DITCH_LAYER, SOURCE_LAYER, trasse_for_layer

from .layers import ensure_point_filter, ensure_point_layers, point_layer_name

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
_LOG_PREFIX = "point_blocks"

# Effective name of the existing DWG block placed at every characteristic point.
# It already exists in the drawing — this script only inserts references to it.
_BLOCK_NAME = "Номер_точки_канавы"
# Attribute tag the running number is written into (by ditch_08_number_points).
# This script leaves it blank.
_NUM_TAG = "#"

# XData app stamped on every placed block so a re-run purges only this script's
# blocks (drawing-wide: placement processes every ditch regardless of canal).
_REGAPP = "ARHYZ_PT"
_SCOPE = "ditch"

# XData tags written by the ditch builders we read from.
_MD_REGAPP = "ARHYZ_MD"  # cross-ditch run + connector/killer (ditch_04_build_cross)
_LD_REGAPP = "ARHYZ_LD"  # longitudinal ditch (ditch_03_build_long)

# Cross-ditch parts: the гаситель (stilling apron) is the true END of a cross
# ditch. The chain is run_end → [connector] → killer.near → killer.far. Parts are
# paired to the run by GEOMETRY (nearest endpoint), not by index/layer — the same
# way ditch_05 links them — because Index is renumbered per-trasse on refresh and
# parts may sit on the base or a per-trasse layer.
_KILLER_LAYER = "inf_md_killer"
_CONN_LAYER = "inf_md_connector"
# A part whose nearest endpoint is within this distance (m) of the anchor is linked
# (matches ditch_05_build_cross_volumes._MATCH_TOL; tolerates hand-drawn lines).
_MATCH_TOL = 1.5

# Plan-bend threshold (deg) for a longitudinal PI, mirrors ditch_03 _plan_turns.
_PI_EPS_DEG = 5.0
# Longitudinal grade-break threshold (Δ rise/run between adjacent segments).
_GRADE_EPS = 0.02
# Two candidate points within this XY distance (m) collapse to one block — also
# merges a cross-ditch endpoint with the longitudinal vertex it joins.
_MERGE_TOL = 0.5
# Kept points closer than this (m) are logged as a possible visual overlap.
_NEAR_WARN = 2.0


Pt = tuple[float, float, float]


def _trim_logs(log_dir: str, prefix: str, keep: int = 10) -> None:
    for f in sorted(glob.glob(os.path.join(log_dir, f"{prefix}_*.log")))[:-keep]:
        try:
            os.remove(f)
        except OSError:
            pass


class PointBlockBuilder:
    """Place the "Номер_точки_канавы" block at every characteristic ditch point.

    Cross-ditches → block at both endpoints of each run. Longitudinal ditches →
    block at start/end, every plan PI, and every profile grade break. A cross-ditch
    endpoint that coincides with a longitudinal vertex (the junction) collapses to a
    single block via the merge tolerance. The block's `#` attribute is left blank;
    ditch_08_number_points fills it. Idempotent: existing ARHYZ_PT blocks are erased
    and re-placed each run.
    """

    def __init__(self) -> None:
        os.makedirs(_LOG_DIR, exist_ok=True)
        _trim_logs(_LOG_DIR, _LOG_PREFIX)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self._log_path = os.path.join(_LOG_DIR, f"{_LOG_PREFIX}_{ts}.log")

    def _log(self, msg: str, level: str = "INFO") -> None:
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [{level}] {msg}\n")

    def run(self) -> Any:
        log = self._log
        log("=== SCRIPT STARTED ===")

        errors: list[str] = []
        placed = 0

        try:
            doc = Application.DocumentManager.MdiActiveDocument
            db = doc.Database

            lock = doc.LockDocument()
            try:
                tx = db.TransactionManager.StartTransaction()
                try:
                    self._ensure_regapp(db, tx)
                    ensure_point_layers(db, tx)
                    layer = point_layer_name()
                    log(f"point block layer '{layer}'")

                    btr_id = self._find_block_def(db, tx, log)
                    if btr_id is None:
                        raise Exception(
                            f"block '{_BLOCK_NAME}' not found in the drawing"
                        )

                    ms = tx.GetObject(
                        SymbolUtilityServices.GetBlockModelSpaceId(db),
                        OpenMode.ForWrite,
                    )

                    purged = self._purge_existing(ms, tx)
                    log(f"purged {purged} existing point block(s)")

                    killers, connectors = self._collect_parts(ms, tx)
                    log(
                        f"found {len(killers)} гаситель(s) + {len(connectors)} "
                        f"connector(s) for cross-ditch ends"
                    )

                    cross_pts = self._cross_points(ms, tx, killers, connectors, log)
                    long_pts = self._long_points(ms, tx, log)
                    log(
                        f"candidates: {len(cross_pts)} cross endpoint(s), "
                        f"{len(long_pts)} longitudinal point(s)"
                    )

                    points = self._dedup(cross_pts + long_pts)
                    log(
                        f"{len(points)} unique point(s) after merge (tol {_MERGE_TOL} m)"
                    )
                    near = self._near_pairs(points)
                    if near:
                        log(
                            f"{near} block pair(s) closer than {_NEAR_WARN} m — may "
                            f"visually overlap; review or raise _MERGE_TOL",
                            "WARN",
                        )

                    placed = self._place_blocks(points, btr_id, layer, ms, tx, log)
                    log(f"placed {placed} point block(s)")

                    tx.Commit()
                    log("transaction committed")
                except Exception:
                    tx.Abort()
                    raise
                finally:
                    tx.Dispose()

                try:
                    fname = ensure_point_filter(db)
                    log(f"layer filter '{fname}' ensured")
                except Exception as e:
                    log(f"layer filter warning: {e}", "WARN")
            finally:
                lock.Dispose()

        except Exception as ex:
            errors.insert(0, f"ERROR: {ex}")
            log(f"ERROR: {ex}", "CRITICAL")
            log(traceback.format_exc(), "CRITICAL")

        log(f"=== DONE: placed={placed}, errors={len(errors)} ===")
        return placed if not errors else errors

    # ── geometry collection ────────────────────────────────────────────────

    def _collect_parts(
        self, ms: Any, tx: Any
    ) -> tuple[list[list[Pt]], list[tuple[Pt, Pt]]]:
        """Collect гаситель vertex-lists and connector (start, end) pairs by layer.

        Both the base layers (inf_md_killer / inf_md_connector) and their per-trasse
        suffixed variants are picked up — a part moved onto the base layer is still
        found, since linkage is geometric, not by suffix.
        """
        killers: list[list[Pt]] = []
        connectors: list[tuple[Pt, Pt]] = []
        for oid in ms:
            try:
                ent = tx.GetObject(oid, OpenMode.ForRead)
            except Exception:
                continue
            if not isinstance(ent, Polyline3d):
                continue
            layer = ent.Layer
            if trasse_for_layer(layer, _KILLER_LAYER) is not None:
                verts = self._vertices(ent, tx)
                if len(verts) >= 2:
                    killers.append(verts)
            elif trasse_for_layer(layer, _CONN_LAYER) is not None:
                verts = self._vertices(ent, tx)
                if len(verts) >= 2:
                    connectors.append((verts[0], verts[-1]))
        return killers, connectors

    def _cross_points(
        self,
        ms: Any,
        tx: Any,
        killers: list[list[Pt]],
        connectors: list[tuple[Pt, Pt]],
        log: Any,
    ) -> list[tuple[float, float, float]]:
        """Start (нагорная) + end of every cross-ditch run (ARHYZ_MD on inf_md_ditch*).

        Start = the run's first vertex. End = the гаситель's outer (far) vertex,
        found by walking the chain run_end → [connector] → killer.near → killer.far
        geometrically. A both-cut ditch with no гаситель ends at the run's last vertex.
        """
        pts: list[tuple[float, float, float]] = []
        no_killer = 0
        for oid in ms:
            try:
                ent = tx.GetObject(oid, OpenMode.ForRead)
            except Exception:
                continue
            if not isinstance(ent, Polyline3d):
                continue
            if trasse_for_layer(ent.Layer, CROSS_DITCH_LAYER) is None:
                continue  # connector / killer / foreign layer
            if not self._has_xdata(ent, _MD_REGAPP):
                continue
            verts = self._vertices(ent, tx)
            if len(verts) < 2:
                continue
            pts.append(verts[0])  # нагорная start
            end = self._structure_end(verts[-1], killers, connectors)
            if end is None:
                end = verts[-1]
                no_killer += 1
            pts.append(end)
        if no_killer:
            log(f"  {no_killer} cross-ditch(es) had no гаситель — ended at run end")
        return pts

    def _structure_end(
        self, run_end: Pt, killers: list[list[Pt]], connectors: list[tuple[Pt, Pt]]
    ) -> Optional[Pt]:
        """Far end of the гаситель linked to a run, or None if the run has no apron.

        Anchors = the run end plus the far end of any connector touching it (the
        apron may join directly or through a connector). The matched гаситель is the
        one whose nearest vertex is closest to an anchor (≤ _MATCH_TOL); its terminus
        is the vertex farthest from that anchor.
        """
        anchors: list[Pt] = [run_end]
        for c0, c1 in connectors:
            d0, d1 = math.dist(c0, run_end), math.dist(c1, run_end)
            if min(d0, d1) <= _MATCH_TOL:
                anchors.append(c1 if d0 <= d1 else c0)  # advance to the far end

        best_d = _MATCH_TOL
        best_far: Optional[Pt] = None
        for kverts in killers:
            for a in anchors:
                near = min(kverts, key=lambda p: math.dist(p, a))
                d = math.dist(near, a)
                if d <= best_d:
                    best_d = d
                    best_far = max(kverts, key=lambda p: math.dist(p, a))
        return best_far

    def _long_points(
        self, ms: Any, tx: Any, log: Any
    ) -> list[tuple[float, float, float]]:
        """Characteristic points of every longitudinal ditch (ARHYZ_LD on inf_ct_toe*).

        Start + end, plan PIs (XY deflection > _PI_EPS_DEG) and profile grade breaks
        (adjacent-segment grade change > _GRADE_EPS). Cut-toe lines (ARHYZ_CT) share
        the layer but are skipped — only ARHYZ_LD is read.
        """
        pts: list[tuple[float, float, float]] = []
        for oid in ms:
            try:
                ent = tx.GetObject(oid, OpenMode.ForRead)
            except Exception:
                continue
            if not isinstance(ent, Polyline3d):
                continue
            if trasse_for_layer(ent.Layer, SOURCE_LAYER) is None:
                continue
            if not self._has_xdata(ent, _LD_REGAPP):
                continue  # cut-toe (ARHYZ_CT) or foreign 3D line on the layer
            verts = self._vertices(ent, tx)
            if len(verts) < 2:
                continue
            closed = bool(getattr(ent, "Closed", False))
            idxs = self._characteristic_indices(verts, closed)
            for i in sorted(idxs):
                pts.append(verts[i])
        return pts

    def _characteristic_indices(
        self, pts: list[tuple[float, float, float]], closed: bool
    ) -> set[int]:
        """Indices of endpoints + plan PIs + profile grade breaks along a 3D run."""
        n = len(pts)
        idxs: set[int] = set()
        if n == 0:
            return idxs
        if not closed:
            idxs.add(0)
            idxs.add(n - 1)
        eps = math.radians(_PI_EPS_DEG)

        def ang(a: Any, b: Any) -> float:
            return math.atan2(b[1] - a[1], b[0] - a[0])

        def plan_deflect(i: int) -> float:
            d = ang(pts[i], pts[i + 1]) - ang(pts[i - 1], pts[i])
            while d > math.pi:
                d -= 2 * math.pi
            while d < -math.pi:
                d += 2 * math.pi
            return abs(d)

        def grade(a: Any, b: Any) -> Optional[float]:
            run = math.hypot(b[0] - a[0], b[1] - a[1])
            return None if run < 1e-9 else (b[2] - a[2]) / run

        for i in range(1, n - 1):
            if plan_deflect(i) > eps:
                idxs.add(i)
                continue
            g0 = grade(pts[i - 1], pts[i])
            g1 = grade(pts[i], pts[i + 1])
            if g0 is not None and g1 is not None and abs(g1 - g0) > _GRADE_EPS:
                idxs.add(i)
        return idxs

    def _vertices(self, ent: Any, tx: Any) -> list[tuple[float, float, float]]:
        """Ordered (x, y, z) vertices of a Polyline3d."""
        pts: list[tuple[float, float, float]] = []
        for vid in ent:
            try:
                p = tx.GetObject(vid, OpenMode.ForRead).Position
                pts.append((float(p.X), float(p.Y), float(p.Z)))
            except Exception:
                continue
        return pts

    def _dedup(
        self, pts: list[tuple[float, float, float]]
    ) -> list[tuple[float, float, float]]:
        """Collapse points within _MERGE_TOL (XY) to a single representative."""
        kept: list[tuple[float, float, float]] = []
        for p in pts:
            if any(math.hypot(p[0] - k[0], p[1] - k[1]) <= _MERGE_TOL for k in kept):
                continue
            kept.append(p)
        return kept

    def _near_pairs(self, pts: list[tuple[float, float, float]]) -> int:
        """Count kept-point pairs closer than _NEAR_WARN (possible visual overlap)."""
        n = 0
        for i in range(len(pts)):
            for j in range(i + 1, len(pts)):
                if (
                    math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1])
                    < _NEAR_WARN
                ):
                    n += 1
        return n

    # ── block placement ──────────────────────────────────────────────────────

    def _place_blocks(
        self,
        points: list[tuple[float, float, float]],
        btr_id: Any,
        layer: str,
        ms: Any,
        tx: Any,
        log: Any,
    ) -> int:
        placed = 0
        btr = tx.GetObject(btr_id, OpenMode.ForRead)
        attdefs = [
            tx.GetObject(eid, OpenMode.ForRead)
            for eid in btr
            if isinstance(tx.GetObject(eid, OpenMode.ForRead), AttributeDefinition)
        ]
        for p in points:
            try:
                br = BlockReference(Point3d(*p), btr_id)
                br.Layer = layer
                ms.AppendEntity(br)
                tx.AddNewlyCreatedDBObject(br, True)
                self._add_attributes(br, attdefs, tx)
                br.XData = ResultBuffer(
                    TypedValue(1001, _REGAPP), TypedValue(1000, _SCOPE)
                )
                placed += 1
            except Exception as e:
                log(f"  place failed at ({p[0]:.2f}, {p[1]:.2f}): {e}", "WARN")
        return placed

    def _add_attributes(self, br: Any, attdefs: list[Any], tx: Any) -> None:
        """Append an AttributeReference per (non-constant) AttributeDefinition.

        The running-number attribute (`#`) is left blank — ditch_08_number_points
        fills it. Other attributes keep their definition default.
        """
        for ad in attdefs:
            if ad.Constant:
                continue
            ar = AttributeReference()
            ar.SetAttributeFromBlock(ad, br.BlockTransform)
            ar.TextString = "" if ad.Tag.strip() == _NUM_TAG else ad.TextString
            br.AttributeCollection.AppendAttribute(ar)
            tx.AddNewlyCreatedDBObject(ar, True)

    def _find_block_def(self, db: Any, tx: Any, log: Any) -> Optional[Any]:
        """ObjectId of the _BLOCK_NAME block table record (exact, then case-insensitive)."""
        bt = tx.GetObject(db.BlockTableId, OpenMode.ForRead)
        candidates: list[str] = []
        exact: Optional[Any] = None
        ci: Optional[Any] = None
        for btr_id in bt:
            btr = tx.GetObject(btr_id, OpenMode.ForRead)
            if not isinstance(btr, BlockTableRecord):
                continue
            if btr.IsAnonymous or btr.IsLayout:
                continue
            name = btr.Name
            if name == _BLOCK_NAME:
                exact = btr_id
            if name.strip().lower() == _BLOCK_NAME.strip().lower():
                ci = btr_id
            low = name.lower()
            if "точк" in low or "point" in low:
                candidates.append(name)
        if exact is not None:
            return exact
        if ci is not None:
            log(f"block matched case-insensitively to '{_BLOCK_NAME}'", "WARN")
            return ci
        log(f"block '{_BLOCK_NAME}' not found; candidates: {candidates}", "WARN")
        return None

    # ── xdata / idempotency ────────────────────────────────────────────────

    def _has_xdata(self, ent: Any, regapp: str) -> bool:
        try:
            return ent.GetXDataForApplication(regapp) is not None
        except Exception:
            return False

    def _purge_existing(self, ms: Any, tx: Any) -> int:
        """Erase every block this script placed on a previous run (ARHYZ_PT xdata)."""
        erased = 0
        for oid in list(ms):
            try:
                ent = tx.GetObject(oid, OpenMode.ForRead)
                if not isinstance(ent, BlockReference):
                    continue
                if ent.GetXDataForApplication(_REGAPP) is None:
                    continue
                ent.UpgradeOpen()
                ent.Erase()
                erased += 1
            except Exception:
                continue
        return erased

    def _ensure_regapp(self, db: Any, tx: Any) -> None:
        """Register ARHYZ_PT in RegAppTable so XData can be attached."""
        rat = tx.GetObject(db.RegAppTableId, OpenMode.ForRead)
        if not rat.Has(_REGAPP):
            rat.UpgradeOpen()
            ratr = RegAppTableRecord()
            ratr.Name = _REGAPP
            rat.Add(ratr)
            tx.AddNewlyCreatedDBObject(ratr, True)
