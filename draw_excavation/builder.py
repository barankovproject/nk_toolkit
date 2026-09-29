"""Draw the canal excavation pit (котлован) in plan from corridor feature lines.

Per corridor (all entities are 3D polylines), everything comes from corridor feature
lines so it shares the corridor's section stations:
  - top edge / бровка  = closed Polyline3d from the 'Daylight' feature lines
  - pit bottom / дно    = closed Polyline3d from the 'Channel_Bottom' feature lines
  - divisions / поперечины = one Polyline3d per section station tracing the cut:
                          Daylight-left → Channel_Bottom-left → Channel_Bottom-right → Daylight-right
                          (paired by station, inner points ordered to avoid self-crossing)

Layers + the 'Excavation' filter come from layers.json. Entities are XData-tagged with
the corridor name (RegApp ARHYZ_EXC, code 1000) so re-runs replace only that corridor.

ExcavationBuilder(query): empty query → all corridors; non-empty → the matching one.
"""

from __future__ import annotations

import datetime
import glob
import os
from typing import Any, Optional

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import (
    OpenMode,
    RegAppTable,
    RegAppTableRecord,
    ResultBuffer,
    TypedValue,
)
from Autodesk.Civil.ApplicationServices import CivilApplication

from civil.utils import find_best_match, safe_iter, safe_resolve

from .layers import ensure_exc_filter, ensure_exc_layers

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
_LOG_PREFIX = "draw_excavation"

_REGAPP = "ARHYZ_EXC"
TOP_CODE = "Daylight"  # бровка (pit top edge)
BOTTOM_CODE = "Channel_Bottom"  # дно котлована (pit bottom edge)
CENTER_CODE = "Channel_Flowline"  # centerline (offset 0)
TOP_LAYER = "inf_exc_top"
BOTTOM_LAYER = "inf_exc_bottom"
DIVISION_LAYER = "inf_exc_division"
SLOPE_LAYER = "inf_exc_slope"  # captured corridor slope-pattern geometry (бергштрихи)
CENTER_LAYER = "inf_exc_centerline"


def _trim_logs(log_dir: str, prefix: str, keep: int = 10) -> None:
    for f in sorted(glob.glob(os.path.join(log_dir, f"{prefix}_*.log")))[:-keep]:
        try:
            os.remove(f)
        except OSError:
            pass


class ExcavationBuilder:
    def __init__(self, query: str = "") -> None:
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
        log("=== draw_excavation ===")
        log(
            f"query={self.query!r}  top={TOP_CODE!r}  bottom={BOTTOM_CODE!r} (both corridor FL)"
        )

        doc = Application.DocumentManager.MdiActiveDocument
        db = doc.Database
        civil_db = CivilApplication.ActiveDocument

        results: list[str] = []
        lock = doc.LockDocument()
        try:
            tx = db.TransactionManager.StartTransaction()
            try:
                ensure_exc_layers(db, tx)
                self._ensure_regapp(db, tx)
                ms = tx.GetObject(db.CurrentSpaceId, OpenMode.ForWrite)

                cc = civil_db.CorridorCollection
                corridors: list[Any] = []
                names: list[str] = []
                for raw in safe_iter(cc):
                    corr = safe_resolve(raw, tx)
                    if corr is None:
                        continue
                    corridors.append(corr)
                    names.append(corr.Name)

                targets = self._select(corridors, names)
                log(f"corridors: {len(names)}  selected: {len(targets)}\n")

                for corr in targets:
                    results.append(self._draw_one(corr, ms, tx))
                    log(results[-1])

                tx.Commit()
                log("\ntransaction committed")
            except Exception:
                tx.Abort()
                raise
            finally:
                tx.Dispose()

            # filter must be set inside the document lock but outside any transaction
            try:
                fname = ensure_exc_filter(db)
                log(f"layer filter '{fname}' ensured")
            except Exception as e:
                log(f"layer filter warning: {e}")
        finally:
            lock.Dispose()

        ok = sum(1 for r in results if "top:OK" in r)
        log(f"\n--- {ok}/{len(results)} corridors with top outline ---")
        log("=== DONE ===")
        return "\n".join(results)

    def _select(self, corridors: list[Any], names: list[str]) -> list[Any]:
        if not self.query:
            return corridors
        match = find_best_match(self.query, names)
        if match is None:
            return []
        return [corridors[match[0]]]

    def _ensure_regapp(self, db: Any, tx: Any) -> None:
        rat = tx.GetObject(db.RegAppTableId, OpenMode.ForRead)
        if not rat.Has(_REGAPP):
            rat.UpgradeOpen()
            ratr = RegAppTableRecord()
            ratr.Name = _REGAPP
            rat.Add(ratr)
            tx.AddNewlyCreatedDBObject(ratr, True)

    def _draw_one(self, corr: Any, ms: Any, tx: Any) -> str:
        name = corr.Name
        try:
            self._purge(ms, tx, name)

            dl, dr = self._fl_lr(corr, TOP_CODE)  # бровка left/right (sta,x,y,z)
            if dl is None:
                return f"  {name:30s} SKIP (no {TOP_CODE})  tagged=0"
            self._add_polyline3d(self._loop(dr, dl), TOP_LAYER, True, ms, tx)
            s_top = f"OK ({len(dl) + len(dr)} pts)"

            bl, br = self._fl_lr(corr, BOTTOM_CODE)  # дно left/right
            if bl is None:
                s_bot, n_div = f"SKIP (no {BOTTOM_CODE})", 0
            else:
                self._add_polyline3d(self._loop(bl, br), BOTTOM_LAYER, True, ms, tx)
                s_bot = f"OK ({len(bl) + len(br)} pts)"
                n_div = self._draw_divisions(dl, dr, bl, br, ms, tx)

            n_slope = self._capture_slope(corr, ms, tx)
            n_center = self._draw_centerline(corr, ms, tx)
            tagged = self._tag(ms, tx, name)
            return (
                f"  {name:30s} top:{s_top}  bottom:{s_bot}  div={n_div}  "
                f"slope={n_slope}  center={n_center}  tagged={tagged}"
            )
        except Exception as e:
            return f"  {name:30s} FAIL: {type(e).__name__}: {e}"

    def _purge(self, ms: Any, tx: Any, corridor_name: str) -> int:
        to_erase: list[Any] = []
        for oid in ms:
            ent = tx.GetObject(oid, OpenMode.ForRead)
            if not ent.Layer.startswith("inf_exc_"):
                continue
            rb = ent.GetXDataForApplication(_REGAPP)
            if rb is None:
                continue
            nm = next((str(tv.Value) for tv in rb if tv.TypeCode == 1000), None)
            if nm == corridor_name:
                to_erase.append(oid)
        for oid in to_erase:
            tx.GetObject(oid, OpenMode.ForWrite).Erase()
        return len(to_erase)

    def _tag(self, ms: Any, tx: Any, corridor_name: str) -> int:
        rb = ResultBuffer(TypedValue(1001, _REGAPP), TypedValue(1000, corridor_name))
        n = 0
        for oid in ms:
            ent = tx.GetObject(oid, OpenMode.ForRead)
            if not ent.Layer.startswith("inf_exc_"):
                continue
            if ent.GetXDataForApplication(_REGAPP) is not None:
                continue
            ent.UpgradeOpen()
            ent.XData = rb
            n += 1
        return n

    # --- feature-line extraction -----------------------------------------------

    def _fls_for_code(self, corr: Any, code: str) -> list[Any]:
        try:
            bl = list(corr.Baselines)[0]
            fl_map = bl.MainBaselineFeatureLines.FeatureLineCollectionMap
            return list(fl_map[code])
        except Exception:
            return []

    @staticmethod
    def _fl_pts(fl: Any) -> list[tuple[float, float, float, float]]:
        return [
            (float(fp.Station), fp.XYZ.X, fp.XYZ.Y, fp.XYZ.Z)
            for fp in fl.FeatureLinePoints
        ]

    @staticmethod
    def _first_offset(fl: Any) -> float:
        for fp in fl.FeatureLinePoints:
            return float(fp.Offset)
        return 0.0

    def _fl_lr(self, corr: Any, code: str) -> tuple[Optional[list], Optional[list]]:
        """Return (left, right) of the two main feature lines for a code as (station, x, y, z)."""
        fls = self._fls_for_code(corr, code)
        if len(fls) < 2:
            return None, None
        main = sorted(
            fls, key=lambda fl: len(list(fl.FeatureLinePoints)), reverse=True
        )[:2]
        a, b = main[0], main[1]
        oa, ob = self._first_offset(a), self._first_offset(b)
        if oa >= 0 and ob < 0:
            fl_r, fl_l = a, b
        elif ob >= 0 and oa < 0:
            fl_r, fl_l = b, a
        else:
            fl_r, fl_l = a, b
        left, right = self._fl_pts(fl_l), self._fl_pts(fl_r)
        if not left or not right:
            return None, None
        return left, right

    @staticmethod
    def _loop(side_a: list, side_b: list) -> list:
        """Closed-loop XYZ vertices: side_a forward + side_b reversed."""
        return [(x, y, z) for _s, x, y, z in side_a] + [
            (x, y, z) for _s, x, y, z in reversed(side_b)
        ]

    @staticmethod
    def _order_along(a: tuple, b: tuple, pts: list) -> list:
        """Order points by projection onto the a→b direction (keeps the cut monotonic)."""
        dx, dy = b[0] - a[0], b[1] - a[1]
        return sorted(pts, key=lambda p: (p[0] - a[0]) * dx + (p[1] - a[1]) * dy)

    def _draw_divisions(
        self, dl: list, dr: list, bl: list, br: list, ms: Any, tx: Any
    ) -> int:
        """Transverse cut per station: бровка → дно (Channel_Bottom) corners → бровка.

        Both бровка and дно are corridor feature lines, so дно corners are matched to the
        бровка station directly (no interpolation). Inner points are ordered along the cut
        to avoid self-crossing if the corridor offset sign flips between feature lines.
        """
        bl_map = {round(s, 3): (x, y, z) for s, x, y, z in bl}
        br_map = {round(s, 3): (x, y, z) for s, x, y, z in br}
        n = min(len(dl), len(dr))
        count = 0
        for i in range(n):
            sta = dl[i][0]
            top_l = (dl[i][1], dl[i][2], dl[i][3])
            top_r = (dr[i][1], dr[i][2], dr[i][3])
            key = round(sta, 3)
            inner = [p for p in (bl_map.get(key), br_map.get(key)) if p is not None]
            inner = self._order_along(top_l, top_r, inner)
            self._add_polyline3d(
                [top_l] + inner + [top_r], DIVISION_LAYER, False, ms, tx
            )
            count += 1
        return count

    def _draw_centerline(self, corr: Any, ms: Any, tx: Any) -> int:
        """Draw the alignment centerline (Channel_Flowline FL, offset 0) as an open 3D polyline."""
        fls = self._fls_for_code(corr, CENTER_CODE)
        if not fls:
            return 0
        fl = sorted(fls, key=lambda f: len(list(f.FeatureLinePoints)), reverse=True)[0]
        pts = self._fl_pts(fl)
        if len(pts) < 2:
            return 0
        self._add_polyline3d(
            [(x, y, z) for _s, x, y, z in pts], CENTER_LAYER, False, ms, tx
        )
        return 1

    def _capture_slope(self, corr: Any, ms: Any, tx: Any) -> int:
        """Copy the corridor's slope-pattern geometry (бергштрихи) onto inf_exc_slope.

        Requires draw_corridor_slope_hatches to have run (patterns exist on the corridor).
        CorridorSlopePattern.GetGeometries() returns a DBObjectCollection of Line objects.
        """
        try:
            sp_col = corr.SlopePatterns
        except Exception:
            return 0
        count = 0
        for i in range(sp_col.Count):
            try:
                geoms = sp_col.get_Item(i).GetGeometries()
            except Exception:
                continue
            for j in range(geoms.Count):
                try:
                    ent = geoms[j].Clone()
                    ent.Layer = SLOPE_LAYER
                    ms.AppendEntity(ent)
                    tx.AddNewlyCreatedDBObject(ent, True)
                    count += 1
                except Exception:
                    pass
        return count

    # --- 3D polyline helper ----------------------------------------------------

    def _add_polyline3d(
        self, coords: list, layer: str, closed: bool, ms: Any, tx: Any
    ) -> Any:
        from Autodesk.AutoCAD.DatabaseServices import Poly3dType, Polyline3d
        from Autodesk.AutoCAD.Geometry import Point3d, Point3dCollection

        vs = Point3dCollection()
        for c in coords:
            vs.Add(Point3d(float(c[0]), float(c[1]), float(c[2])))
        pl = Polyline3d(Poly3dType.SimplePoly, vs, closed)
        pl.Layer = layer
        ms.AppendEntity(pl)
        tx.AddNewlyCreatedDBObject(pl, True)
        return pl.ObjectId
