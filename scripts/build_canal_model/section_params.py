from __future__ import annotations

import math
from typing import Any, Callable, Iterable, Optional

from .config import GABION, pk_to_sta


def section_params_at(
    sta: float,
    segments: list[dict[str, Any]],
    cfg_types: dict[str, Any],
    sta_end: float,
    widening: Optional[dict[str, Any]],
) -> tuple[float, float, float, float]:
    """Return (bottom_w, d, m, t) at station sta, interpolating across type transitions and widening."""
    last_gabion_key = next(
        (
            str(seg["type"])
            for seg in reversed(segments)
            if str(seg["type"]) in cfg_types
        ),
        str(segments[0]["type"]),
    )

    if widening is not None:
        w_b = float(widening["b"])
        w_len = float(widening["length"])
        trans_start = sta_end - w_len
        flat_start = trans_start + GABION.widening_trans
        if sta >= trans_start:
            last_gab_tp = cfg_types[last_gabion_key]
            d = float(last_gab_tp["d"])
            m_s = float(last_gab_tp["m"])
            t = float(last_gab_tp["t"])
            last_bw = float(last_gab_tp["bottom_w"])
            bw = (
                w_b
                if sta >= flat_start
                else last_bw
                + (sta - trans_start) / GABION.widening_trans * (w_b - last_bw)
            )
            return bw, d, m_s, t

    half = GABION.trans_len / 2.0
    for i in range(len(segments) - 1):
        seg_a, seg_b = segments[i], segments[i + 1]
        key_a, key_b = str(seg_a["type"]), str(seg_b["type"])
        if key_a == key_b or key_a not in cfg_types or key_b not in cfg_types:
            continue
        boundary = pk_to_sta(seg_a["to"])
        if boundary - half <= sta <= boundary + half:
            ratio = (sta - (boundary - half)) / GABION.trans_len
            tp_a, tp_b = cfg_types[key_a], cfg_types[key_b]

            def lerp(a: Any, b: Any, r: float = ratio) -> float:
                return float(a) + (float(b) - float(a)) * r

            return (
                lerp(tp_a["bottom_w"], tp_b["bottom_w"]),
                lerp(tp_a["d"], tp_b["d"]),
                lerp(tp_a["m"], tp_b["m"]),
                lerp(tp_a["t"], tp_b["t"]),
            )

    tp_key = last_gabion_key
    for seg in segments:
        if pk_to_sta(seg["from"]) <= sta <= pk_to_sta(seg["to"]) + 0.001:
            candidate = str(seg["type"])
            if candidate in cfg_types:
                tp_key = candidate
                break
    tp = cfg_types[tp_key]
    return float(tp["bottom_w"]), float(tp["d"]), float(tp["m"]), float(tp["t"])


def miter_pullback(
    pi_sta: float,
    align_w: Any,
    segments: list[dict[str, Any]],
    cfg_types: dict[str, Any],
    sta_end: float,
    widening: Optional[dict[str, Any]],
) -> float:
    """Return the bisector-miter pullback (m) at a plan PI.

    At a PI the cross-section rotates to the bisector, so its outermost lateral
    point retreats along the tangent by half_top_w * tan(deflection/2). A
    PI-adjacent loft span shorter than this makes the inner-side profile points
    move backwards → self-intersecting loft → degenerate solid (НК-3А-1).
    """
    defl = align_w.deflection_at(pi_sta)
    bw, d, m_s, t = section_params_at(pi_sta, segments, cfg_types, sta_end, widening)
    top_w = bw + 2.0 * (m_s * d + t * math.sqrt(1.0 + m_s * m_s))
    return 0.5 * top_w * math.tan(defl / 2.0)


def miter_lean(
    pi_sta: float,
    slope_at: Callable[[float], float],
    segments: list[dict[str, Any]],
    cfg_types: dict[str, Any],
    sta_end: float,
    widening: Optional[dict[str, Any]],
    eps: float = 0.3,
) -> float:
    """Top-wall lean kink (m) at a profile grade break coinciding with a PI.

    Cross-sections are perpendicular to the 3D flow (geometry.section_pts):
    points at height vz lean longitudinally by −(slope/mag)·vz. When the slope
    changes across the station, the top points (vz = +d) of the shared section
    advance by d·|Δ(slope/mag)| relative to the neighbouring section
    (НК-3А-1 PI 250.307 = PVI Δslope 0.445: +0.29 m on the P4/P5 edges).
    """
    s_in = slope_at(pi_sta - eps)
    s_out = slope_at(pi_sta + eps)
    u_in = s_in / math.sqrt(1.0 + s_in * s_in)
    u_out = s_out / math.sqrt(1.0 + s_out * s_out)
    _, d, _, _ = section_params_at(pi_sta, segments, cfg_types, sta_end, widening)
    return d * abs(u_in - u_out)


def pi_reach_at(
    sta: float,
    plan_pi_stas: Iterable[float],
    align_w: Any,
    slope_at: Callable[[float], float],
    segments: list[dict[str, Any]],
    cfg_types: dict[str, Any],
    sta_end: float,
    widening: Optional[dict[str, Any]],
) -> float:
    """Worst longitudinal advance of the bisector section at a plan PI, else 0.0.

    reach = miter_pullback (plan rotation of the outermost lateral point)
          + miter_lean (top-wall kink when a grade break sits on the PI).
    """
    pi = next((p for p in plan_pi_stas if abs(sta - p) < 0.01), None)
    if pi is None:
        return 0.0
    return miter_pullback(
        pi, align_w, segments, cfg_types, sta_end, widening
    ) + miter_lean(pi, slope_at, segments, cfg_types, sta_end, widening)


def corner_piece_len(reach: float, mag: float) -> float:
    """Length (plan metres) of the gabion piece adjacent to a bisector-miter PI.

    The worst longitudinal 3D edge of that piece is ≈ piece·mag + reach, so the
    cap piece ≤ (loft_step − edge_safety − reach)/mag keeps every edge under
    loft_step (НК-1А-3: a full 2 m step next to a 39° type-6 PI had a 3.21 m
    edge). The floor reach + miter_margin keeps the loft from self-intersecting
    (НК-3А-1 degenerate wedge). When the window is empty the floor wins — but
    such PIs are routed to the virtual arc fan by canal_builder.
    """
    lo = reach + GABION.miter_margin
    hi = (GABION.loft_step - GABION.edge_safety - reach) / mag
    return max(lo, hi)


def loft_substations(
    s0: float,
    s1: float,
    slope_at: Callable[[float], float],
    reach_head: float = 0.0,
    reach_tail: float = 0.0,
) -> list[float]:
    """Split loft span s0→s1 into sub-stations with GABION.loft_step along-slope spacing.

    A trailing remainder shorter than GABION.min_unit merges with the previous
    step and splits evenly (доборные ГСИ: 6.4 m → 2, 2, 1.2, 1.2).

    When the span starts/ends at a bisector-miter plan PI, pass its reach
    (pi_reach_at): a corner piece of corner_piece_len() is reserved at that
    end so it neither self-intersects (≥ reach + margin) nor grows a
    longitudinal 3D edge beyond loft_step (≤ (loft_step − safety − reach)/mag,
    with mag refined at the piece midpoint — slope often changes right at
    the PI when a grade break sits on it).
    """

    def mag(sta: float) -> float:
        slope = slope_at(sta)
        return math.sqrt(1.0 + slope * slope)

    def split_even(a: float, b: float, low: float) -> list[float]:
        """Interior stations splitting a..b evenly into the most loft_step-like
        piece count whose pieces still clear `low` (доборные: 2.4 m → 1.2 + 1.2)."""
        chunk = b - a
        k = max(1, int(math.ceil(chunk / GABION.loft_step - 1e-9)))
        while k > 1 and chunk / k < low - 1e-9:
            k -= 1
        return [a + chunk * j / k for j in range(1, k)]

    # reserve PI corner pieces; the regular split covers the remaining [a, b]
    a, b = s0, s1
    has_head_piece = False
    has_tail_piece = False
    if reach_head > 0.0:
        piece = corner_piece_len(reach_head, mag(s0))
        piece = corner_piece_len(reach_head, mag(s0 + piece / 2.0))  # refine inside
        if (b - a) - piece >= GABION.min_unit - 1e-9:
            a = s0 + piece
            has_head_piece = True
    if reach_tail > 0.0:
        piece = corner_piece_len(reach_tail, mag(s1))
        piece = corner_piece_len(reach_tail, mag(s1 - piece / 2.0))  # refine inside
        if (b - a) - piece >= GABION.min_unit - 1e-9:
            b = s1 - piece
            has_tail_piece = True

    sub: list[float] = []
    s = a
    while s < b - 1e-6:
        sub.append(s)
        s += GABION.loft_step / mag(s)
    sub.append(b)

    merged_tail = False
    while len(sub) >= 3 and sub[-1] - sub[-2] < GABION.min_unit - 1e-9:
        sub.pop(-2)
        merged_tail = True
    if merged_tail:
        sub = sub[:-1] + split_even(sub[-2], sub[-1], GABION.min_unit) + [sub[-1]]

    return ([s0] if has_head_piece else []) + sub + ([s1] if has_tail_piece else [])


def type_key_at(sta: float, segs: list[dict[str, Any]]) -> str:
    """Return the segment type key string that covers station sta."""
    for seg in segs:
        if pk_to_sta(seg["from"]) <= sta <= pk_to_sta(seg["to"]) + 0.001:
            return str(seg["type"])
    return str(segs[-1]["type"])
