from __future__ import annotations

import datetime
import glob
import json
import os
import traceback
from typing import Any, Optional

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import Line, OpenMode
from Autodesk.AutoCAD.Geometry import Point3d

from .config import DRAWING, find_best_match
from .layers import ensure_lp_filter, ensure_lp_layers
from paths import CANALS_DATA_DIR

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
_LOG_PREFIX = "location_plan"

# Outer shell indices in section_pts: P7-P6-P5-P4
_OUTER_IDX = (8, 7, 6, 5)


def _trim_logs(log_dir: str, prefix: str, keep: int = 10) -> None:
    for f in sorted(glob.glob(os.path.join(log_dir, f"{prefix}_*.log")))[:-keep]:
        try:
            os.remove(f)
        except OSError:
            pass


def _add_line(p1: Any, p2: Any, layer: str, ms: Any, tx: Any) -> None:
    ln = Line(p1, p2)
    ln.Layer = layer
    ms.AppendEntity(ln)
    tx.AddNewlyCreatedDBObject(ln, True)


class LocationPlanBuilder:
    def __init__(self, query: str) -> None:
        self.query = query.strip()
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
        log(f"query='{self.query}'")

        errors: list[str] = []
        added = 0

        try:
            section_pts, rib_stations = self._load_section_pts()
            if not section_pts:
                raise Exception(
                    f"No section_points in canal data JSON for '{self.query}'. "
                    "Run build_canal_model first."
                )
            rib_piece_count = sum(len(r.get("laterals", [])) for r in rib_stations)
            log(
                f"loaded {len(section_pts)} pre-computed stations, {len(rib_stations)} rib stations ({rib_piece_count} pieces)"
            )

            doc = Application.DocumentManager.MdiActiveDocument
            db = doc.Database

            lock = doc.LockDocument()
            try:
                tx = db.TransactionManager.StartTransaction()
                try:
                    ensure_lp_layers(db, tx)
                    log("layers ensured")

                    self._ensure_regapp(db, tx)

                    ms = tx.GetObject(db.CurrentSpaceId, OpenMode.ForWrite)

                    erased = self._purge_lp_entities(ms, tx, self.query)
                    log(f"purged {erased} existing entities for '{self.query}'")

                    n, outline_oid = self._draw_outline(section_pts, ms, tx)
                    added += n
                    log(f"outline: {n} polylines")

                    n, corridor_oid, corr_pts_r, corr_pts_l = (
                        self._draw_corridor_outline(ms, tx)
                    )
                    added += n
                    log(f"corridor outline: {n} polylines")

                    if outline_oid is not None and corridor_oid is not None:
                        snapped = self._snap_outline_to_corridor(
                            outline_oid, corr_pts_r, corr_pts_l, section_pts, tx
                        )
                        log(f"outline snap: {snapped}")

                    if outline_oid is not None:
                        n = self._draw_gabion_hatch(outline_oid, ms, tx)
                        added += n
                        log(f"gabion hatch: {n}")

                    if outline_oid is not None and corridor_oid is not None:
                        n = self._draw_slope_hatch(corridor_oid, outline_oid, ms, tx)
                        added += n
                        log(f"slope hatch: {n}")
                    else:
                        log("slope hatch skipped — one boundary missing", "WARN")

                    n = self._draw_gabion_3d(section_pts, ms, tx)
                    added += n
                    log(f"gabion 3d lines: {n}")

                    n = self._draw_ribs(section_pts, rib_stations, ms, tx)
                    added += n
                    log(f"ribs: {n}")

                    n = self._draw_centerline(section_pts, ms, tx)
                    added += n
                    log(f"centerline: {n} polylines")

                    tagged = self._tag_lp_entities(ms, tx, self.query)
                    log(f"tagged {tagged} new entities with canal '{self.query}'")

                    tx.Commit()
                    log("transaction committed")
                except Exception:
                    tx.Abort()
                    raise
                finally:
                    tx.Dispose()

                # filter must be set inside the document lock but outside any transaction
                try:
                    fname = ensure_lp_filter(db)
                    log(f"layer filter '{fname}' ensured")
                except Exception as e:
                    log(f"layer filter warning: {e}", "WARN")
            finally:
                lock.Dispose()

        except Exception as ex:
            errors.insert(0, f"ERROR: {ex}")
            log(f"ERROR: {ex}", "CRITICAL")
            log(traceback.format_exc(), "CRITICAL")

        log(f"=== DONE: added={added}, errors={len(errors)} ===")
        return added if not errors else errors

    _REGAPP = "ARHYZ_LP"

    def _ensure_regapp(self, db: Any, tx: Any) -> None:
        """Register ARHYZ_LP app in RegAppTable so XData can be attached."""
        from Autodesk.AutoCAD.DatabaseServices import RegAppTable, RegAppTableRecord

        rat = tx.GetObject(db.RegAppTableId, OpenMode.ForRead)
        if not rat.Has(self._REGAPP):
            rat.UpgradeOpen()
            ratr = RegAppTableRecord()
            ratr.Name = self._REGAPP
            rat.Add(ratr)
            tx.AddNewlyCreatedDBObject(ratr, True)

    def _purge_lp_entities(self, ms: Any, tx: Any, canal_name: str) -> int:
        """Erase inf_lp_* entities tagged with this canal name only."""
        from Autodesk.AutoCAD.DatabaseServices import ResultBuffer

        to_erase: list[Any] = []
        for oid in ms:
            try:
                ent = tx.GetObject(oid, OpenMode.ForRead)
                if not ent.Layer.startswith("inf_lp_"):
                    continue
                rb = ent.GetXDataForApplication(self._REGAPP)
                if rb is None:
                    continue
                name = next((str(tv.Value) for tv in rb if tv.TypeCode == 1000), None)
                if name == canal_name:
                    to_erase.append(oid)
            except Exception:
                pass
        for oid in to_erase:
            try:
                tx.GetObject(oid, OpenMode.ForWrite).Erase()
            except Exception:
                pass
        return len(to_erase)

    def _tag_lp_entities(self, ms: Any, tx: Any, canal_name: str) -> int:
        """Attach XData ARHYZ_LP=canal_name to every inf_lp_* entity that has no tag yet."""
        from Autodesk.AutoCAD.DatabaseServices import ResultBuffer, TypedValue

        tagged = 0
        rb_new = ResultBuffer(
            TypedValue(1001, self._REGAPP),
            TypedValue(1000, canal_name),
        )
        for oid in ms:
            try:
                ent = tx.GetObject(oid, OpenMode.ForRead)
                if not ent.Layer.startswith("inf_lp_"):
                    continue
                if ent.GetXDataForApplication(self._REGAPP) is not None:
                    continue  # already tagged — belongs to another canal
                ent.UpgradeOpen()
                ent.XData = rb_new
                tagged += 1
            except Exception:
                pass
        return tagged

    def _load_section_pts(
        self,
    ) -> tuple[dict[str, list[list[Any]]], list[dict[str, Any]]]:
        """Load section_points and rib_stations from canal data JSON."""
        from civil.utils import normalize

        norm = normalize(self.query)
        if os.path.isdir(CANALS_DATA_DIR):
            for fname in os.listdir(CANALS_DATA_DIR):
                if fname.endswith(".json") and normalize(fname[:-5]) == norm:
                    path = os.path.join(CANALS_DATA_DIR, fname)
                    with open(path, encoding="utf-8") as f:
                        data = json.load(f)
                    # tolerate stale JSON: old rib_stations were bare floats, new are dicts
                    ribs = [
                        r for r in data.get("rib_stations", []) if isinstance(r, dict)
                    ]
                    return data.get("section_points", {}), ribs
        return {}, []

    def _draw_outline(
        self,
        section_pts: dict[str, list[list[Any]]],
        ms: Any,
        tx: Any,
    ) -> tuple[int, Optional[Any]]:
        """Draw a closed 2D polyline along the gabion outer boundary (P7/P4) in plan.

        Returns (count, ObjectId) so the caller can use it as a hatch boundary.
        """
        from Autodesk.AutoCAD.DatabaseServices import Polyline
        from Autodesk.AutoCAD.Geometry import Point2d

        layer = "inf_lp_outline"

        stations = sorted(section_pts.keys(), key=lambda k: float(k))
        if len(stations) < 2:
            return 0, None

        left_pts = [section_pts[s][8][:2] for s in stations]
        right_pts = [section_pts[s][5][:2] for s in reversed(stations)]

        pl = Polyline()
        pl.SetDatabaseDefaults()
        for i, (x, y) in enumerate(left_pts + right_pts):
            pl.AddVertexAt(i, Point2d(x, y), 0.0, 0.0, 0.0)
        pl.Closed = True
        pl.Layer = layer
        ms.AppendEntity(pl)
        tx.AddNewlyCreatedDBObject(pl, True)
        return 1, pl.ObjectId

    def _draw_corridor_outline(
        self, ms: Any, tx: Any
    ) -> tuple[
        int, Optional[Any], list[tuple[float, float]], list[tuple[float, float]]
    ]:
        """Draw a closed 2D polyline from corridor Daylight feature lines.

        Returns (count, ObjectId, pts_r, pts_l) — full right/left FL point lists
        so the caller can determine which end is closer to the canal start.
        Returns (0, None, [], []) if no match.
        """
        from Autodesk.AutoCAD.DatabaseServices import Polyline
        from Autodesk.AutoCAD.Geometry import Point2d
        from Autodesk.Civil.ApplicationServices import CivilApplication
        from civil.utils import safe_iter, safe_resolve

        layer = "inf_lp_corridor"

        civil_db = CivilApplication.ActiveDocument
        cc = civil_db.CorridorCollection

        corridors: list[Any] = []
        names: list[str] = []
        for raw in safe_iter(cc):
            corr = safe_resolve(raw, tx)
            if corr is None:
                continue
            corridors.append(corr)
            names.append(corr.Name)

        if not names:
            self._log("no corridors found in drawing", "WARN")
            return 0, None, [], []

        match = find_best_match(self.query, names)
        if match is None:
            self._log(
                f"corridor not found for '{self.query}' — "
                f"available: {', '.join(names)}",
                "WARN",
            )
            return 0, None, [], []

        corr = corridors[match[0]]
        corr_name = match[1]
        self._log(f"corridor matched: '{corr_name}'")

        try:
            bl = list(corr.Baselines)[0]
            fl_map = bl.MainBaselineFeatureLines.FeatureLineCollectionMap
            fls = list(fl_map["Daylight"])
        except Exception as e:
            self._log(f"Daylight feature lines error: {e}", "WARN")
            return 0, None, [], []

        if len(fls) < 2:
            self._log(
                f"corridor '{corr_name}': {len(fls)} Daylight FL found (need 2)",
                "WARN",
            )
            return 0, None, [], []

        def first_offset(fl: Any) -> float:
            for fp in fl.FeatureLinePoints:
                return float(fp.Offset)
            return 0.0

        off0 = first_offset(fls[0])
        fl_r = fls[0] if off0 >= 0 else fls[1]
        fl_l = fls[1] if off0 >= 0 else fls[0]

        pts_r = [(float(fp.XYZ.X), float(fp.XYZ.Y)) for fp in fl_r.FeatureLinePoints]
        pts_l = [(float(fp.XYZ.X), float(fp.XYZ.Y)) for fp in fl_l.FeatureLinePoints]

        if not pts_r or not pts_l:
            self._log(f"corridor '{corr_name}': empty Daylight FL points", "WARN")
            return 0, None, [], []

        outline = pts_r + list(reversed(pts_l))

        pl = Polyline()
        pl.SetDatabaseDefaults()
        for i, (x, y) in enumerate(outline):
            pl.AddVertexAt(i, Point2d(x, y), 0.0, 0.0, 0.0)
        pl.Closed = True
        pl.Layer = layer
        ms.AppendEntity(pl)
        tx.AddNewlyCreatedDBObject(pl, True)

        self._log(f"corridor outline: {len(outline)} vertices")
        return 1, pl.ObjectId, pts_r, pts_l

    def _snap_outline_to_corridor(
        self,
        outline_oid: Any,
        corr_pts_r: list[tuple[float, float]],
        corr_pts_l: list[tuple[float, float]],
        section_pts: dict[str, list[list[Any]]],
        tx: Any,
        max_dist: float = 5.0,
    ) -> str:
        """Translate the gabion outline's start cap outward to sit flush with the corridor cap.

        The cap edge (P4_start→P7_start) is shifted perpendicular to itself, along the canal
        axis away from the canal body, by the perpendicular component of the gap to the nearest
        corridor endpoints.  The cap keeps its shape (stays parallel) — this closes the hatch
        sliver at the canal start without distorting the gabion outline.
        Only acts when the corridor endpoints are within max_dist metres.
        """
        import math
        from Autodesk.AutoCAD.DatabaseServices import OpenMode
        from Autodesk.AutoCAD.Geometry import Point2d

        def dist(a: tuple[float, float], b: tuple[float, float]) -> float:
            return math.hypot(a[0] - b[0], a[1] - b[1])

        stations = sorted(section_pts.keys(), key=lambda k: float(k))
        p7s = tuple(section_pts[stations[0]][8][:2])  # gabion cap, left  (outline v0)
        p4s = tuple(
            section_pts[stations[0]][5][:2]
        )  # gabion cap, right (outline v[n-1])
        p7e = tuple(section_pts[stations[-1]][8][:2])  # left outer at canal end

        # cap edge direction (P4_start → P7_start)
        ex, ey = p7s[0] - p4s[0], p7s[1] - p4s[1]
        elen = math.hypot(ex, ey)
        if elen < 1e-9:
            return "skipped — degenerate cap edge"
        ex, ey = ex / elen, ey / elen

        # perpendicular to the cap; orient it outward (away from the canal body)
        perp = (ey, -ex)
        outward = (p7s[0] - p7e[0], p7s[1] - p7e[1])
        if perp[0] * outward[0] + perp[1] * outward[1] < 0.0:
            perp = (-perp[0], -perp[1])

        # nearest corridor endpoint to each gabion cap endpoint
        fl_ends = [corr_pts_r[0], corr_pts_r[-1], corr_pts_l[0], corr_pts_l[-1]]
        c7 = min(fl_ends, key=lambda p: dist(p, p7s))
        c4 = min(fl_ends, key=lambda p: dist(p, p4s))
        if dist(c7, p7s) > max_dist or dist(c4, p4s) > max_dist:
            return (
                f"skipped — corridor too far "
                f"(p7 {dist(c7, p7s):.2f} m, p4 {dist(c4, p4s):.2f} m, max {max_dist} m)"
            )

        # perpendicular (along-axis) component of each gap → common outward shift
        d7 = (c7[0] - p7s[0]) * perp[0] + (c7[1] - p7s[1]) * perp[1]
        d4 = (c4[0] - p4s[0]) * perp[0] + (c4[1] - p4s[1]) * perp[1]
        move = (d7 + d4) / 2.0
        if move <= 0.0:
            return f"skipped — corridor cap not outside gabion (move={move:.3f} m)"

        new7 = (p7s[0] + perp[0] * move, p7s[1] + perp[1] * move)
        new4 = (p4s[0] + perp[0] * move, p4s[1] + perp[1] * move)

        pl = tx.GetObject(outline_oid, OpenMode.ForWrite)
        n = pl.NumberOfVertices
        pl.SetPointAt(0, Point2d(new7[0], new7[1]))
        pl.SetPointAt(n - 1, Point2d(new4[0], new4[1]))
        return f"OK — cap shifted {move:.3f} m outward (d7={d7:.3f}, d4={d4:.3f})"

    # Pattern hatch scales (drawing units = metres)
    _GABION_HATCH_SCALE: float = 0.1
    _SLOPE_HATCH_SCALE: float = 0.1

    def _draw_gabion_hatch(self, outline_oid: Any, ms: Any, tx: Any) -> int:
        """Fill the whole gabion outline with a HONEY pattern on layer inf_lp_hatch."""
        from Autodesk.AutoCAD.DatabaseServices import (
            Hatch,
            HatchPatternType,
            HatchStyle,
            HatchLoopTypes,
            ObjectIdCollection,
        )

        layer = "inf_lp_hatch"

        loop_ids = ObjectIdCollection()
        loop_ids.Add(outline_oid)

        h = Hatch()
        h.SetDatabaseDefaults()
        h.PatternScale = self._GABION_HATCH_SCALE
        h.SetHatchPattern(HatchPatternType.PreDefined, "HONEY")
        h.HatchStyle = HatchStyle.Normal
        h.Layer = layer
        ms.AppendEntity(h)
        tx.AddNewlyCreatedDBObject(h, True)

        h.Associative = True
        h.AppendLoop(HatchLoopTypes.Outermost, loop_ids)
        h.EvaluateHatch(True)

        return 1

    def _draw_centerline(
        self, section_pts: dict[str, list[list[Any]]], ms: Any, tx: Any
    ) -> int:
        """Draw the alignment centerline in plan through bottom-centre points (idx 2)."""
        from Autodesk.AutoCAD.DatabaseServices import Polyline
        from Autodesk.AutoCAD.Geometry import Point2d

        layer = "inf_lp_centerline"

        stations = sorted(section_pts.keys(), key=lambda k: float(k))
        if len(stations) < 2:
            return 0

        pl = Polyline()
        pl.SetDatabaseDefaults()
        for i, s in enumerate(stations):
            x, y = section_pts[s][2][0], section_pts[s][2][1]
            pl.AddVertexAt(i, Point2d(x, y), 0.0, 0.0, 0.0)
        pl.Layer = layer
        ms.AppendEntity(pl)
        tx.AddNewlyCreatedDBObject(pl, True)
        return 1

    def _draw_slope_hatch(
        self, outer_oid: Any, inner_oid: Any, ms: Any, tx: Any
    ) -> int:
        """Hatch the slope zone between corridor boundary (outer) and gabion outline (inner).

        Pattern: ANSI37, layer: inf_lp_slope_hatch (light blue).
        """
        from Autodesk.AutoCAD.DatabaseServices import (
            Hatch,
            HatchPatternType,
            HatchStyle,
            HatchLoopTypes,
            ObjectIdCollection,
        )

        layer = "inf_lp_slope_hatch"

        outer_ids = ObjectIdCollection()
        outer_ids.Add(outer_oid)
        inner_ids = ObjectIdCollection()
        inner_ids.Add(inner_oid)

        h = Hatch()
        h.SetDatabaseDefaults()
        h.PatternScale = self._SLOPE_HATCH_SCALE
        h.SetHatchPattern(HatchPatternType.PreDefined, "ANSI37")
        h.HatchStyle = HatchStyle.Normal
        h.Layer = layer
        ms.AppendEntity(h)
        tx.AddNewlyCreatedDBObject(h, True)

        h.Associative = True
        h.AppendLoop(HatchLoopTypes.Outermost, outer_ids)
        h.AppendLoop(HatchLoopTypes.Default, inner_ids)
        h.EvaluateHatch(True)

        return 1

    # Physical rib thickness along canal axis (metres); mirrors RIBS.size in canal_model
    _RIB_HALF: float = 0.085

    def _draw_ribs(
        self,
        section_pts: dict[str, list[list[Any]]],
        rib_stations: list[dict[str, Any]],
        ms: Any,
        tx: Any,
    ) -> int:
        """Draw one filled rectangle per lateral rib segment at each rib station.

        rib_stations format: [{"station": float, "laterals": [[lat_a, lat_b], ...]}, ...]
        Lateral offsets are signed distances from canal centre along the cross-axis.
        Each rectangle is _RIB_HALF*2 thick along the canal axis.
        """
        import math
        from Autodesk.AutoCAD.DatabaseServices import (
            Hatch,
            HatchLoopTypes,
            HatchPatternType,
            HatchStyle,
            ObjectIdCollection,
            Polyline,
        )
        from Autodesk.AutoCAD.Geometry import Point2d

        layer = "inf_lp_ribs"
        half = self._RIB_HALF
        count = 0

        # sorted list of (float_station, key) for interpolation
        sorted_keys = sorted(section_pts.keys(), key=lambda k: float(k))
        sorted_floats = [float(k) for k in sorted_keys]

        def _interp_pts(sta: float) -> list[list[float]]:
            """Linearly interpolate section_pts at an arbitrary station."""
            if sta <= sorted_floats[0]:
                return section_pts[sorted_keys[0]]
            if sta >= sorted_floats[-1]:
                return section_pts[sorted_keys[-1]]
            # find bracketing stations
            for j in range(len(sorted_floats) - 1):
                s0, s1 = sorted_floats[j], sorted_floats[j + 1]
                if s0 <= sta <= s1:
                    t = (sta - s0) / (s1 - s0) if s1 > s0 else 0.0
                    pts0 = section_pts[sorted_keys[j]]
                    pts1 = section_pts[sorted_keys[j + 1]]
                    return [
                        [
                            pts0[i][0] + t * (pts1[i][0] - pts0[i][0]),
                            pts0[i][1] + t * (pts1[i][1] - pts0[i][1]),
                            pts0[i][2] + t * (pts1[i][2] - pts0[i][2]),
                        ]
                        for i in range(len(pts0))
                    ]
            return section_pts[sorted_keys[-1]]

        for rec in rib_stations:
            raw_sta = rec["station"]
            laterals = rec.get("laterals", [])
            pts = _interp_pts(raw_sta)

            # canal centre bottom and lateral unit vector from section_pts
            cx, cy = pts[2][0], pts[2][1]  # idx 2 = centre bottom
            p1x, p1y = pts[1][0], pts[1][1]  # idx 1 = left bottom edge
            p3x, p3y = pts[3][0], pts[3][1]  # idx 3 = right bottom edge
            dx, dy = p3x - p1x, p3y - p1y
            lat_len = math.sqrt(dx * dx + dy * dy)
            if lat_len < 1e-6:
                continue
            rx, ry = dx / lat_len, dy / lat_len  # lateral unit vector (centre→right)
            ax, ay = -ry, rx  # canal axis unit vector

            for lat_a, lat_b in laterals:
                la_x, la_y = cx + rx * lat_a, cy + ry * lat_a
                lb_x, lb_y = cx + rx * lat_b, cy + ry * lat_b

                corners = [
                    Point2d(la_x + ax * half, la_y + ay * half),
                    Point2d(la_x - ax * half, la_y - ay * half),
                    Point2d(lb_x - ax * half, lb_y - ay * half),
                    Point2d(lb_x + ax * half, lb_y + ay * half),
                ]

                pl = Polyline()
                pl.SetDatabaseDefaults()
                for i, pt in enumerate(corners):
                    pl.AddVertexAt(i, pt, 0.0, 0.0, 0.0)
                pl.Closed = True
                pl.Layer = layer
                ms.AppendEntity(pl)
                tx.AddNewlyCreatedDBObject(pl, True)

                rib_ids = ObjectIdCollection()
                rib_ids.Add(pl.ObjectId)

                h = Hatch()
                h.SetDatabaseDefaults()
                h.PatternScale = 1.0
                h.SetHatchPattern(HatchPatternType.PreDefined, "SOLID")
                h.HatchStyle = HatchStyle.Normal
                h.Layer = layer
                ms.AppendEntity(h)
                tx.AddNewlyCreatedDBObject(h, True)
                h.Associative = True
                h.AppendLoop(HatchLoopTypes.Outermost, rib_ids)
                h.EvaluateHatch(True)

                count += 1

        return count

    def _create_viewport(
        self,
        section_pts: dict[str, list[list[Any]]],
        db: Any,
        doc: Any,
        scale: float = 500.0,
        layout_name: str = "",
    ) -> str:
        """Create a paper space viewport showing the canal location plan.

        scale     — denominator of the drawing scale (500 → 1:500).
        layout_name — paper space layout to use; defaults to 'LP_<canal_name>'.
        """
        import math
        from Autodesk.AutoCAD.DatabaseServices import (
            LayoutManager,
            Viewport,
            OpenMode,
        )
        from Autodesk.AutoCAD.Geometry import Point2d, Point3d

        if not layout_name:
            safe = self.query.replace(" ", "_")
            layout_name = f"LP_{safe}"

        # bounding box from P7 (idx 8) and P4 (idx 5) — outermost gabion edges
        xs, ys = [], []
        for pts in section_pts.values():
            for idx in (5, 8):
                xs.append(pts[idx][0])
                ys.append(pts[idx][1])

        if not xs:
            return "no section_points — cannot create viewport"

        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        bbox_w = max_x - min_x
        bbox_h = max_y - min_y
        cx_m = (min_x + max_x) / 2.0
        cy_m = (min_y + max_y) / 2.0

        pad = 0.15  # 15 % padding around the canal
        view_w = bbox_w * (1.0 + pad)
        view_h = bbox_h * (1.0 + pad)

        # paper space dimensions (drawing units = metres in this project)
        # 1:scale means 1 paper unit = scale model units → paper_unit = 1/scale model units
        # → viewport paper width = view_w / scale, height = view_h / scale
        vp_w = view_w / scale
        vp_h = view_h / scale

        # ensure at least 0.05 m in paper space (5 cm) in each direction
        vp_w = max(vp_w, 0.05)
        vp_h = max(vp_h, 0.05)

        lm = LayoutManager.Current
        if not lm.LayoutExists(layout_name):
            lm.CreateLayout(layout_name)

        layout_id = lm.GetLayoutId(layout_name)

        lock = doc.LockDocument()
        try:
            tx = db.TransactionManager.StartTransaction()
            try:
                layout = tx.GetObject(layout_id, OpenMode.ForRead)
                ps_btr_id = layout.BlockTableRecordId
                ps_btr = tx.GetObject(ps_btr_id, OpenMode.ForWrite)

                # centre the viewport on the paper sheet with 0.01 m margin
                margin = 0.01
                vp = Viewport()
                vp.SetDatabaseDefaults()
                vp.Width = vp_w
                vp.Height = vp_h
                vp.CenterPoint = Point3d(margin + vp_w / 2.0, margin + vp_h / 2.0, 0.0)
                vp.ViewCenter = Point2d(cx_m, cy_m)
                vp.ViewHeight = vp_h * scale  # model space height
                vp.CustomScale = 1.0 / scale
                vp.On = True

                ps_btr.AppendEntity(vp)
                tx.AddNewlyCreatedDBObject(vp, True)
                vp.UpdateDisplay()

                tx.Commit()
            except Exception:
                tx.Abort()
                raise
            finally:
                tx.Dispose()
        finally:
            lock.Dispose()

        lm.CurrentLayout = layout_name
        return (
            f"layout '{layout_name}' — viewport {vp_w * 1000:.0f}×{vp_h * 1000:.0f} mm, "
            f"1:{int(scale)}, view centre ({cx_m:.1f}, {cy_m:.1f})"
        )

    def _draw_gabion_3d(
        self,
        section_pts: dict[str, list[list[Any]]],
        ms: Any,
        tx: Any,
    ) -> int:
        """Draw 3D lines along outer shell (P7-P6-P5-P4) using pre-computed JSON points."""
        layer = "inf_lp_gabion_3d"

        stations = sorted(section_pts.keys(), key=lambda k: float(k))
        if len(stations) < 2:
            return 0

        def to_pt3d(raw: list) -> list[Any]:
            return [Point3d(p[0], p[1], p[2]) for p in raw]

        all_pts = [to_pt3d(section_pts[s]) for s in stations]
        count = 0

        pts = all_pts[0]
        for k in range(len(_OUTER_IDX) - 1):
            _add_line(pts[_OUTER_IDX[k]], pts[_OUTER_IDX[k + 1]], layer, ms, tx)
            count += 1

        for i in range(1, len(stations)):
            prev = all_pts[i - 1]
            cur = all_pts[i]

            for idx in _OUTER_IDX:
                _add_line(prev[idx], cur[idx], layer, ms, tx)
                count += 1

            for k in range(len(_OUTER_IDX) - 1):
                _add_line(cur[_OUTER_IDX[k]], cur[_OUTER_IDX[k + 1]], layer, ms, tx)
                count += 1

        return count
