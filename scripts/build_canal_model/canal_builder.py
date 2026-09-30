from __future__ import annotations

import json
import math
import os
import traceback
from typing import Any, Optional

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import LoftOptions, OpenMode
from Autodesk.Civil.ApplicationServices import CivilApplication
from Autodesk.Civil.DatabaseServices import Profile

from civil import AlignmentWrapper, ProfileWrapper

from .acad_helpers import (
    civil_transaction,
    ensure_ps_defs,
    gabion_layer,
    purge_canal_solids,
    tag_rib,
)
from .config import (
    DATA_DIR,
    GABION,
    SHARP_PI,
    find_best_match,
    load_canal_config,
    load_gsi_baskets,
    load_trough_table,
    load_types_table,
    pk_to_sta,
)
from .context import BuildContext
from .export import build_canal_export
from .gabion_builder import GabionBuilder
from .geometry import arc_pt_dir, compute_virtual_arc
from .logger import Logger
from .rib_builder import RibBuilder
from .section_params import pi_reach_at, section_params_at
from .trough_builder import TroughBuilder


class CanalBuilder:
    """Top-level orchestrator: loads config, opens Civil3D transaction, runs all builders, saves JSON."""

    def __init__(self, query: str, log_keep: int = 10) -> None:
        self.query = query.strip()
        self.log = Logger(keep=log_keep)

    def run(self) -> int | list[str]:
        """Execute the full canal model build. Returns solid count or list of error strings."""
        log = self.log
        log("=== SCRIPT STARTED ===")
        log(f"query='{self.query}'")

        errors: list[str] = []
        added = 0

        try:
            canal_cfg = load_canal_config(self.query)
            segments: list[dict[str, Any]] = canal_cfg["segments"]
            widening: Optional[dict[str, Any]] = canal_cfg.get("widening")
            log(f"segments: {len(segments)}, widening: {widening}")

            cfg_types: dict[str, Any]
            cfg_types, types_path = load_types_table(canal_cfg)
            log(f"type table: {types_path}")
            trough_cfg_types: dict[str, Any] = load_trough_table(canal_cfg)
            if not trough_cfg_types:
                log("trough types: none (non-default type_table)")
            gsi_baskets: dict[str, str] = load_gsi_baskets()

            self._validate_segments(segments, cfg_types, trough_cfg_types, types_path)

            doc = Application.DocumentManager.MdiActiveDocument
            db = doc.Database
            civil_db = CivilApplication.ActiveDocument

            with civil_transaction(doc, db) as tx:
                align, align_name = self._find_alignment(tx, civil_db)
                profile, profile_name = self._find_profile(tx, align, align_name)
                log(f"alignment: '{align_name}'  profile: '{profile_name}'")

                sta_start = float(align.StartingStation)
                sta_end = float(align.EndingStation)
                log(f"stations: {sta_start:.3f} - {sta_end:.3f}")

                align_w = AlignmentWrapper(align, sta_end)
                profile_w = ProfileWrapper(profile, sta_end)

                bx, by = align_w.xy_at(sta_start)
                bz = profile_w.elevation_at(sta_start)
                log(f"base: X={bx:.3f} Y={by:.3f} Z={bz:.3f}")

                plan_pi_stas = align_w.plan_pis(sta_start, log)
                log(
                    f"plan PIs ({len(plan_pi_stas)}): {[f'{s:.2f}' for s in plan_pi_stas]}"
                )

                sharp_pi_stas = self._find_sharp_pis(
                    plan_pi_stas,
                    align_w,
                    profile_w,
                    segments,
                    cfg_types,
                    trough_cfg_types,
                    sta_end,
                    widening,
                )
                arc_infos: dict[float, dict[str, Any]] = {}
                virtual_arc_overrides: dict[
                    float, tuple[float, float, float, float]
                ] = {}
                if sharp_pi_stas:
                    log(
                        f"sharp PIs ({len(sharp_pi_stas)}): "
                        f"{[f'{s:.3f}' for s in sharp_pi_stas]} — virtual arc enabled"
                    )
                    for pi in sharp_pi_stas:
                        bw, d, m_s, t = section_params_at(
                            pi, segments, cfg_types, sta_end, widening
                        )
                        top_w = bw + 2.0 * (m_s * d + t * math.sqrt(1.0 + m_s * m_s))
                        if top_w <= 1e-6:
                            log(
                                f"  PI {pi:.3f}: zero canal width, skip virtual arc",
                                "WARN",
                            )
                            continue
                        R = top_w * SHARP_PI.arc_radius_factor
                        arc_info = compute_virtual_arc(pi, R, align_w)
                        arc_infos[pi] = arc_info

                        phi_deg = abs(math.degrees(arc_info["phi"]))
                        # Pick N so the OUTER edge arc length per slice is ≤ GABION.loft_step
                        # (outer edge is the longest physical edge of a fan slice;
                        # angular-only sizing under-samples when R or φ is large).
                        outer_R = R + top_w / 2.0
                        outer_step_max = GABION.loft_step
                        N_outer = int(
                            math.ceil(outer_R * abs(arc_info["phi"]) / outer_step_max)
                        )
                        N_angle = int(math.ceil(phi_deg / SHARP_PI.arc_deg_per_step))
                        N = max(SHARP_PI.arc_min_steps, N_outer, N_angle)
                        if N % 2 == 1:
                            N += 1  # force even so the PI midpoint is exactly sampled
                        arc_info["N"] = N
                        outer_step = outer_R * abs(arc_info["phi"]) / N
                        log(
                            f"  PI {pi:.3f}: φ={phi_deg:.2f}° top_w={top_w:.3f}m "
                            f"R={R:.3f}m L={arc_info['L']:.3f}m "
                            f"PC={arc_info['pc_sta']:.3f} PT={arc_info['pt_sta']:.3f} "
                            f"N={N} steps (outer_edge_step={outer_step:.3f}m)"
                        )
                        for i in range(N + 1):
                            t_frac = i / N
                            sub_sta = arc_info["pc_sta"] + t_frac * (
                                arc_info["pt_sta"] - arc_info["pc_sta"]
                            )
                            x, y, ax, ay = arc_pt_dir(arc_info, sub_sta)
                            virtual_arc_overrides[round(sub_sta, 4)] = (x, y, ax, ay)

                pvi_stas = profile_w.pvi_stations(sta_start, errors)
                log(f"PVIs ({len(pvi_stas)}): {[f'{s:.2f}' for s in pvi_stas]}")
                for pvi in profile_w.pvi_data(sta_start):
                    gin = pvi.get("grade_in")
                    gout = pvi.get("grade_out")
                    if gin is not None and gout is not None:
                        delta = gout - gin
                        flag = " ***" if abs(delta) > 0.1 else ""
                        log(
                            f"  PVI {pvi['station']:.3f}: {gin:.4f} → {gout:.4f} Δ={delta:+.4f}{flag}"
                        )

                stations, callout_breakpoints = self._build_stations(
                    sta_start,
                    sta_end,
                    pvi_stas,
                    plan_pi_stas,
                    segments,
                    cfg_types,
                    widening,
                    sharp_pi_stas,
                    arc_infos,
                )
                log(f"section count: {len(stations)}")

                ms = tx.GetObject(db.CurrentSpaceId, OpenMode.ForWrite)

                gabion_psd_id, trough_psd_id, _, rib_psd_id = ensure_ps_defs(db, tx)
                purge_canal_solids(
                    align_name, gabion_psd_id, trough_psd_id, rib_psd_id, ms, tx, log
                )

                opts = LoftOptions()
                ctx = BuildContext(align_w, profile_w, ms, tx, opts, log, sta_end)

                trough_piece_stats: dict[str, dict[str, int]] = {}
                rib_counts_map: dict[str, int] = {}

                gb = GabionBuilder(
                    ctx,
                    cfg_types,
                    trough_cfg_types,
                    segments,
                    widening,
                    bx,
                    by,
                    bz,
                    virtual_arc_overrides=virtual_arc_overrides,
                    canal_name=align_name,
                    gsi_baskets=gsi_baskets,
                )
                n, errs = gb.build(stations, plan_pi_stas)
                added += n
                errors.extend(errs)

                rb = RibBuilder(
                    ctx,
                    canal_name=align_name,
                    psd_rib=rib_psd_id,
                    gsi_baskets=gsi_baskets,
                )
                for seg in segments:
                    if not seg.get("ribs"):
                        continue
                    tp_key = str(seg["type"])
                    if tp_key in trough_cfg_types:
                        continue
                    seg_s = pk_to_sta(seg["from"])
                    seg_e = min(pk_to_sta(seg["to"]), sta_end)
                    if widening is not None:
                        rib_clip = sta_end - float(widening["length"])
                        if seg_e > rib_clip + 0.01:
                            seg_e = rib_clip
                    if seg_e <= seg_s + 0.01:
                        log(
                            f"segment ribs [{seg['from']}]: fully inside widening, skipped"
                        )
                        continue
                    seg_bw = float(cfg_types[tp_key]["bottom_w"])
                    n = rb.place(
                        seg_s,
                        seg_e,
                        seg_bw,
                        seg["from"],
                        gabion_layer(tp_key),
                        split=False,
                    )
                    added += n
                    rib_counts_map[seg["to"]] = n
                    log(f"segment ribs [{seg['from']}-{seg['to']}]: {n} ribs")

                if widening is not None and widening.get("ribs"):
                    w_b = float(widening["b"])
                    w_len = float(widening["length"])
                    flat_start = sta_end - w_len + GABION.widening_trans
                    n = rb.place(
                        flat_start,
                        sta_end,
                        w_b,
                        "widening",
                        gabion_layer(gb.last_gabion_key),
                        stagger=True,
                    )
                    added += n
                    rib_counts_map["__widening__"] = n
                    log(f"widening ribs: {n} (staggered)")
                errors.extend(rb.errors)

                tb = TroughBuilder(ctx, canal_name=align_name)
                for seg in segments:
                    tp_key = str(seg["type"])
                    if tp_key not in trough_cfg_types:
                        continue
                    tp = trough_cfg_types[tp_key]
                    seg_s = pk_to_sta(seg["from"])
                    seg_e = pk_to_sta(seg["to"])
                    if widening is not None:
                        trough_clip = sta_end - float(widening["length"])
                        if seg_e > trough_clip + 0.01:
                            seg_e = trough_clip
                    if seg_e <= seg_s + 0.01:
                        log(f"trough [{seg['from']}]: fully inside widening, skipped")
                        continue
                    n, pstats = tb.build_segment(
                        tp, tp_key, seg_s, seg_e, plan_pi_stas, pvi_stas
                    )
                    added += n
                    trough_piece_stats[seg["to"]] = pstats
                    log(f"trough [{seg['from']}-{seg_e:.2f}]: {n} solids, {pstats}")
                errors.extend(tb.errors)

                log(f"solids added: {added}")

                canal_data = build_canal_export(
                    align_name,
                    sta_start,
                    sta_end,
                    align_w,
                    profile_w,
                    segments,
                    pvi_stas,
                    plan_pi_stas,
                    trough_piece_stats,
                    rib_counts_map,
                    cfg_types,
                    trough_cfg_types,
                    widening,
                    bx,
                    by,
                    bz,
                    stations=stations,
                    callout_breakpoints=callout_breakpoints,
                )

            os.makedirs(DATA_DIR, exist_ok=True)
            out_path = os.path.join(DATA_DIR, f"{align_name}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(canal_data, f, ensure_ascii=False, indent=2)
            log(f"canal data saved: {out_path}")

        except Exception as ex:
            errors.insert(0, f"ERROR: {ex}")
            log(f"ERROR: {ex}", "CRITICAL")
            log(traceback.format_exc(), "CRITICAL")

        log(f"=== SCRIPT DONE: added={added}, errors={len(errors)} ===")
        if errors:
            self.log.mark_errors(len(errors))
        return added if not errors else errors

    def _validate_segments(
        self,
        segments: list[dict[str, Any]],
        cfg_types: dict[str, Any],
        trough_cfg_types: dict[str, Any],
        types_path: str,
    ) -> None:
        """Raise if any gabion segment type is missing from config or has zero dimensions."""
        for seg in segments:
            tp_key = str(seg["type"])
            if tp_key in trough_cfg_types:
                continue
            if tp_key not in cfg_types:
                raise Exception(f"Segment type {tp_key} not in {types_path}")
            tp = cfg_types[tp_key]
            if float(tp["d"]) <= 0 or float(tp["bottom_w"]) <= 0 or float(tp["t"]) <= 0:
                raise Exception(f"Canal type {tp_key} has zeros in {types_path}")

    def _find_alignment(self, tx: Any, civil_db: Any) -> tuple[Any, str]:
        """Return (Alignment, matched_name) by fuzzy-matching self.query against all alignments."""
        align_objects = []
        for oid in civil_db.GetAlignmentIds():
            try:
                align_objects.append(tx.GetObject(oid, OpenMode.ForRead))
            except Exception:
                continue
        names = [a.Name for a in align_objects]
        result = find_best_match(self.query, names)
        if result is None:
            raise Exception(f"No alignment matching '{self.query}'. Available: {names}")
        return align_objects[result[0]], result[1]

    def _find_profile(self, tx: Any, align: Any, align_name: str) -> tuple[Any, str]:
        """Return (Profile, matched_name); searches by align_name first, then query, then 'компоновка'."""
        profile_objects = []
        for pid in align.GetProfileIds():
            try:
                p = tx.GetObject(pid, OpenMode.ForRead)
                if isinstance(p, Profile):
                    profile_objects.append(p)
            except Exception:
                continue
        names = [p.Name for p in profile_objects]
        result = find_best_match(align_name, names)
        if result is None:
            result = find_best_match(self.query, names)
        if result is None:
            design_idx = next(
                (i for i, n in enumerate(names) if "компоновка" in n.lower()), None
            )
            if design_idx is not None:
                result = (design_idx, names[design_idx])
                self.log(f"profile: no name match, using '{result[1]}'", "WARN")
        if result is None:
            _SURFACE_KEYWORDS = ("поверхность", "земля", "коридор")
            design = [
                i
                for i, n in enumerate(names)
                if not any(kw in n.lower() for kw in _SURFACE_KEYWORDS)
            ]
            if len(design) == 1:
                result = (design[0], names[design[0]])
                self.log(
                    f"profile: fuzzy match failed, using sole design profile '{result[1]}'",
                    "WARN",
                )
        if result is None:
            raise Exception(f"No profile matching '{align_name}'. Profiles: {names}")
        return profile_objects[result[0]], result[1]

    def _find_sharp_pis(
        self,
        plan_pi_stas: list[float],
        align_w: Any,
        profile_w: Any,
        segments: list[dict[str, Any]],
        cfg_types: dict[str, Any],
        trough_cfg_types: dict[str, Any],
        sta_end: float,
        widening: Optional[dict[str, Any]],
    ) -> list[float]:
        """Return plan PIs on gabion segments that need the virtual arc fan.

        Two triggers:
          1. deflection ≥ SHARP_PI.deg on a wide segment (types 7/8) — the
             bisector cut visually smears on the inner corner (legacy rule);
          2. the bisector corner-piece window is empty: no piece length both
             avoids self-intersection (≥ reach + margin) and keeps the worst
             longitudinal 3D edge ≤ loft_step (piece·mag + reach + safety ≤
             loft_step). reach = miter pullback + top-wall lean
             (НК-1А-3: type 6 @ 39.24° → pullback 1.23 m, window empty).
        """
        sharp: list[float] = []
        for pi in plan_pi_stas:
            seg_type = None
            for seg in segments:
                if pk_to_sta(seg["from"]) - 0.01 <= pi <= pk_to_sta(seg["to"]) + 0.01:
                    seg_type = str(seg["type"])
                    break
            if seg_type is None or seg_type in trough_cfg_types:
                continue  # trough PIs are handled by the trough mono pieces
            deflection_deg = math.degrees(align_w.deflection_at(pi))
            if seg_type in SHARP_PI.wide_types and deflection_deg >= SHARP_PI.deg:
                sharp.append(pi)
                continue
            reach = pi_reach_at(
                pi,
                [pi],
                align_w,
                profile_w.slope_at,
                segments,
                cfg_types,
                sta_end,
                widening,
            )
            s_in = profile_w.slope_at(pi - 0.3)
            s_out = profile_w.slope_at(pi + 0.3)
            mag = math.sqrt(1.0 + max(s_in * s_in, s_out * s_out))
            lo = reach + GABION.miter_margin
            hi = (GABION.loft_step - GABION.edge_safety - reach) / mag
            if hi < lo:
                self.log(
                    f"PI {pi:.3f}: deflection {deflection_deg:.2f}° — bisector corner "
                    f"piece window empty (reach {reach:.3f}, edge cap "
                    f"{GABION.loft_step} m) -> virtual arc"
                )
                sharp.append(pi)
        return sharp

    def _build_stations(
        self,
        sta_start: float,
        sta_end: float,
        pvi_stas: list[float],
        plan_pi_stas: list[float],
        segments: list[dict[str, Any]],
        cfg_types: dict[str, Any],
        widening: Optional[dict[str, Any]],
        sharp_pi_stas: Optional[list[float]] = None,
        arc_infos: Optional[dict[float, dict[str, Any]]] = None,
    ) -> tuple[list[float], list[float]]:
        """Build (loft stations, callout breakpoints).

        Returns the sorted, deduplicated loft station list and the subset of those
        stations that should carry a coordinate callout (изломы) — i.e. all stations
        except the dense interior fan-slice anchors of a sharp-PI virtual arc.

        For each sharp PI in arc_infos, inserts N+1 fan-slice anchor stations between
        the virtual PC and PT (replacing the bisector cut with a smooth radial arc).
        Also pushes widening trans_start past PT when it lands inside the arc zone.
        """
        if sharp_pi_stas is None:
            sharp_pi_stas = []
        if arc_infos is None:
            arc_infos = {}

        # PVIs within pi_merge_tol of a plan PI are absorbed by the PI (НК-1E-2:
        # PVI 547.678 vs PI 547.787 left a 0.109 m sliver gabion — just over the
        # SNAP_TOL merge, and the tail-merge can't help a 2-station span). The PI
        # must win so the bisector miter survives; the profile kink moves by
        # ≤ tol·|Δslope| — millimetres. Mirrors the trough_builder convention.
        pvi_kept = [
            s
            for s in pvi_stas
            if all(abs(s - p) > GABION.pi_merge_tol for p in plan_pi_stas)
        ]
        dropped = sorted(
            s
            for s in set(pvi_stas) - set(pvi_kept)
            if min(abs(s - p) for p in plan_pi_stas) > 1e-6  # exact dups are silent
        )
        if dropped:
            self.log(
                f"PVIs absorbed by plan PI (<= {GABION.pi_merge_tol} m): "
                f"{[f'{s:.3f}' for s in dropped]}",
                "WARN",
            )
        stations: list[float] = (
            [sta_start, sta_end] + list(pvi_kept) + list(plan_pi_stas)
        )

        for seg in segments:
            for pk in (seg["from"], seg["to"]):
                extra = pk_to_sta(pk)
                if sta_start < extra < sta_end:
                    stations.append(extra)

        half_gt = GABION.trans_len / 2.0
        for i in range(len(segments) - 1):
            seg_a, seg_b = segments[i], segments[i + 1]
            key_a, key_b = str(seg_a["type"]), str(seg_b["type"])
            if key_a == key_b or key_a not in cfg_types or key_b not in cfg_types:
                continue
            boundary = pk_to_sta(seg_a["to"])
            for extra in (boundary - half_gt, boundary + half_gt):
                if sta_start < extra < sta_end:
                    stations.append(extra)

        # Sharp-PI virtual-arc anchors: N+1 fan-slice stations between PC and PT
        # (N is computed in run() and stored on arc_info to stay consistent
        # with virtual_arc_overrides). Interior anchors (i=1..N-1) are collected so
        # callout placement can drop them — only PC/PT of an arc carry a callout.
        arc_interior: list[float] = []
        for pi, arc_info in arc_infos.items():
            pc_sta = arc_info["pc_sta"]
            pt_sta = arc_info["pt_sta"]
            N = arc_info["N"]
            for i in range(N + 1):
                t_frac = i / N
                extra = pc_sta + t_frac * (pt_sta - pc_sta)
                if sta_start < extra < sta_end:
                    stations.append(extra)
                    if 0 < i < N:
                        arc_interior.append(extra)

        if widening is not None:
            w_len = float(widening["length"])
            trans_start = sta_end - w_len
            # If trans_start lands inside a sharp-PI arc zone, push it to PT so the
            # widening transition doesn't overlap the fan. Mutates widening["length"]
            # so downstream consumers (section_params_at, rib placement) see the
            # shortened widening zone.
            for pi, arc_info in arc_infos.items():
                pc_sta = arc_info["pc_sta"]
                pt_sta = arc_info["pt_sta"]
                if pc_sta - 0.05 <= trans_start <= pt_sta + 0.05:
                    new_trans_start = pt_sta
                    if new_trans_start < sta_end - 0.05:
                        new_w_len = sta_end - new_trans_start
                        self.log(
                            f"widening trans_start {trans_start:.3f} inside arc zone of "
                            f"sharp PI {pi:.3f} → pushed to PT {new_trans_start:.3f} "
                            f"(length {w_len:.3f}→{new_w_len:.3f})",
                            "WARN",
                        )
                        widening["length"] = new_w_len
                        trans_start = new_trans_start
                    break
            flat_start = trans_start + GABION.widening_trans
            snap_ref = set(stations) | set(plan_pi_stas)
            for extra in (trans_start, flat_start):
                if sta_start < extra < sta_end:
                    if any(abs(extra - s) < 0.05 for s in snap_ref):
                        self.log(
                            f"widening sta {extra:.3f} skipped (within 0.05m of existing)",
                            "WARN",
                        )
                    else:
                        stations.append(extra)

        # Snap near-coincident stations together (>0.001 left tiny sliver solids,
        # e.g. a segment "to" PK 80.510 vs the alignment end 80.513 lofted a ~3 mm
        # gabion at the widening end). Merge anything within SNAP_TOL, then pin the
        # endpoints exactly to sta_start/sta_end so the canal still spans the full
        # alignment.
        SNAP_TOL = 0.1
        stations.sort()
        unique = [stations[0]]
        for sta in stations[1:]:
            if sta - unique[-1] > SNAP_TOL:
                unique.append(sta)
        if abs(unique[0] - sta_start) <= SNAP_TOL:
            unique[0] = sta_start
        if abs(unique[-1] - sta_end) <= SNAP_TOL:
            unique[-1] = sta_end
        if len(unique) < len(stations):
            self.log(
                f"stations merged (<= {SNAP_TOL} m): {len(stations)} -> {len(unique)}",
                "WARN",
            )
        callout_breakpoints = [
            s for s in unique if not any(abs(s - a) < 0.002 for a in arc_interior)
        ]
        return unique, callout_breakpoints
