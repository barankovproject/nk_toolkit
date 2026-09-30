from __future__ import annotations

import datetime
import glob
import math
import os
import traceback
from typing import Any

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import Circle, OpenMode, Poly3dType, Polyline3d
from Autodesk.AutoCAD.Geometry import Point3d, Point3dCollection, Vector3d

from civil.alignment import AlignmentWrapper

from . import flips_store
from .config import CONFIG
from .ditch_solver import solve_ditch
from .geometry import consistent_neighbour_sign
from .killer import build_killer
from .layers import ensure_cd_filter, ensure_cd_layers
from .property_sets import ensure_cd_psd, tag_ditch
from .selection import find_alignment_and_surface, selected_ditch_station

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
_LOG_PREFIX = "cross_ditches"
_LAYER = "inf_cd_ditch"
_LAYER_CONN = "inf_cd_connector"
_LAYER_KILLER = "inf_cd_killer"
_REGAPP = "ARHYZ_CD"


def _trim_logs(log_dir: str, prefix: str, keep: int = 10) -> None:
    for f in sorted(glob.glob(os.path.join(log_dir, f"{prefix}_*.log")))[:-keep]:
        try:
            os.remove(f)
        except OSError:
            pass


class CrossDitchBuilder:
    """Draws transverse cross-ditches across a selected alignment, spanning a
    selected TIN surface, as 2D polylines on the inf_cd_ditch layer."""

    def __init__(self, trigger: Any = None) -> None:
        # trigger is IN[0]: a ditch picked by a Dynamo ObjectSelection node to
        # flip manually (or None for a plain rebuild).
        self._trigger = trigger
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
        added = 0

        try:
            doc = Application.DocumentManager.MdiActiveDocument
            db = doc.Database

            lock = doc.LockDocument()
            try:
                tx = db.TransactionManager.StartTransaction()
                try:
                    ensure_cd_layers(db, tx)
                    self._ensure_regapp(db, tx)
                    try:
                        psd_id = ensure_cd_psd(db, tx)
                    except Exception as e:
                        psd_id = None
                        log(f"property set init failed: {e}", "WARN")
                    log("layers ensured")

                    align, surface = find_alignment_and_surface(
                        tx, CONFIG.alignment_name, CONFIG.surface_name
                    )
                    align_name = align.Name
                    surf_name = surface.Name
                    log(f"alignment '{align_name}', surface '{surf_name}'")

                    # manual flips: toggle the picked ditch's station, but only
                    # when the selection changed (the .dyn auto-runs repeatedly).
                    flipped, last_handle = flips_store.load(align_name)
                    sel = selected_ditch_station(self._trigger, tx, psd_id)
                    if sel is not None and sel[0] != last_handle:
                        handle, sel_sta = sel
                        flipped = flips_store.toggle(flipped, sel_sta)
                        flips_store.save(align_name, flipped, handle)
                        state = (
                            "flipped"
                            if flips_store.is_flipped(flipped, sel_sta)
                            else "restored"
                        )
                        log(f"manual {state} ditch at sta {sel_sta:.3f}")
                    log(f"manual flips: {[f'{s:.1f}' for s in flipped]}")

                    sta_end = float(align.EndingStation)
                    sta_start = float(align.StartingStation)
                    align_w = AlignmentWrapper(align, sta_end)

                    ms = tx.GetObject(db.CurrentSpaceId, OpenMode.ForWrite)

                    erased = self._purge_entities(ms, tx, align_name)
                    log(f"purged {erased} existing ditch(es) for '{align_name}'")

                    added = self._draw_ditches(
                        align_w,
                        surface,
                        sta_start,
                        sta_end,
                        ms,
                        tx,
                        log,
                        flipped,
                        align_name,
                        psd_id,
                    )
                    log(f"drawn {added} cross-ditch polyline(s)")

                    tagged = self._tag_entities(ms, tx, align_name)
                    log(f"tagged {tagged} new entities with '{align_name}'")

                    tx.Commit()
                    log("transaction committed")
                except Exception:
                    tx.Abort()
                    raise
                finally:
                    tx.Dispose()

                # filter must be set inside the document lock but outside any transaction
                try:
                    fname = ensure_cd_filter(db)
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

    def _draw_ditches(
        self,
        align_w: Any,
        surface: Any,
        sta_start: float,
        sta_end: float,
        ms: Any,
        tx: Any,
        log: Any,
        flipped_stations: list[float],
        align_name: str,
        psd_id: Any,
    ) -> int:
        """Place one skewed 3D cross-ditch every CONFIG.step along the alignment.

        Each ditch is solved independently (ditch_solver.solve_ditch): the skew
        angle is grown until the longitudinal grade between the two banks lands
        in the target band, both ends dropped CONFIG.ditch_depth below surface.
        Drawn as a 3D polyline from the high (нагорная) bank to the low one.
        `flipped_stations` are stations the user flipped by hand — re-solved with
        the opposite start side (a meaningful re-solve, not a mirror).
        """
        step = CONFIG.step
        count = 0
        off_surface = 0
        out_of_band = 0
        no_bank = 0
        nb_flipped = 0
        man_flipped = 0
        lengths: list[float] = []
        thetas: list[float] = []

        # stations sta_start, sta_start+step, … up to sta_end inclusive
        stations: list[float] = []
        s = sta_start
        while s < sta_end - 1e-6:
            stations.append(s)
            s += step
        stations.append(sta_end)

        # Pass 1: solve every ditch independently.
        solved: list[Optional[Any]] = [
            solve_ditch(surface, align_w, sta, CONFIG) for sta in stations
        ]

        # Pass 2: a ditch whose start side disagrees with its 2-before + 2-after
        # neighbours (which all agree) is an outlier — re-solve it forced to the
        # neighbours' side, so the whole row keeps a consistent direction.
        for i, d in enumerate(solved):
            if d is None:
                continue
            window = [
                solved[j].start_nside if 0 <= j < len(solved) and solved[j] else None
                for j in (i - 2, i - 1, i + 1, i + 2)
            ]
            row = consistent_neighbour_sign(window)
            if row is not None and d.start_nside != row:
                forced = solve_ditch(
                    surface, align_w, stations[i], CONFIG, force_start_nside=row
                )
                if forced is not None:
                    solved[i] = forced
                    nb_flipped += 1
                    log(f"  sta {stations[i]:8.3f}: start flipped to match neighbours")

        # Pass 3: manual flips win over everything — re-solve the user's chosen
        # stations with the opposite start side (выемка/насыпь roles swap, skew
        # and apron rebuild for the new direction — meaningful, not a mirror).
        for i, d in enumerate(solved):
            if d is None or not flips_store.is_flipped(flipped_stations, stations[i]):
                continue
            forced = solve_ditch(
                surface, align_w, stations[i], CONFIG, force_start_nside=-d.start_nside
            )
            if forced is not None:
                solved[i] = forced
                man_flipped += 1
                log(f"  sta {stations[i]:8.3f}: manual flip applied")

        for sta, ditch in zip(stations, solved):
            if ditch is None:
                off_surface += 1
                log(f"  sta {sta:8.3f}: axis off surface or no banks — skipped", "WARN")
                continue
            if ditch.status == "out_of_band":
                out_of_band += 1
                log(
                    f"  sta {sta:8.3f}: grade {ditch.slope:.3f} out of band "
                    f"at θ={ditch.theta_deg:.0f}° (skew capped)",
                    "WARN",
                )
            elif ditch.status == "no_bank":
                no_bank += 1
                log(
                    f"  sta {sta:8.3f}: an end hit a surface edge, not a break "
                    f"(θ={ditch.theta_deg:.0f}°)",
                    "WARN",
                )

            count += 1  # 1-based ditch number along the alignment

            cx, cy = align_w.xy_at(sta)
            # Both banks are откос выемки (both scarp rises climb): the ditch sits
            # entirely in a cut, there is no насыпь to drain onto, so no
            # гаситель/connector is built — the ditch just ends at the бровка.
            both_cut = (
                ditch.scarp_start is not None
                and ditch.scarp_start > 0.0
                and ditch.scarp_end is not None
                and ditch.scarp_end > 0.0
            )
            killer = (
                None
                if both_cut
                else build_killer(
                    surface, cx, cy, ditch.top, ditch.bot, CONFIG.ditch_depth, CONFIG
                )
            )
            # ditch ends at the connector top when the apron is built, else бровка
            ditch_end = killer.connector_top if killer is not None else ditch.bot
            length_2d = math.hypot(
                ditch_end[0] - ditch.top[0], ditch_end[1] - ditch.top[1]
            )

            def _f(v: Any) -> str:
                return f"{v:+.2f}" if v is not None else " none"

            log(
                f"  #{count:>2} sta {sta:8.3f}: θ={ditch.theta_deg:4.0f}° "
                f"start_scarp={_f(ditch.scarp_start)} end_scarp={_f(ditch.scarp_end)} "
                f"Z {ditch.top[2]:.2f}->{ditch_end[2]:.2f} L2D={length_2d:.2f}"
                f"{'' if killer else ' (no apron)'}"
            )

            # main ditch: start (выемка) → ditch_end (connector top or бровка)
            pl = self._add_pl3d(ditch.top, ditch_end, _LAYER, ms, tx)
            if psd_id is not None:
                tag_ditch(
                    pl,
                    psd_id,
                    tx,
                    alignment=align_name,
                    index=count,
                    station=sta,
                    theta_deg=ditch.theta_deg,
                    slope=ditch.slope,
                    length_2d=length_2d,
                    z_start=ditch.top[2],
                    z_end=ditch_end[2],
                    status=ditch.status,
                )

            if killer is not None:
                # connector down the откос насыпи + horizontal гаситель apron.
                # Skip the connector when the ditch joins the apron directly
                # (has_connector False) — the main ditch already ends at near.
                if killer.has_connector:
                    self._add_pl3d(
                        killer.connector_top, killer.near, _LAYER_CONN, ms, tx
                    )
                self._add_pl3d(killer.near, killer.far, _LAYER_KILLER, ms, tx)

            # circle marking the ditch start (high / нагорная end)
            circ = Circle(
                Point3d(*ditch.top),
                Vector3d(0.0, 0.0, 1.0),
                CONFIG.start_marker_d / 2.0,
            )
            circ.Layer = _LAYER
            ms.AppendEntity(circ)
            tx.AddNewlyCreatedDBObject(circ, True)

            lengths.append(length_2d)
            thetas.append(ditch.theta_deg)

        if lengths:
            log(
                f"ditch length (m): min={min(lengths):.2f} max={max(lengths):.2f} "
                f"avg={sum(lengths) / len(lengths):.2f}; "
                f"θ avg={sum(thetas) / len(thetas):.1f}° max={max(thetas):.0f}°; "
                f"{nb_flipped} nbr-flip, {man_flipped} manual-flip, "
                f"{out_of_band} out-of-band, {no_bank} edge-end, {off_surface} skipped"
            )
        return count

    def _add_pl3d(
        self,
        p1: tuple[float, float, float],
        p2: tuple[float, float, float],
        layer: str,
        ms: Any,
        tx: Any,
    ) -> Any:
        """Add a 2-point 3D polyline on `layer`; return it."""
        pts = Point3dCollection()
        pts.Add(Point3d(*p1))
        pts.Add(Point3d(*p2))
        pl = Polyline3d(Poly3dType.SimplePoly, pts, False)
        pl.Layer = layer
        ms.AppendEntity(pl)
        tx.AddNewlyCreatedDBObject(pl, True)
        return pl

    def _ensure_regapp(self, db: Any, tx: Any) -> None:
        """Register ARHYZ_CD in RegAppTable so XData can be attached."""
        from Autodesk.AutoCAD.DatabaseServices import RegAppTable, RegAppTableRecord

        rat = tx.GetObject(db.RegAppTableId, OpenMode.ForRead)
        if not rat.Has(_REGAPP):
            rat.UpgradeOpen()
            ratr = RegAppTableRecord()
            ratr.Name = _REGAPP
            rat.Add(ratr)
            tx.AddNewlyCreatedDBObject(ratr, True)

    def _purge_entities(self, ms: Any, tx: Any, align_name: str) -> int:
        """Erase inf_cd_* entities tagged with this alignment name only."""
        to_erase: list[Any] = []
        for oid in ms:
            try:
                ent = tx.GetObject(oid, OpenMode.ForRead)
                if not ent.Layer.startswith("inf_cd_"):
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

    def _tag_entities(self, ms: Any, tx: Any, align_name: str) -> int:
        """Attach XData ARHYZ_CD=align_name to every untagged inf_cd_* entity."""
        from Autodesk.AutoCAD.DatabaseServices import ResultBuffer, TypedValue

        tagged = 0
        rb_new = ResultBuffer(
            TypedValue(1001, _REGAPP),
            TypedValue(1000, align_name),
        )
        for oid in ms:
            try:
                ent = tx.GetObject(oid, OpenMode.ForRead)
                if not ent.Layer.startswith("inf_cd_"):
                    continue
                if ent.GetXDataForApplication(_REGAPP) is not None:
                    continue  # already tagged — belongs to another alignment
                ent.UpgradeOpen()
                ent.XData = rb_new
                tagged += 1
            except Exception:
                pass
        return tagged
