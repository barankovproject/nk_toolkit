"""Canal model JSON export."""

from __future__ import annotations

import datetime
import math
from typing import TYPE_CHECKING, Any, Optional

from .config import GABION, RIBS, pk_to_sta
from .geometry import section_pts
from .section_params import loft_substations, pi_reach_at, section_params_at

if TYPE_CHECKING:
    from civil.alignment import AlignmentWrapper
    from civil.profile import ProfileWrapper


def _rib_records(
    profile_w: ProfileWrapper,
    segments: list[dict[str, Any]],
    widening: Optional[dict[str, Any]],
    cfg_types: dict[str, Any],
    trough_cfg_types: dict[str, Any],
    sta_end: float,
) -> list[dict[str, Any]]:
    """Return rib records with station and lateral segment list, mirroring RibBuilder.place().

    Each record: {"station": float, "laterals": [[lat_a, lat_b], ...]}
    Lateral values are signed offsets from canal centre (metres), matching the cross_axis.
    """

    def _slope_mag(sta: float) -> float:
        sl = profile_w.slope_at(sta)
        return math.sqrt(1.0 + sl * sl)

    def _step_regular(
        zone_start: float, zone_end: float, half_w: float
    ) -> list[dict[str, Any]]:
        recs: list[dict[str, Any]] = []
        rib_sta = zone_end - RIBS.size / 2.0
        while rib_sta >= zone_start - 1e-6:
            recs.append({"station": rib_sta, "laterals": [[-half_w, half_w]]})
            rib_sta -= RIBS.step / _slope_mag(rib_sta)
        return recs

    def _lateral_positions(n: int, rib_len: float) -> list[list[float]]:
        total_span = n * rib_len + max(0, n - 1) * RIBS.gap
        start = -total_span / 2.0
        pitch = rib_len + RIBS.gap
        return [[start + i * pitch, start + i * pitch + rib_len] for i in range(n)]

    def _step_stagger(
        zone_start: float, zone_end: float, bottom_w: float
    ) -> list[dict[str, Any]]:
        n_a = max(2, int((bottom_w + RIBS.gap) / (RIBS.max_len + RIBS.gap)))
        rib_len = max(
            RIBS.min_len, min(RIBS.max_len, (bottom_w - (n_a - 1) * RIBS.gap) / n_a)
        )
        pos_a = _lateral_positions(n_a, rib_len)
        pos_b = _lateral_positions(n_a - 1, rib_len)
        recs: list[dict[str, Any]] = []
        rib_sta = zone_end - RIBS.size / 2.0
        is_a = True
        while rib_sta >= zone_start - 1e-6:
            recs.append({"station": rib_sta, "laterals": pos_a if is_a else pos_b})
            rib_sta -= RIBS.step / _slope_mag(rib_sta)
            is_a = not is_a
        return recs

    result: list[dict[str, Any]] = []

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
            continue
        half_w = float(cfg_types[tp_key]["bottom_w"]) / 2.0
        result.extend(_step_regular(seg_s, seg_e, half_w))

    if widening is not None and widening.get("ribs"):
        w_len = float(widening["length"])
        flat_start = sta_end - w_len + GABION.widening_trans
        result.extend(_step_stagger(flat_start, sta_end, float(widening["b"])))

    return sorted(result, key=lambda r: r["station"])


def build_canal_export(
    align_name: str,
    sta_start: float,
    sta_end: float,
    align_w: AlignmentWrapper,
    profile_w: ProfileWrapper,
    segments: list[dict[str, Any]],
    pvi_stas: list[float],
    plan_pi_stas: list[float],
    trough_piece_stats: dict[str, dict[str, int]],
    rib_counts_map: dict[str, int],
    cfg_types: dict[str, Any],
    trough_cfg_types: dict[str, Any],
    widening: Optional[dict[str, Any]],
    bx: float,
    by: float,
    bz: float,
    stations: Optional[list[float]] = None,
    callout_breakpoints: Optional[list[float]] = None,
) -> dict[str, Any]:
    """Build canal data dict for JSON export (segment records, PI angles, section points).

    `callout_breakpoints` is the subset of `stations` that should carry a coordinate
    callout (изломы): breakpoints minus the dense interior fan-slice anchors of a
    sharp-PI virtual arc. The exported `callout_stations` = these breakpoints plus the
    dobornie (tail-merged) boundaries, and is consumed by draw_gabion_view.
    """

    def section_at(sta: float) -> list[Any]:
        x, y = align_w.xy_at(sta)
        ang = align_w.angle_at(sta)
        ax_v, ay_v = math.cos(ang), math.sin(ang)
        rx_v, ry_v = align_w.cross_axis_at(sta)
        elev = profile_w.elevation_at(sta) - bz
        slope = profile_w.slope_at(sta)
        bw, d, m_s, t = section_params_at(sta, segments, cfg_types, sta_end, widening)
        return section_pts(
            x - bx,
            y - by,
            elev,
            rx_v,
            ry_v,
            ax_v,
            ay_v,
            slope,
            bx,
            by,
            bz,
            bw,
            d,
            m_s,
            t,
        )

    # expand key stations to all loft sub-stations (same step logic as gabion_builder)
    key_stas: list[float] = (
        stations
        if stations
        else sorted(set([sta_start, sta_end] + list(pvi_stas) + list(plan_pi_stas)))
    )
    # breakpoints that carry a callout (изломы): all key stations unless an explicit
    # subset is given (which drops the dense interior sharp-PI arc anchors). Stations
    # excluded from that subset are arc anchors → arc_set, used to suppress dobornie
    # callouts inside an arc fan (those units are sub-standard by design).
    bp_set: set[str] = {
        f"{s:.3f}"
        for s in (callout_breakpoints if callout_breakpoints is not None else key_stas)
    }
    arc_set: set[str] = {f"{s:.3f}" for s in key_stas} - bp_set

    def reach_at(sta: float) -> float:
        # sharp-PI fan anchors are perpendicular slices, not bisector miters
        if f"{sta:.3f}" in arc_set:
            return 0.0
        return pi_reach_at(
            sta,
            plan_pi_stas,
            align_w,
            profile_w.slope_at,
            segments,
            cfg_types,
            sta_end,
            widening,
        )

    callout_stas: set[float] = set()
    all_stas: list[float] = []
    for i in range(len(key_stas) - 1):
        seg0, seg1 = key_stas[i], key_stas[i + 1]
        in_arc = f"{seg0:.3f}" in arc_set or f"{seg1:.3f}" in arc_set
        if f"{seg0:.3f}" in bp_set:
            callout_stas.add(round(seg0, 3))  # излом
        # same sub-splitting as gabion_builder (incl. PI corner-piece reservation)
        sub = loft_substations(
            seg0,
            seg1,
            profile_w.slope_at,
            reach_head=reach_at(seg0),
            reach_tail=reach_at(seg1),
        )
        # dobornie = any gabion unit whose along-slope length != standard (loft_step).
        # Full while-loop steps are exactly loft_step; only merged halves and the
        # trailing remainder are sub-standard, so flag their start boundary.
        # Suppressed inside arc fans.
        if not in_arc:
            for j in range(1, len(sub) - 1):
                full_h = GABION.loft_step / math.sqrt(
                    1.0 + profile_w.slope_at(sub[j]) ** 2
                )
                if abs((sub[j + 1] - sub[j]) - full_h) > 0.05:
                    callout_stas.add(round(sub[j], 3))
        all_stas.extend(sub[:-1])
    all_stas.append(key_stas[-1])
    if f"{key_stas[-1]:.3f}" in bp_set:
        callout_stas.add(round(key_stas[-1], 3))

    rib_recs = _rib_records(
        profile_w, segments, widening, cfg_types, trough_cfg_types, sta_end
    )
    # rib stations are NOT added to all_stas — their XY is interpolated in draw_location_plan

    seen: set[str] = set()
    unique_stas: list[float] = []
    for sta in all_stas:
        k = f"{sta:.3f}"
        if k not in seen:
            seen.add(k)
            unique_stas.append(sta)

    section_pts_map = {
        f"{sta:.3f}": [
            [round(p.X, 4), round(p.Y, 4), round(p.Z, 4)] for p in section_at(sta)
        ]
        for sta in unique_stas
    }

    seg_records: list[dict[str, Any]] = []
    for seg in segments:
        tp_key = str(seg["type"])
        seg_s_r = pk_to_sta(seg["from"])
        seg_e_r = pk_to_sta(seg["to"])
        kind = "trough" if tp_key in trough_cfg_types else "gabion"
        rec: dict[str, Any] = {
            "type": tp_key,
            "kind": kind,
            "station_start": round(seg_s_r, 3),
            "station_end": round(seg_e_r, 3),
            "length": round(seg_e_r - seg_s_r, 3),
        }
        if kind == "trough":
            ps = trough_piece_stats.get(seg["to"], {"std": 0, "cut": 0, "mono": 0})
            rec.update(
                {
                    "troughs_std": ps["std"],
                    "troughs_cut": ps["cut"],
                    "troughs_mono": ps["mono"],
                }
            )
        if seg.get("ribs"):
            rec["ribs"] = rib_counts_map.get(seg["to"], 0)
        seg_records.append(rec)

    pi_records: list[dict[str, Any]] = [
        {
            "station": round(pi_sta, 3),
            "angle_deg": round(math.degrees(align_w.deflection_at(pi_sta)), 2),
        }
        for pi_sta in plan_pi_stas
    ]

    return {
        "alignment": align_name,
        "computed_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "total_length": round(sta_end - sta_start, 3),
        "segments": seg_records,
        "plan_pis": pi_records,
        "pvi_stations": [round(s, 3) for s in pvi_stas],
        "widening_ribs": rib_counts_map.get("__widening__", 0),
        "rib_stations": [
            {"station": round(r["station"], 3), "laterals": r["laterals"]}
            for r in rib_recs
        ],
        "callout_stations": sorted(callout_stas),
        "section_points": section_pts_map,
    }
