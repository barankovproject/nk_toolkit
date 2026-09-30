from __future__ import annotations

import math
from typing import Any, NamedTuple, Optional

from .cross_profile import break_point
from .geometry import classify_start_side, pick_theta, rotate


class Ditch(NamedTuple):
    """A solved 3D cross-ditch: two end points (x, y, z) plus diagnostics."""

    top: tuple[float, float, float]  # high (нагорная) end, water source
    bot: tuple[float, float, float]  # low (низовая) end, water outlet
    theta_deg: float
    slope: float
    status: str  # "ok" | "out_of_band" | "no_bank"
    scarp_start: Optional[float]  # откос rise at the start end (+ = cut, выемка)
    scarp_end: Optional[float]  # откос rise at the end end (− = fill, насыпь)
    start_nside: float  # +1/-1: which side of the axis normal the start is on


def _safe_elev(surface: Any, x: float, y: float) -> Optional[float]:
    try:
        return float(surface.FindElevationAtXY(x, y))
    except Exception:
        return None


def solve_ditch(
    surface: Any,
    align_w: Any,
    sta: float,
    cfg: Any,
    force_start_nside: Optional[float] = None,
) -> Optional[Ditch]:
    """Solve one skewed 3D cross-ditch at station `sta`.

    Grows the skew angle θ from the alignment normal until the longitudinal
    grade between the two banks lands in [cfg.slope_min, cfg.slope_max]; both
    ends are dropped cfg.ditch_depth below the surface. The skew is searched in
    BOTH rotation senses: the primary sense swings the cut end up-station (which
    on steep stretches only steepens the grade), the opposite sense swings it
    down-station so the trasse's own fall cancels part of the cross-slope and the
    grade drops into the band. The opposite sense is tried whenever the primary
    one cannot reach the band, and kept when it lands closer to / inside it.
    θ is capped at cfg.theta_max_deg; when cfg.forbid_neighbour_overlap is True it
    is further bounded so the ditch's along-alignment extent stays within half a
    `step` on each side (neighbours must not overlap in plan).

    `force_start_nside` (+1/-1) overrides which side of the axis normal is the
    start, used by the neighbour-consistency pass to align an outlier ditch.

    Returns None only if the axis point itself is off the surface.
    """
    cx, cy = align_w.xy_at(sta)
    ang_ax = align_w.angle_at(sta)
    ax, ay = math.cos(ang_ax), math.sin(ang_ax)
    nx, ny = align_w.cross_axis_at(sta)  # unit normal (-sin, cos)

    if _safe_elev(surface, cx, cy) is None:
        return None

    # Which way does terrain fall ALONG the alignment? (sign of the skew). Use a
    # multi-metre arm so a local bump can't flip one ditch against its neighbours.
    gp = cfg.grade_probe
    e_fwd = _safe_elev(surface, *align_w.xy_at(sta + gp))
    e_back = _safe_elev(surface, *align_w.xy_at(sta - gp))
    descend_along = 1.0
    if e_fwd is not None and e_back is not None:
        descend_along = 1.0 if e_fwd < e_back else -1.0

    s_step = cfg.sample_step
    reach = cfg.max_reach
    thr = cfg.slope_break
    half_step = cfg.step / 2.0
    steep = cfg.scarp_min_slope
    up_n, down_n = (nx, ny), (-nx, -ny)

    # Find the cut (выемка) side straight across (θ=0), then aim the skew so the
    # cut bank — the start — swings UPHILL along the falling trasse and the fill
    # bank downhill. That guarantees ZStart > ZEnd, i.e. water drains start→end
    # (а not the other way round, which produced end-above-start ditches).
    pa0, _, sl_a0 = break_point(surface, cx, cy, nx, ny, s_step, reach, thr, steep)
    pb0, _, sl_b0 = break_point(surface, cx, cy, -nx, -ny, s_step, reach, thr, steep)
    za0 = _safe_elev(surface, pa0[0], pa0[1]) if pa0 is not None else 0.0
    zb0 = _safe_elev(surface, pb0[0], pb0[1]) if pb0 is not None else 0.0
    cut_side = classify_start_side(sl_a0, za0 or 0.0, sl_b0, zb0 or 0.0)
    # force_start_nside (neighbour pass) overrides which side is the start: pick
    # the θ=0 bank that sits on the requested normal side.
    if force_start_nside is not None:

        def _nside0(p: Any) -> float:
            return 1.0 if (p[0] - cx) * nx + (p[1] - cy) * ny >= 0.0 else -1.0

        if pa0 is not None and _nside0(pa0) == force_start_nside:
            cut_side = "a"
        elif pb0 is not None and _nside0(pb0) == force_start_nside:
            cut_side = "b"
    cut_dir = up_n if cut_side == "a" else down_n
    perp_cut = (-cut_dir[1], cut_dir[0])
    pc_dot = perp_cut[0] * ax + perp_cut[1] * ay
    # +θ moves the cut end by sgn·perp_cut along the axis; pick sgn so that goes
    # against the descent (uphill) → cut end higher.
    sgn = -descend_along if pc_dot > 0 else descend_along

    # Grow θ in one rotation direction, keeping only skews that DRAIN correctly:
    # the выемка (cut = start) bank higher than the насыпь (fill = end) bank.
    # cut_side fixes WHICH bank is the start (semantics); the skew must then put
    # that bank on top. Picking by |slope| alone (old behaviour) also accepted
    # skews where the cut end came out LOWER — a ditch running uphill, with the
    # гаситель on the high side.
    def _search(
        sign: float,
    ) -> tuple[list[tuple[float, float]], dict[float, Any]]:
        cands: list[tuple[float, float]] = []
        dat: dict[float, tuple[Any, Any, float, float, Any, Any, str]] = {}
        t = 0.0
        while t <= cfg.theta_max_deg + 1e-9:
            ang = sign * math.radians(t)
            ur = rotate(up_n[0], up_n[1], ang)
            dr = rotate(down_n[0], down_n[1], ang)
            pa_, sa_, sl_a_ = break_point(
                surface, cx, cy, ur[0], ur[1], s_step, reach, thr, steep
            )
            pb_, sb_, sl_b_ = break_point(
                surface, cx, cy, dr[0], dr[1], s_step, reach, thr, steep
            )
            if pa_ is not None and pb_ is not None:
                # overlap guard: along-axis extent within half a step on each side
                # (disabled when cfg.forbid_neighbour_overlap is False, e.g. when
                # `step` is large enough that neighbours can never overlap).
                if cfg.forbid_neighbour_overlap:
                    proj_a = (pa_[0] - cx) * ax + (pa_[1] - cy) * ay
                    proj_b = (pb_[0] - cx) * ax + (pb_[1] - cy) * ay
                    if max(abs(proj_a), abs(proj_b)) > half_step:
                        break
                za_ = _safe_elev(surface, pa_[0], pa_[1])
                zb_ = _safe_elev(surface, pb_[0], pb_[1])
                if za_ is not None and zb_ is not None:
                    length = math.hypot(pb_[0] - pa_[0], pb_[1] - pa_[1])
                    if length > 1e-6:
                        z_cut = za_ if cut_side == "a" else zb_
                        z_fill = zb_ if cut_side == "a" else za_
                        if z_cut > z_fill:  # drains start(выемка) → end(насыпь)
                            cands.append((t, (z_cut - z_fill) / length))
                            bank_ok = sa_ == "break" and sb_ == "break"
                            dat[t] = (
                                pa_,
                                pb_,
                                za_,
                                zb_,
                                sl_a_,
                                sl_b_,
                                "ok" if bank_ok else "no_bank",
                            )
            t += cfg.theta_step_deg
        return cands, dat

    def _band_dist(slope: float) -> float:
        if slope < cfg.slope_min:
            return cfg.slope_min - slope
        if slope > cfg.slope_max:
            return slope - cfg.slope_max
        return 0.0

    candidates, data = _search(sgn)
    pick = pick_theta(candidates, cfg.slope_min, cfg.slope_max)
    # The aimed sense swings the cut end up-station ("against descent"), which on
    # steep stretches only grows the grade out of band. The opposite sense tilts
    # the cut end down-station, letting the trasse's own fall cancel part of the
    # cross-slope so the grade drops INTO the band — the gentle skew a user draws
    # by hand. Try it when the aimed sense has no candidate or misses the band, and
    # switch only if it lands closer to / inside the band. Ditches the aimed sense
    # already solves in band are left exactly as before (no opposite search).
    if pick is None or _band_dist(pick[1]) > 0.0:
        candidates_opp, data_opp = _search(-sgn)
        pick_opp = pick_theta(candidates_opp, cfg.slope_min, cfg.slope_max)
        if pick_opp is not None and (
            pick is None or _band_dist(pick_opp[1]) < _band_dist(pick[1])
        ):
            candidates, data, pick = candidates_opp, data_opp, pick_opp
    if pick is None:
        return None
    th_sel, slope_sel = pick
    pa, pb, za, zb, sl_a, sl_b, bank_status = data[th_sel]

    in_band = cfg.slope_min <= slope_sel <= cfg.slope_max
    status = bank_status if in_band else "out_of_band"

    # Start = подошва откоса выемки. Use the SAME cut_side the skew was aimed at
    # (decided once at θ=0), not a fresh classify here. The _search above only kept
    # skews with z_cut > z_fill, so the cut side (start) is guaranteed higher than
    # the fill side (end) ⇒ ZStart > ZEnd, гаситель on the low end.
    depth = cfg.ditch_depth
    end_a = (pa[0], pa[1], za - depth)
    end_b = (pb[0], pb[1], zb - depth)

    def nside(p: Any) -> float:
        return 1.0 if (p[0] - cx) * nx + (p[1] - cy) * ny >= 0.0 else -1.0

    if cut_side == "a":
        top, bot = end_a, end_b
        scarp_start, scarp_end = sl_a, sl_b
    else:
        top, bot = end_b, end_a
        scarp_start, scarp_end = sl_b, sl_a

    return Ditch(
        top=top,
        bot=bot,
        theta_deg=th_sel,
        slope=slope_sel,
        status=status,
        scarp_start=scarp_start,
        scarp_end=scarp_end,
        start_nside=nside(top),
    )
