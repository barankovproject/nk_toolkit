from __future__ import annotations

import datetime
import glob
import os
import traceback
from typing import Any

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import OpenMode, Poly3dType, Polyline3d
from Autodesk.AutoCAD.Geometry import Point3d, Point3dCollection

from civil.alignment import AlignmentWrapper

# Alignment/surface lookup is shared with the ditch scripts — imported, not copied.
from ditch_core.selection import find_alignment_and_surface

from ditch_core.config import CONFIG, CUT_EPS

from .layers import ensure_ct_filter, ensure_ct_layers
from .toe_solver import cut_toe_at

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
_LOG_PREFIX = "cut_toe_line"

_LAYER = "inf_ct_toe"
_LAYER_PREFIX = "inf_ct_"
_REGAPP = "ARHYZ_CT"


def _trim_logs(log_dir: str, prefix: str, keep: int = 10) -> None:
    for f in sorted(glob.glob(os.path.join(log_dir, f"{prefix}_*.log")))[:-keep]:
        try:
            os.remove(f)
        except OSError:
            pass


class CutToeLineBuilder:
    """Draws the toe of the cut slope (подошва откоса выемки) along an alignment.

    Walks the alignment at CONFIG.step and, at each station with a cut side,
    locates the toe (the same point ditch_core calls ditch.top). The
    toe points are joined into continuous blue 3D polylines on inf_ct_toe, broken
    wherever a station has no cut side. Regenerate model: every run purges the
    script's own entities for this alignment, then redraws — re-running after a
    surface edit is clean, never additive.
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
        drawn = 0

        try:
            doc = Application.DocumentManager.MdiActiveDocument
            db = doc.Database

            lock = doc.LockDocument()
            try:
                tx = db.TransactionManager.StartTransaction()
                try:
                    ensure_ct_layers(db, tx)
                    self._ensure_regapp(db, tx)
                    log("layers ensured")

                    align, surface = find_alignment_and_surface(
                        tx, CONFIG.alignment_name, CONFIG.surface_name
                    )
                    align_name = align.Name
                    log(f"alignment '{align_name}', surface '{surface.Name}'")

                    sta_start = float(align.StartingStation)
                    sta_end = float(align.EndingStation)
                    align_w = AlignmentWrapper(align, sta_end)

                    ms = tx.GetObject(db.CurrentSpaceId, OpenMode.ForWrite)

                    purged = self._purge_entities(ms, tx, align_name)
                    log(
                        f"purged {purged} existing toe-line entity(ies) for '{align_name}'"
                    )

                    runs, n_sta, n_hit = self._collect_runs(
                        surface, align_w, sta_start, sta_end, log
                    )
                    log(
                        f"walked {n_sta} station(s), {n_hit} with a cut side, "
                        f"{len(runs)} contiguous run(s)"
                    )

                    drawn = self._draw_runs(runs, ms, tx, align_name, log)
                    log(f"drawn {drawn} toe polyline(s)")

                    tx.Commit()
                    log("transaction committed")
                except Exception:
                    tx.Abort()
                    raise
                finally:
                    tx.Dispose()

                # filter must be set inside the document lock but outside any transaction
                try:
                    fname = ensure_ct_filter(db)
                    log(f"layer filter '{fname}' ensured")
                except Exception as e:
                    log(f"layer filter warning: {e}", "WARN")
            finally:
                lock.Dispose()

        except Exception as ex:
            errors.insert(0, f"ERROR: {ex}")
            log(f"ERROR: {ex}", "CRITICAL")
            log(traceback.format_exc(), "CRITICAL")

        log(f"=== DONE: drawn={drawn}, errors={len(errors)} ===")
        return drawn if not errors else errors

    def _collect_runs(
        self,
        surface: Any,
        align_w: Any,
        sta_start: float,
        sta_end: float,
        log: Any,
    ) -> tuple[list[list[tuple[float, float, float]]], int, int]:
        """Walk the alignment; group consecutive cut-toe points into runs.

        A station with no cut side ends the current run (a gap in the toe line);
        the next cut station starts a fresh run. Returns (runs, stations_walked,
        stations_with_toe).
        """
        runs: list[list[tuple[float, float, float]]] = []
        current: list[tuple[float, float, float]] = []
        n_sta = 0
        n_hit = 0

        sta = sta_start
        while sta <= sta_end + 1e-9:
            n_sta += 1
            try:
                toe = cut_toe_at(surface, align_w, sta, CONFIG, CUT_EPS)
            except Exception as e:
                # a single bad station never aborts the run — just breaks the line
                toe = None
                log(f"  sta {sta:8.3f}: toe probe failed ({e}) — gap", "WARN")
            if toe is None:
                if current:
                    runs.append(current)
                    current = []
            else:
                n_hit += 1
                current.append(toe)
            sta += CONFIG.step

        if current:
            runs.append(current)
        return runs, n_sta, n_hit

    def _draw_runs(
        self,
        runs: list[list[tuple[float, float, float]]],
        ms: Any,
        tx: Any,
        align_name: str,
        log: Any,
    ) -> int:
        """Draw one tagged blue 3D polyline per run of ≥ 2 toe points."""
        drawn = 0
        for i, run in enumerate(runs, 1):
            if len(run) < 2:
                log(f"  run #{i}: only {len(run)} point — skipped (needs ≥ 2)", "WARN")
                continue
            pts = Point3dCollection()
            for p in run:
                pts.Add(Point3d(*p))
            pl = Polyline3d(Poly3dType.SimplePoly, pts, False)
            pl.Layer = _LAYER
            ms.AppendEntity(pl)
            tx.AddNewlyCreatedDBObject(pl, True)
            self._tag_entity(pl, tx, align_name)
            drawn += 1
            log(f"  run #{i}: {len(run)} pts, Z {run[0][2]:.2f}->{run[-1][2]:.2f}")
        return drawn

    def _ensure_regapp(self, db: Any, tx: Any) -> None:
        """Register ARHYZ_CT in RegAppTable so XData can be attached."""
        from Autodesk.AutoCAD.DatabaseServices import RegAppTable, RegAppTableRecord

        rat = tx.GetObject(db.RegAppTableId, OpenMode.ForRead)
        if not rat.Has(_REGAPP):
            rat.UpgradeOpen()
            ratr = RegAppTableRecord()
            ratr.Name = _REGAPP
            rat.Add(ratr)
            tx.AddNewlyCreatedDBObject(ratr, True)

    def _tag_entity(self, ent: Any, tx: Any, align_name: str) -> None:
        """Attach XData ARHYZ_CT=align_name so re-runs can purge only this alignment."""
        from Autodesk.AutoCAD.DatabaseServices import ResultBuffer, TypedValue

        ent.XData = ResultBuffer(
            TypedValue(1001, _REGAPP),
            TypedValue(1000, align_name),
        )

    def _purge_entities(self, ms: Any, tx: Any, align_name: str) -> int:
        """Erase inf_ct_* entities tagged with this alignment name only."""
        to_erase: list[Any] = []
        for oid in ms:
            try:
                ent = tx.GetObject(oid, OpenMode.ForRead)
                if not ent.Layer.startswith(_LAYER_PREFIX):
                    continue
                rb = ent.GetXDataForApplication(_REGAPP)
                if rb is None:
                    continue
                name = next((str(tv.Value) for tv in rb if tv.TypeCode == 1000), None)
                if name == align_name:
                    to_erase.append(oid)
            except Exception:
                pass
        for oid in to_erase:
            try:
                tx.GetObject(oid, OpenMode.ForWrite).Erase()
            except Exception:
                pass
        return len(to_erase)
