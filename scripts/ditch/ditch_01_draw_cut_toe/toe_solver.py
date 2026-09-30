from __future__ import annotations

from typing import Any, Optional

# The cut-toe point is the SAME break point ditch_core uses for
# ditch.top (подошва откоса выемки). Reuse break_point verbatim — never copy it.
from ditch_core.cross_profile import break_point


def _safe_elev(surface: Any, x: float, y: float) -> Optional[float]:
    try:
        return float(surface.FindElevationAtXY(x, y))
    except Exception:
        return None


def cut_toe_at(
    surface: Any,
    align_w: Any,
    sta: float,
    cfg: Any,
    eps: float,
) -> Optional[tuple[float, float, float]]:
    """Toe of the cut slope (подошва откоса выемки) at station `sta`, or None.

    Samples straight across the alignment normal (θ=0) on both sides. The first
    surface slope break on a side is its бровка; the side whose откос beyond that
    break CLIMBS (scarp_rise > eps) is a cut side (выемка), and that break point
    is the toe of its cut slope — exactly the point ditch_solver assigns to
    ditch.top. Returns the toe at surface elevation (x, y, z); NOT dropped by any
    depth — this marks the toe on the terrain, not a ditch floor.

    Returns None when the axis is off the surface or neither side is a cut (flat
    or fill on both sides — no откос выемки here, so the toe line breaks).
    """
    cx, cy = align_w.xy_at(sta)
    if _safe_elev(surface, cx, cy) is None:
        return None

    nx, ny = align_w.cross_axis_at(sta)
    s_step = cfg.sample_step
    reach = cfg.max_reach
    thr = cfg.slope_break
    steep = cfg.scarp_min_slope

    pa, _, rise_a = break_point(surface, cx, cy, nx, ny, s_step, reach, thr, steep)
    pb, _, rise_b = break_point(surface, cx, cy, -nx, -ny, s_step, reach, thr, steep)

    a_cut = pa is not None and rise_a is not None and rise_a > eps
    b_cut = pb is not None and rise_b is not None and rise_b > eps

    if a_cut and b_cut:
        # both banks rise — take the more pronounced выемка
        chosen = pa if rise_a >= rise_b else pb
    elif a_cut:
        chosen = pa
    elif b_cut:
        chosen = pb
    else:
        return None

    z = _safe_elev(surface, chosen[0], chosen[1])
    if z is None:
        return None
    return (chosen[0], chosen[1], z)
