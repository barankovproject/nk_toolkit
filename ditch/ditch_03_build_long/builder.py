from __future__ import annotations

import datetime
import glob
import math
import os
import traceback
from typing import Any, Optional

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import (
    OpenMode,
    Poly3dType,
    Polyline,
    Polyline2d,
    Polyline3d,
    SymbolUtilityServices,
)
from Autodesk.AutoCAD.Geometry import Point3d, Point3dCollection
from Autodesk.Civil.ApplicationServices import CivilApplication
from Autodesk.Civil.DatabaseServices import TinSurface

from civil.utils import find_best_match

from ditch_core.config import CONFIG, DROP, SOURCE_LAYER, trasse_for_layer

from .property_sets import ensure_ld_psd, write_ld_ps
from .volumes import ld_volumes

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
_LOG_PREFIX = "long_ditches"
_REGAPP = "ARHYZ_LD"


def _trim_logs(log_dir: str, prefix: str, keep: int = 10) -> None:
    for f in sorted(glob.glob(os.path.join(log_dir, f"{prefix}_*.log")))[:-keep]:
        try:
            os.remove(f)
        except OSError:
            pass


class LongitudinalDitchBuilder:
    """Drape the user's 2D longitudinal-ditch polylines onto the trasse surface.

    Each flat polyline on SOURCE_LAYER is turned into a 3D polyline whose vertices
    sit DROP metres below the surface, and the original 2D polyline is replaced by
    it (same layer). Volumes are computed later; this only builds the geometry.
    Idempotent: only 2D polylines are converted, so a re-run is a no-op.
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
        converted = 0

        try:
            doc = Application.DocumentManager.MdiActiveDocument
            db = doc.Database

            lock = doc.LockDocument()
            try:
                tx = db.TransactionManager.StartTransaction()
                try:
                    self._ensure_regapp(db, tx)
                    psd_id = ensure_ld_psd(db, tx)
                    surface = self._find_surface(tx)
                    log(f"surface '{surface.Name}', source layer '{SOURCE_LAYER}'")

                    ms = tx.GetObject(
                        SymbolUtilityServices.GetBlockModelSpaceId(db),
                        OpenMode.ForWrite,
                    )
                    converted, skipped = self._convert(ms, tx, surface, psd_id, log)
                    log(f"converted {converted} polyline(s), {skipped} skipped")

                    tx.Commit()
                    log("transaction committed")
                except Exception:
                    tx.Abort()
                    raise
                finally:
                    tx.Dispose()
            finally:
                lock.Dispose()

        except Exception as ex:
            errors.insert(0, f"ERROR: {ex}")
            log(f"ERROR: {ex}", "CRITICAL")
            log(traceback.format_exc(), "CRITICAL")

        log(f"=== DONE: converted={converted}, errors={len(errors)} ===")
        return converted if not errors else errors

    def _convert(
        self, ms: Any, tx: Any, surface: Any, psd_id: Any, log: Any
    ) -> tuple[int, int]:
        """Drape ditch polylines on SOURCE_LAYER onto the surface (Z = surface − DROP).

        A flat 2D polyline is converted to 3D; an already-converted 3D polyline
        (tagged ARHYZ_LD) is re-draped from its current XY, so a DROP change or a
        manual XY edit takes effect on re-run. Other 3D polylines on the layer
        (e.g. ditch_01_draw_cut_toe's ARHYZ_CT toe lines) are left untouched. The
        snapshot of oids is taken first so freshly added 3D lines aren't re-processed.
        """
        oids = list(ms)
        converted = 0
        skipped = 0
        per_canal: dict[str, int] = {}  # 1-based ditch index within each canal
        for oid in oids:
            try:
                ent = tx.GetObject(oid, OpenMode.ForRead)
            except Exception:
                continue
            # Process the whole inf_ct_toe family: bare base + per-canal suffixed
            # layers (inf_ct_toe_<trasse>). The canal comes from the layer suffix,
            # not a flat config value, so each ditch keeps its own canal on re-run.
            orig_layer = ent.Layer
            canal = trasse_for_layer(orig_layer, SOURCE_LAYER)
            if canal is None:  # not a longitudinal-ditch layer
                continue
            is_3d = isinstance(ent, Polyline3d)
            if is_3d and not self._is_ld(ent):
                continue  # foreign 3D line on the layer — leave it
            if not is_3d and not isinstance(ent, (Polyline, Polyline2d)):
                continue

            pts_xy = self._vertices_xy(ent, tx)
            if len(pts_xy) < 2:
                continue
            draped = self._drape(pts_xy, surface, log)
            if len(draped) < 2:
                skipped += 1
                log("  polyline skipped: <2 vertices on surface", "WARN")
                continue

            closed = bool(getattr(ent, "Closed", False))
            pl = self._add_pl3d(draped, closed, orig_layer, ms, tx)
            ent.UpgradeOpen()
            ent.Erase()
            converted += 1
            index = per_canal[canal] = per_canal.get(canal, 0) + 1

            length_3d = self._length3d(draped)
            n_turns = self._plan_turns(draped, closed)
            vols = ld_volumes(length_3d, n_turns)
            write_ld_ps(
                pl, psd_id, tx, canal=canal, index=index, length_3d=length_3d, vols=vols
            )
            zs = [p[2] for p in draped]
            log(
                f"  #{converted} {'re-draped' if is_3d else 'converted'}: "
                f"{len(draped)} verts, {n_turns} turn(s), Z {min(zs):.2f}..{max(zs):.2f}"
                f"{' (closed)' if closed else ''} L3D={length_3d:.2f} "
                f"exc={vols['VolExcavation']:.2f} stone={vols['VolStone']:.2f} "
                f"geo={vols['VolGeotextile']:.2f} move={vols['MoveTonnage']:.2f} "
                f"mat={vols['MatCount']:.1f}шт/{vols['MatArea']:.1f}m2 "
                f"anch={vols['AnchorCount']:.1f}"
            )
        return converted, skipped

    def _length3d(self, pts: list[tuple[float, float, float]]) -> float:
        """Total 3D length over consecutive draped vertices."""
        return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))

    def _plan_turns(
        self, pts: list[tuple[float, float, float]], closed: bool, eps_deg: float = 5.0
    ) -> int:
        """Count plan bends — interior vertices whose XY deflection exceeds eps_deg.

        A near-collinear vertex (offset polylines can carry redundant points) is
        not a turn. For a closed polyline the wrap-around vertex is also checked.
        """
        n = len(pts)
        if n < 3:
            return 0
        eps = math.radians(eps_deg)

        def ang(a: Any, b: Any) -> float:
            return math.atan2(b[1] - a[1], b[0] - a[0])

        def deflect(i: int) -> float:
            d = ang(pts[i], pts[i + 1]) - ang(pts[i - 1], pts[i])
            while d > math.pi:
                d -= 2 * math.pi
            while d < -math.pi:
                d += 2 * math.pi
            return abs(d)

        turns = sum(1 for i in range(1, n - 1) if deflect(i) > eps)
        if closed and deflect(0) > eps:  # wrap-around at the closing vertex
            turns += 1
        return turns

    def _is_ld(self, ent: Any) -> bool:
        """True if the entity carries this script's ARHYZ_LD XData tag."""
        try:
            return ent.GetXDataForApplication(_REGAPP) is not None
        except Exception:
            return False

    def _vertices_xy(self, ent: Any, tx: Any) -> list[tuple[float, float]]:
        """Ordered (x, y) of a lightweight Polyline, Polyline2d or Polyline3d. Z ignored."""
        pts: list[tuple[float, float]] = []
        if isinstance(ent, Polyline):
            for i in range(ent.NumberOfVertices):
                p = ent.GetPoint3dAt(i)
                pts.append((float(p.X), float(p.Y)))
        else:  # Polyline2d / Polyline3d — iterate vertex objects
            for vid in ent:
                try:
                    p = tx.GetObject(vid, OpenMode.ForRead).Position
                    pts.append((float(p.X), float(p.Y)))
                except Exception:
                    continue
        return pts

    def _drape(
        self, pts_xy: list[tuple[float, float]], surface: Any, log: Any
    ) -> list[tuple[float, float, float]]:
        """Map (x, y) to (x, y, surface_Z − DROP); drop vertices off the surface."""
        out: list[tuple[float, float, float]] = []
        for x, y in pts_xy:
            try:
                z = float(surface.FindElevationAtXY(x, y)) - DROP
            except Exception:
                log(f"  vertex ({x:.2f}, {y:.2f}) off surface — dropped", "WARN")
                continue
            out.append((x, y, z))
        return out

    def _add_pl3d(
        self,
        pts: list[tuple[float, float, float]],
        closed: bool,
        layer: str,
        ms: Any,
        tx: Any,
    ) -> Any:
        """Add a draped 3D polyline on `layer`, tagged ARHYZ_LD.

        The layer is the source polyline's own layer (bare inf_ct_toe or a
        per-canal inf_ct_toe_<trasse>), so the rebuild keeps the canal suffix the
        refresh reads — never flattened back to the bare base layer.
        """
        col = Point3dCollection()
        for p in pts:
            col.Add(Point3d(*p))
        pl = Polyline3d(Poly3dType.SimplePoly, col, closed)
        pl.Layer = layer
        ms.AppendEntity(pl)
        tx.AddNewlyCreatedDBObject(pl, True)
        self._tag(pl)
        return pl

    def _tag(self, ent: Any) -> None:
        """Attach XData ARHYZ_LD so a later volume pass can find the longitudinal ditch.

        A data value (1070) follows the app name — XData carrying only the 1001
        sentinel and no payload is silently dropped by AutoCAD, so the tag must
        have at least one value to persist.
        """
        from Autodesk.AutoCAD.DatabaseServices import ResultBuffer, TypedValue

        ent.XData = ResultBuffer(TypedValue(1001, _REGAPP), TypedValue(1070, 1))

    def _ensure_regapp(self, db: Any, tx: Any) -> None:
        """Register ARHYZ_LD in RegAppTable so XData can be attached."""
        from Autodesk.AutoCAD.DatabaseServices import RegAppTable, RegAppTableRecord

        rat = tx.GetObject(db.RegAppTableId, OpenMode.ForRead)
        if not rat.Has(_REGAPP):
            rat.UpgradeOpen()
            ratr = RegAppTableRecord()
            ratr.Name = _REGAPP
            rat.Add(ratr)
            tx.AddNewlyCreatedDBObject(ratr, True)

    def _find_surface(self, tx: Any) -> Any:
        """Fuzzy-match the trasse TIN surface by CONFIG.surface_name; raise if none."""
        civil_db = CivilApplication.ActiveDocument
        surfaces: list[Any] = []
        for oid in civil_db.GetSurfaceIds():
            try:
                ent = tx.GetObject(oid, OpenMode.ForRead)
                if isinstance(ent, TinSurface):
                    surfaces.append(ent)
            except Exception:
                continue
        names = [s.Name for s in surfaces]
        match: Optional[tuple[int, str]] = find_best_match(CONFIG.surface_name, names)
        if match is None:
            raise Exception(
                f"No TIN surface matching '{CONFIG.surface_name}'. Available: {names}"
            )
        return surfaces[match[0]]
