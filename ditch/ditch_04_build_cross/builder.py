from __future__ import annotations

import datetime
import glob
import math
import os
import traceback
from typing import Any, Optional

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import Circle, OpenMode, Poly3dType, Polyline3d
from Autodesk.AutoCAD.Geometry import Point3d, Point3dCollection, Vector3d

from civil.alignment import AlignmentWrapper

# Geometry is the cross-ditch geometry — imported, never copied. Only the station
# source (marker circles) and the output layers / purge tag differ.
from ditch_core.ditch_solver import solve_ditch
from ditch_core.geometry import consistent_neighbour_sign
from ditch_core.killer import build_killer
from ditch_core.property_sets import ensure_cd_psd, ensure_part_psd, tag_ditch, tag_part

from ditch_core.config import CANAL, CONFIG, layer_for_trasse

from .layers import ensure_md_filter, ensure_md_layer, ensure_md_layers
from .selection import collect_marker_stations, find_alignment_and_surface
from .volumes import ditch_volumes

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
_LOG_PREFIX = "marked_ditches"

_MARKER_LAYER = "inf_md_marker"
# Base layer names. Each run routes onto the canal's own suffixed variant
# (<base>_<CANAL>, see run()) so the refresh can isolate canals by suffix; the
# marker layer is USER input and is never an output (re-running must not erase it).
_LAYER = "inf_md_ditch"
_LAYER_CONN = "inf_md_connector"
_LAYER_KILLER = "inf_md_killer"
_REGAPP = "ARHYZ_MD"
# A marker whose station is within this distance (m) of an already-built ditch is
# treated as a duplicate and skipped — keeps re-runs idempotent.
_DUP_TOL = 1.0


def _trim_logs(log_dir: str, prefix: str, keep: int = 10) -> None:
    for f in sorted(glob.glob(os.path.join(log_dir, f"{prefix}_*.log")))[:-keep]:
        try:
            os.remove(f)
        except OSError:
            pass


class MarkedDitchBuilder:
    """Builds one skewed 3D cross-ditch per user-drawn marker circle.

    The user draws a circle anywhere near the alignment on the inf_md_marker
    layer; its centre is projected onto the alignment to get a station, and a
    cross-ditch identical to ditch_core is solved and drawn there.
    """

    def __init__(self) -> None:
        os.makedirs(_LOG_DIR, exist_ok=True)
        _trim_logs(_LOG_DIR, _LOG_PREFIX)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self._log_path = os.path.join(_LOG_DIR, f"{_LOG_PREFIX}_{ts}.log")
        # Per-run output layers (canal-suffixed); set in run() before any drawing.
        self._ditch_layer = _LAYER
        self._conn_layer = _LAYER_CONN
        self._killer_layer = _LAYER_KILLER
        self._output_layers: set[str] = {_LAYER, _LAYER_CONN, _LAYER_KILLER}

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
                    ensure_md_layers(db, tx)
                    # Route this run onto the canal's own layers so re-running another
                    # canal can't overwrite this one's Canal property set (the refresh
                    # isolates canals by the layer suffix). Bare base only when blank.
                    self._ditch_layer = layer_for_trasse(_LAYER, CANAL)
                    self._conn_layer = layer_for_trasse(_LAYER_CONN, CANAL)
                    self._killer_layer = layer_for_trasse(_LAYER_KILLER, CANAL)
                    self._output_layers = {
                        self._ditch_layer,
                        self._conn_layer,
                        self._killer_layer,
                    }
                    for _name, _base in (
                        (self._ditch_layer, _LAYER),
                        (self._conn_layer, _LAYER_CONN),
                        (self._killer_layer, _LAYER_KILLER),
                    ):
                        ensure_md_layer(db, tx, _name, _base)
                    self._ensure_regapp(db, tx)
                    try:
                        psd_id = ensure_cd_psd(db, tx)
                    except Exception as e:
                        psd_id = None
                        log(f"property set init failed: {e}", "WARN")
                    try:
                        part_psd_id = ensure_part_psd(db, tx)
                    except Exception as e:
                        part_psd_id = None
                        log(f"part property set init failed: {e}", "WARN")
                    log("layers ensured")

                    align, surface = find_alignment_and_surface(
                        tx, CONFIG.alignment_name, CONFIG.surface_name
                    )
                    align_name = align.Name
                    surf_name = surface.Name
                    log(f"alignment '{align_name}', surface '{surf_name}'")

                    sta_end = float(align.EndingStation)
                    sta_start = float(align.StartingStation)
                    align_w = AlignmentWrapper(align, sta_end)

                    ms = tx.GetObject(db.CurrentSpaceId, OpenMode.ForWrite)

                    stations, marker_oids = collect_marker_stations(
                        ms, tx, align, sta_start, sta_end, _MARKER_LAYER, log
                    )

                    # Additive model: keep every ditch already built for this
                    # alignment and only add ones at markers that don't yet have a
                    # ditch nearby. Re-runs are idempotent; deleting a marker does
                    # NOT remove its ditch (markers are instructions, not state).
                    existing = self._existing_ditch_stations(ms, tx, align_name, psd_id)
                    log(f"found {len(existing)} existing ditch(es) for '{align_name}'")

                    added = self._draw_ditches(
                        align_w,
                        surface,
                        stations,
                        existing,
                        ms,
                        tx,
                        log,
                        align_name,
                        psd_id,
                        part_psd_id,
                    )
                    log(f"drawn {added} marked cross-ditch(es)")

                    # Consume markers: every projected marker has now been turned
                    # into a ditch (or was a duplicate of one), so erase it. The
                    # marker layer ends up clean; unprojectable markers were not
                    # collected and stay in place.
                    consumed = self._erase_markers(marker_oids, tx)
                    log(f"consumed {consumed} marker circle(s)")

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
                    fname = ensure_md_filter(db)
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
        stations: list[float],
        existing: list[float],
        ms: Any,
        tx: Any,
        log: Any,
        align_name: str,
        psd_id: Any,
        part_psd_id: Any = None,
    ) -> int:
        """Solve and draw one skewed 3D cross-ditch at each NEW marker station.

        A marker whose station is within DUP_TOL of an already-built ditch is
        skipped (idempotent re-runs, no duplicates). Same two passes as
        ditch_core over the remaining new stations: (1) solve each ditch
        independently; (2) re-solve any ditch whose start side disagrees with its
        agreeing 2-before + 2-after neighbours, so a row of markers keeps a
        consistent direction. No manual-flip pass — markers don't flip.
        """
        kept = list(existing)
        new_stations: list[float] = []
        dup = 0
        for sta in stations:
            if any(abs(sta - e) <= _DUP_TOL for e in kept):
                dup += 1
                log(f"  sta {sta:8.3f}: ditch already exists nearby — skipped")
                continue
            new_stations.append(sta)
            kept.append(sta)  # so two close markers in one run don't both build
        log(f"{len(new_stations)} new station(s), {dup} duplicate(s) skipped")
        stations = new_stations

        count = len(existing)  # continue ditch numbering past the existing ones
        off_surface = 0
        out_of_band = 0
        no_bank = 0
        nb_flipped = 0
        lengths: list[float] = []
        thetas: list[float] = []

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
            # Only the 2-before / 2-after ditches that are actually NEAR (within
            # CONFIG.neighbour_max_dist along the alignment) count — a far ditch
            # sits on different terrain and must not force this one's direction.
            window = [
                solved[j].start_nside
                if (
                    0 <= j < len(solved)
                    and solved[j] is not None
                    and abs(stations[j] - stations[i]) <= CONFIG.neighbour_max_dist
                )
                else None
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
            # quantities (выемка / щебень / геотекстиль / перемещение) by 3D length
            vols, l3d = ditch_volumes(ditch.top, ditch_end, killer)

            def _f(v: Any) -> str:
                return f"{v:+.2f}" if v is not None else " none"

            log(
                f"  #{count:>2} sta {sta:8.3f}: θ={ditch.theta_deg:4.0f}° "
                f"start_scarp={_f(ditch.scarp_start)} end_scarp={_f(ditch.scarp_end)} "
                f"Z {ditch.top[2]:.2f}->{ditch_end[2]:.2f} L2D={length_2d:.2f} "
                f"L3D={l3d:.2f} exc={vols['VolExcavation']:.2f} "
                f"stone={vols['VolStone']:.2f} geo={vols['VolGeotextile']:.2f} "
                f"move={vols['MoveTonnage']:.2f}"
                f"{'' if killer else ' (no apron)'}"
            )

            # main ditch: start (выемка) → ditch_end (connector top or бровка)
            pl = self._add_pl3d(ditch.top, ditch_end, self._ditch_layer, ms, tx)
            if psd_id is not None:
                tag_ditch(
                    pl,
                    psd_id,
                    tx,
                    canal=CANAL,
                    alignment=align_name,
                    index=count,
                    station=sta,
                    theta_deg=ditch.theta_deg,
                    slope=ditch.slope,
                    length_2d=length_2d,
                    z_start=ditch.top[2],
                    z_end=ditch_end[2],
                    status=ditch.status,
                    vol_excavation=vols["VolExcavation"],
                    vol_stone=vols["VolStone"],
                    vol_geotextile=vols["VolGeotextile"],
                    move_tonnage=vols["MoveTonnage"],
                )

            if killer is not None:
                # connector down the откос насыпи + horizontal гаситель apron.
                # Tag both with the ditch index so a volume refresh can relink
                # the connector to its ditch deterministically (not by geometry).
                # The connector is skipped when the ditch joins the apron directly
                # (has_connector False) — there the main ditch already ends at near.
                if killer.has_connector:
                    conn = self._add_pl3d(
                        killer.connector_top, killer.near, self._conn_layer, ms, tx
                    )
                    self._tag_index(conn, tx, align_name, count)
                    self._tag_part(
                        conn, tx, part_psd_id, align_name, count, "connector"
                    )
                kil = self._add_pl3d(
                    killer.near, killer.far, self._killer_layer, ms, tx
                )
                self._tag_index(kil, tx, align_name, count)
                self._tag_part(kil, tx, part_psd_id, align_name, count, "killer")

            # circle marking the ditch start (high / нагорная end)
            circ = Circle(
                Point3d(*ditch.top),
                Vector3d(0.0, 0.0, 1.0),
                CONFIG.start_marker_d / 2.0,
            )
            circ.Layer = self._ditch_layer
            ms.AppendEntity(circ)
            tx.AddNewlyCreatedDBObject(circ, True)

            lengths.append(length_2d)
            thetas.append(ditch.theta_deg)

        if lengths:
            log(
                f"ditch length (m): min={min(lengths):.2f} max={max(lengths):.2f} "
                f"avg={sum(lengths) / len(lengths):.2f}; "
                f"θ avg={sum(thetas) / len(thetas):.1f}° max={max(thetas):.0f}°; "
                f"{nb_flipped} nbr-flip, {out_of_band} out-of-band, "
                f"{no_bank} edge-end, {off_surface} skipped"
            )
        return count - len(existing)  # number of NEW ditches drawn this run

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

    def _tag_index(self, ent: Any, tx: Any, align_name: str, index: int) -> None:
        """Attach XData ARHYZ_MD = (alignment, ditch index) to a connector/apron line.

        The index lets a volume refresh relink the connector to its ditch by
        number instead of by fragile endpoint geometry. Alignment stays first so
        the existing purge (reads TypeCode 1000) is unaffected; _tag_entities
        skips this entity because it already carries XData for the app.
        """
        from Autodesk.AutoCAD.DatabaseServices import ResultBuffer, TypedValue

        ent.XData = ResultBuffer(
            TypedValue(1001, _REGAPP),
            TypedValue(1000, align_name),
            TypedValue(1070, int(index)),
        )

    def _tag_part(
        self,
        ent: Any,
        tx: Any,
        part_psd_id: Any,
        align_name: str,
        index: int,
        part_type: str,
    ) -> None:
        """Attach the Arhyz_CrossDitchPart identity PSD to a connector/killer.

        Build-time index; the refresh re-tags with the per-trasse index later. A
        failure here must not abort the ditch, so it is swallowed and logged.
        """
        if part_psd_id is None:
            return
        try:
            tag_part(
                ent,
                part_psd_id,
                tx,
                canal=CANAL,
                alignment=align_name,
                ditch_index=index,
                part_type=part_type,
            )
        except Exception as e:
            self._log(f"part PS tag failed (#{index} {part_type}): {e}", "WARN")

    def _ensure_regapp(self, db: Any, tx: Any) -> None:
        """Register ARHYZ_MD in RegAppTable so XData can be attached."""
        from Autodesk.AutoCAD.DatabaseServices import RegAppTable, RegAppTableRecord

        rat = tx.GetObject(db.RegAppTableId, OpenMode.ForRead)
        if not rat.Has(_REGAPP):
            rat.UpgradeOpen()
            ratr = RegAppTableRecord()
            ratr.Name = _REGAPP
            rat.Add(ratr)
            tx.AddNewlyCreatedDBObject(ratr, True)

    def _erase_markers(self, marker_oids: list[Any], tx: Any) -> int:
        """Erase the consumed marker circles; return how many were erased."""
        erased = 0
        for oid in marker_oids:
            try:
                tx.GetObject(oid, OpenMode.ForWrite).Erase()
                erased += 1
            except Exception:
                pass
        return erased

    def _existing_ditch_stations(
        self, ms: Any, tx: Any, align_name: str, psd_id: Any
    ) -> list[float]:
        """Return the stations of ditches already built for this alignment.

        Reads the Station property of every inf_md_ditch polyline tagged
        ARHYZ_MD=align_name. Used to skip markers that already have a ditch, so
        re-runs are additive and idempotent rather than rebuilding from scratch.
        The start-marker circles share the layer but carry no property set, so
        GetPropertySet throws on them and they are ignored.
        """
        import Autodesk.Aec.PropertyData.DatabaseServices as _PD

        stations: list[float] = []
        if psd_id is None:
            return stations
        for oid in ms:
            try:
                ent = tx.GetObject(oid, OpenMode.ForRead)
                if ent.Layer != self._ditch_layer:
                    continue
                rb = ent.GetXDataForApplication(_REGAPP)
                if rb is None:
                    continue
                name = next((str(tv.Value) for tv in rb if tv.TypeCode == 1000), None)
                if name != align_name:
                    continue
                ps_id = _PD.PropertyDataServices.GetPropertySet(ent, psd_id)
                ps = tx.GetObject(ps_id, OpenMode.ForRead)
                stations.append(float(ps.GetAt(ps.PropertyNameToId("Station"))))
            except Exception:
                continue
        return stations

    def _tag_entities(self, ms: Any, tx: Any, align_name: str) -> int:
        """Attach XData ARHYZ_MD=align_name to every untagged output entity.

        Only this run's output layers are tagged — the user's marker circles stay untagged
        and outside this script's purge scope.
        """
        from Autodesk.AutoCAD.DatabaseServices import ResultBuffer, TypedValue

        tagged = 0
        rb_new = ResultBuffer(
            TypedValue(1001, _REGAPP),
            TypedValue(1000, align_name),
        )
        for oid in ms:
            try:
                ent = tx.GetObject(oid, OpenMode.ForRead)
                if ent.Layer not in self._output_layers:
                    continue
                if ent.GetXDataForApplication(_REGAPP) is not None:
                    continue  # already tagged — belongs to another alignment
                ent.UpgradeOpen()
                ent.XData = rb_new
                tagged += 1
            except Exception:
                pass
        return tagged
