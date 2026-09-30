"""Draw the rib placement scheme (схема расположения рёбер) for one canal.

Shows the transverse ribs as filled rectangles, over the gabion outer shell
(P7-P6-P5-P4) drawn as a thin dashed reference line. No area hatch.

Loads section_points + rib_stations from the canal data JSON (by query). Entities are
XData-tagged with the canal name (RegApp ARHYZ_RL, code 1000) so re-runs replace only
that canal.
"""

from __future__ import annotations

import datetime
import glob
import json
import math
import os
from typing import Any

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import (
    Hatch,
    HatchLoopTypes,
    HatchPatternType,
    HatchStyle,
    Line,
    ObjectIdCollection,
    OpenMode,
    Polyline,
    RegAppTable,
    RegAppTableRecord,
    ResultBuffer,
    TypedValue,
)
from Autodesk.AutoCAD.Geometry import Point2d, Point3d

from civil.utils import normalize
from paths import CANALS_DATA_DIR

from .layers import ensure_rl_filter, ensure_rl_layers

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
_LOG_PREFIX = "draw_rib_layout"

_REGAPP = "ARHYZ_RL"
RIBS_LAYER = "inf_rl_ribs"
SHELL_LAYER = "inf_rl_gabion_3d"
# outer gabion shell point indices: P7-P6-P5-P4
_OUTER_IDX = (8, 7, 6, 5)
# physical rib thickness along canal axis (metres); mirrors RIBS.size in canal_model
_RIB_HALF = 0.085


def _trim_logs(log_dir: str, prefix: str, keep: int = 10) -> None:
    for f in sorted(glob.glob(os.path.join(log_dir, f"{prefix}_*.log")))[:-keep]:
        try:
            os.remove(f)
        except OSError:
            pass


class RibLayoutBuilder:
    def __init__(self, query: str) -> None:
        self.query = (query or "").strip()
        os.makedirs(_LOG_DIR, exist_ok=True)
        _trim_logs(_LOG_DIR, _LOG_PREFIX)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self._log_path = os.path.join(_LOG_DIR, f"{_LOG_PREFIX}_{ts}.log")

    def _log(self, msg: str = "") -> None:
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(msg + "\n")

    def run(self) -> Any:
        log = self._log
        log("=== draw_rib_layout ===")
        log(f"query={self.query!r}")

        section_pts, rib_stations = self._load_section_pts()
        if not section_pts:
            log(
                f"ERROR: no section_points for '{self.query}' — run build_canal_model first"
            )
            return f"no section_points for '{self.query}'"
        log(f"loaded {len(section_pts)} stations, {len(rib_stations)} rib stations")

        doc = Application.DocumentManager.MdiActiveDocument
        db = doc.Database

        lock = doc.LockDocument()
        try:
            tx = db.TransactionManager.StartTransaction()
            try:
                ensure_rl_layers(db, tx)
                self._ensure_regapp(db, tx)
                ms = tx.GetObject(db.CurrentSpaceId, OpenMode.ForWrite)

                erased = self._purge(ms, tx, self.query)
                log(f"purged {erased} existing entities")

                n_shell = self._draw_gabion_3d(section_pts, ms, tx)
                log(f"gabion shell (dashed): {n_shell} lines")

                n_ribs = self._draw_ribs(section_pts, rib_stations, ms, tx)
                log(f"ribs: {n_ribs}")

                tagged = self._tag(ms, tx, self.query)
                log(f"tagged {tagged} entities")
                tx.Commit()
                log("transaction committed")

                try:
                    fname = ensure_rl_filter(db)
                    log(f"layer filter '{fname}' ensured")
                except Exception as e:
                    log(f"layer filter warning: {e}")
            except Exception:
                tx.Abort()
                raise
            finally:
                tx.Dispose()
        finally:
            lock.Dispose()

        log("=== DONE ===")
        return "OK"

    def _load_section_pts(
        self,
    ) -> tuple[dict[str, list[list[Any]]], list[dict[str, Any]]]:
        norm = normalize(self.query)
        if os.path.isdir(CANALS_DATA_DIR):
            for fname in os.listdir(CANALS_DATA_DIR):
                if fname.endswith(".json") and normalize(fname[:-5]) == norm:
                    with open(
                        os.path.join(CANALS_DATA_DIR, fname), encoding="utf-8"
                    ) as f:
                        data = json.load(f)
                    ribs = [
                        r for r in data.get("rib_stations", []) if isinstance(r, dict)
                    ]
                    return data.get("section_points", {}), ribs
        return {}, []

    def _ensure_regapp(self, db: Any, tx: Any) -> None:
        rat = tx.GetObject(db.RegAppTableId, OpenMode.ForRead)
        if not rat.Has(_REGAPP):
            rat.UpgradeOpen()
            ratr = RegAppTableRecord()
            ratr.Name = _REGAPP
            rat.Add(ratr)
            tx.AddNewlyCreatedDBObject(ratr, True)

    def _purge(self, ms: Any, tx: Any, canal_name: str) -> int:
        to_erase: list[Any] = []
        for oid in ms:
            ent = tx.GetObject(oid, OpenMode.ForRead)
            if not ent.Layer.startswith("inf_rl_"):
                continue
            rb = ent.GetXDataForApplication(_REGAPP)
            if rb is None:
                continue
            nm = next((str(tv.Value) for tv in rb if tv.TypeCode == 1000), None)
            if nm == canal_name:
                to_erase.append(oid)
        for oid in to_erase:
            tx.GetObject(oid, OpenMode.ForWrite).Erase()
        return len(to_erase)

    def _tag(self, ms: Any, tx: Any, canal_name: str) -> int:
        rb = ResultBuffer(TypedValue(1001, _REGAPP), TypedValue(1000, canal_name))
        n = 0
        for oid in ms:
            ent = tx.GetObject(oid, OpenMode.ForRead)
            if not ent.Layer.startswith("inf_rl_"):
                continue
            if ent.GetXDataForApplication(_REGAPP) is not None:
                continue
            ent.UpgradeOpen()
            ent.XData = rb
            n += 1
        return n

    def _add_line(self, p1: Any, p2: Any, ms: Any, tx: Any) -> None:
        ln = Line(p1, p2)
        ln.Layer = SHELL_LAYER
        ms.AppendEntity(ln)
        tx.AddNewlyCreatedDBObject(ln, True)

    def _draw_gabion_3d(
        self, section_pts: dict[str, list[list[Any]]], ms: Any, tx: Any
    ) -> int:
        """Outer gabion shell wireframe P7-P6-P5-P4 as a thin dashed reference (inf_rl_gabion_3d)."""
        stations = sorted(section_pts.keys(), key=lambda k: float(k))
        if len(stations) < 2:
            return 0

        def to_pt3d(raw: list) -> list[Any]:
            return [Point3d(p[0], p[1], p[2]) for p in raw]

        all_pts = [to_pt3d(section_pts[s]) for s in stations]
        count = 0
        pts = all_pts[0]
        for k in range(len(_OUTER_IDX) - 1):
            self._add_line(pts[_OUTER_IDX[k]], pts[_OUTER_IDX[k + 1]], ms, tx)
            count += 1
        for i in range(1, len(stations)):
            prev = all_pts[i - 1]
            cur = all_pts[i]
            for idx in _OUTER_IDX:
                self._add_line(prev[idx], cur[idx], ms, tx)
                count += 1
            for k in range(len(_OUTER_IDX) - 1):
                self._add_line(cur[_OUTER_IDX[k]], cur[_OUTER_IDX[k + 1]], ms, tx)
                count += 1
        return count

    def _draw_ribs(
        self,
        section_pts: dict[str, list[list[Any]]],
        rib_stations: list[dict[str, Any]],
        ms: Any,
        tx: Any,
    ) -> int:
        """One filled rectangle per lateral rib segment at each rib station (inf_rl_ribs)."""
        half = _RIB_HALF
        count = 0

        sorted_keys = sorted(section_pts.keys(), key=lambda k: float(k))
        sorted_floats = [float(k) for k in sorted_keys]

        def _interp_pts(sta: float) -> list[list[float]]:
            if sta <= sorted_floats[0]:
                return section_pts[sorted_keys[0]]
            if sta >= sorted_floats[-1]:
                return section_pts[sorted_keys[-1]]
            for j in range(len(sorted_floats) - 1):
                s0, s1 = sorted_floats[j], sorted_floats[j + 1]
                if s0 <= sta <= s1:
                    t = (sta - s0) / (s1 - s0) if s1 > s0 else 0.0
                    p0 = section_pts[sorted_keys[j]]
                    p1 = section_pts[sorted_keys[j + 1]]
                    return [
                        [
                            p0[i][0] + t * (p1[i][0] - p0[i][0]),
                            p0[i][1] + t * (p1[i][1] - p0[i][1]),
                            p0[i][2] + t * (p1[i][2] - p0[i][2]),
                        ]
                        for i in range(len(p0))
                    ]
            return section_pts[sorted_keys[-1]]

        for rec in rib_stations:
            laterals = rec.get("laterals", [])
            pts = _interp_pts(rec["station"])
            cx, cy = pts[2][0], pts[2][1]
            p1x, p1y = pts[1][0], pts[1][1]
            p3x, p3y = pts[3][0], pts[3][1]
            dx, dy = p3x - p1x, p3y - p1y
            lat_len = math.sqrt(dx * dx + dy * dy)
            if lat_len < 1e-6:
                continue
            rx, ry = dx / lat_len, dy / lat_len
            ax, ay = -ry, rx

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
                pl.Layer = RIBS_LAYER
                ms.AppendEntity(pl)
                tx.AddNewlyCreatedDBObject(pl, True)

                rib_ids = ObjectIdCollection()
                rib_ids.Add(pl.ObjectId)
                h = Hatch()
                h.SetDatabaseDefaults()
                h.PatternScale = 1.0
                h.SetHatchPattern(HatchPatternType.PreDefined, "SOLID")
                h.HatchStyle = HatchStyle.Normal
                h.Layer = RIBS_LAYER
                ms.AppendEntity(h)
                tx.AddNewlyCreatedDBObject(h, True)
                h.Associative = True
                h.AppendLoop(HatchLoopTypes.Outermost, rib_ids)
                h.EvaluateHatch(True)
                count += 1
        return count
