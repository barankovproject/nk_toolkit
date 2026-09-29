"""Draw the gabion placement scheme (схема расположения габионов) for one canal.

Starter version: the gabion outer outline (P7/P4 in plan) filled with a HONEY hatch,
on its own inf_gl_* layers — a separate drawing from the location plan, to be extended
later with GSI section divisions and numbering.

Loads section_points from the canal data JSON (by query). Entities are XData-tagged with
the canal name (RegApp ARHYZ_GL, code 1000) so re-runs replace only that canal.
"""

from __future__ import annotations

import datetime
import glob
import json
import os
from typing import Any, Optional

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

from .layers import ensure_gl_filter, ensure_gl_layers

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
_LOG_PREFIX = "draw_gabion_layout"

_REGAPP = "ARHYZ_GL"
OUTLINE_LAYER = "inf_gl_outline"
HATCH_LAYER = "inf_gl_hatch"
SHELL_LAYER = "inf_gl_gabion_3d"
HATCH_PATTERN = "HONEY"
HATCH_SCALE = 0.1
# outer gabion shell point indices: P7-P6-P5-P4 (same as draw_location_plan)
_OUTER_IDX = (8, 7, 6, 5)


def _trim_logs(log_dir: str, prefix: str, keep: int = 10) -> None:
    for f in sorted(glob.glob(os.path.join(log_dir, f"{prefix}_*.log")))[:-keep]:
        try:
            os.remove(f)
        except OSError:
            pass


class GabionLayoutBuilder:
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
        log("=== draw_gabion_layout ===")
        log(f"query={self.query!r}")

        section_pts = self._load_section_pts()
        if not section_pts:
            log(
                f"ERROR: no section_points for '{self.query}' — run build_canal_model first"
            )
            return f"no section_points for '{self.query}'"
        log(f"loaded {len(section_pts)} stations")

        doc = Application.DocumentManager.MdiActiveDocument
        db = doc.Database

        lock = doc.LockDocument()
        try:
            tx = db.TransactionManager.StartTransaction()
            try:
                ensure_gl_layers(db, tx)
                self._ensure_regapp(db, tx)
                ms = tx.GetObject(db.CurrentSpaceId, OpenMode.ForWrite)

                erased = self._purge(ms, tx, self.query)
                log(f"purged {erased} existing entities")

                outline_oid = self._draw_outline(section_pts, ms, tx)
                log(f"outline: {'OK' if outline_oid else 'SKIP'}")
                if outline_oid is not None:
                    self._draw_hatch(outline_oid, ms, tx)
                    log("hatch: OK")

                n_shell = self._draw_gabion_3d(section_pts, ms, tx)
                log(f"gabion shell 3d lines: {n_shell}")

                tagged = self._tag(ms, tx, self.query)
                log(f"tagged {tagged} entities")
                tx.Commit()
                log("transaction committed")
            except Exception:
                tx.Abort()
                raise
            finally:
                tx.Dispose()

            # filter must be set inside the document lock but outside any transaction
            try:
                fname = ensure_gl_filter(db)
                log(f"layer filter '{fname}' ensured")
            except Exception as e:
                log(f"layer filter warning: {e}")
        finally:
            lock.Dispose()

        log("=== DONE ===")
        return "OK"

    def _load_section_pts(self) -> dict[str, list[list[Any]]]:
        norm = normalize(self.query)
        if os.path.isdir(CANALS_DATA_DIR):
            for fname in os.listdir(CANALS_DATA_DIR):
                if fname.endswith(".json") and normalize(fname[:-5]) == norm:
                    with open(
                        os.path.join(CANALS_DATA_DIR, fname), encoding="utf-8"
                    ) as f:
                        return json.load(f).get("section_points", {})
        return {}

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
            if not ent.Layer.startswith("inf_gl_"):
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
            if not ent.Layer.startswith("inf_gl_"):
                continue
            if ent.GetXDataForApplication(_REGAPP) is not None:
                continue
            ent.UpgradeOpen()
            ent.XData = rb
            n += 1
        return n

    def _draw_outline(
        self, section_pts: dict[str, list[list[Any]]], ms: Any, tx: Any
    ) -> Optional[Any]:
        """Closed 2D polyline along the gabion outer boundary: P7 (idx 8) fwd + P4 (idx 5) rev."""
        stations = sorted(section_pts.keys(), key=lambda k: float(k))
        if len(stations) < 2:
            return None
        left = [section_pts[s][8][:2] for s in stations]
        right = [section_pts[s][5][:2] for s in reversed(stations)]
        pl = Polyline()
        pl.SetDatabaseDefaults()
        for i, (x, y) in enumerate(left + right):
            pl.AddVertexAt(i, Point2d(x, y), 0.0, 0.0, 0.0)
        pl.Closed = True
        pl.Layer = OUTLINE_LAYER
        ms.AppendEntity(pl)
        tx.AddNewlyCreatedDBObject(pl, True)
        return pl.ObjectId

    def _add_line(self, p1: Any, p2: Any, ms: Any, tx: Any) -> None:
        ln = Line(p1, p2)
        ln.Layer = SHELL_LAYER
        ms.AppendEntity(ln)
        tx.AddNewlyCreatedDBObject(ln, True)

    def _draw_gabion_3d(
        self, section_pts: dict[str, list[list[Any]]], ms: Any, tx: Any
    ) -> int:
        """Outer gabion shell wireframe P7-P6-P5-P4 (like draw_location_plan._draw_gabion_3d)."""
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

    def _draw_hatch(self, outline_oid: Any, ms: Any, tx: Any) -> None:
        loop_ids = ObjectIdCollection()
        loop_ids.Add(outline_oid)
        h = Hatch()
        h.SetDatabaseDefaults()
        h.PatternScale = HATCH_SCALE
        h.SetHatchPattern(HatchPatternType.PreDefined, HATCH_PATTERN)
        h.HatchStyle = HatchStyle.Normal
        h.Layer = HATCH_LAYER
        ms.AppendEntity(h)
        tx.AddNewlyCreatedDBObject(h, True)
        h.Associative = True
        h.AppendLoop(HatchLoopTypes.Outermost, loop_ids)
        h.EvaluateHatch(True)
