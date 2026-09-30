from __future__ import annotations

import math
from typing import Any, NamedTuple, Optional

from .geometry import line_intersect_s


class Killer(NamedTuple):
    """Stilling-apron construction at the foot of the откос насыпи.

    connector_top — where the (extended) ditch meets the connector = new ditch
                    end. The main ditch is drawn start → connector_top. When
                    has_connector is False the main ditch connects straight to the
                    apron and connector_top == near (no separate connector drawn).
    near, far     — the two ends of the horizontal гаситель apron (near = the
                    trasse-side end where the connector / ditch lands).
    has_connector — True when a connector segment (connector_top → near) runs down
                    the откос; False when the ditch joins the apron directly.
    """

    connector_top: tuple[float, float, float]
    near: tuple[float, float, float]
    far: tuple[float, float, float]
    has_connector: bool = True


def _surface_foot(
    surface: Any,
    cx: float,
    cy: float,
    dx: float,
    dy: float,
    step: float,
    max_reach: float,
) -> Optional[tuple[float, float]]:
    """Surface edge (подошва) walking from the axis along (dx,dy).

    Steps out by `step` to the last on-surface sample, then bisects between it
    and the first off-surface point so the edge — and the apron that sits on it —
    lands on the true подошва, not up to one `step` short of it. Returns
    (distance_from_axis, surface_elevation), or None if the axis is off-surface.
    """

    def elev(s: float) -> Optional[float]:
        try:
            return float(surface.FindElevationAtXY(cx + dx * s, cy + dy * s))
        except Exception:
            return None

    last: Optional[tuple[float, float]] = None
    s = 0.0
    while s <= max_reach + 1e-9:
        z = elev(s)
        if z is None:
            break
        last = (s, z)
        s += step
    if last is None:
        return None

    lo_s, lo_z = last
    hi_s = lo_s + step
    if hi_s > max_reach:  # ran into the reach cap, not a real edge — don't refine
        return last
    for _ in range(24):  # bisect to the surface edge (~µm)
        mid = 0.5 * (lo_s + hi_s)
        z = elev(mid)
        if z is None:
            hi_s = mid
        else:
            lo_s, lo_z = mid, z
    return (lo_s, lo_z)


def build_killer(
    surface: Any,
    cx: float,
    cy: float,
    top: tuple[float, float, float],
    bot: tuple[float, float, float],
    depth: float,
    cfg: Any,
) -> Optional[Killer]:
    """Build the гаситель apron + connector at the foot of the откос насыпи.

    Geometry is solved in the (s, Z) profile along the ditch line, s measured
    from the axis toward the fill (низовой) end:
      - подошва = surface edge on the fill side (s_foot, z_foot); apron sits at
        z_foot − depth, horizontal, centred on s_foot (± cfg.killer_half);
      - connector runs from the trasse-side apron end up the откос (its slope =
        бровка→подошва) and meets the extended ditch line (through top & bot) at
        connector_top — the new ditch end.
    When the fill side has no real откос (подошва sits right at the бровка, e.g.
    1e #11 where the surface edge coincides with the бровка), g_scarp is
    ill-defined and the connector intersection runs far away; the connector is
    then dropped and the main ditch joins the apron directly (has_connector False),
    provided the straight ditch→apron run still drains at ≤ slope_max.
    Returns None when the fill side has no откос beyond the бровка (e.g. the axis
    is off-surface, or подошва ≤ бровка), so the caller keeps the plain ditch.
    """
    fdx, fdy = bot[0] - cx, bot[1] - cy
    d = math.hypot(fdx, fdy)
    if d < 1e-6:
        return None
    fdx, fdy = fdx / d, fdy / d

    foot = _surface_foot(surface, cx, cy, fdx, fdy, cfg.sample_step, cfg.max_reach)
    if foot is None:
        return None
    s_foot, z_foot = foot  # подошва: on the SURFACE (apron is not buried)

    # бровка насыпи distance + its SURFACE elevation (bot is buried by depth)
    s_br = (bot[0] - cx) * fdx + (bot[1] - cy) * fdy
    z_br_surf = bot[2] + depth
    if s_foot - s_br < 1e-6:
        return None  # подошва not beyond the бровка — no откос to lay on

    g_scarp = (z_foot - z_br_surf) / (s_foot - s_br)  # откос slope, dZ/ds (negative)

    half = cfg.killer_half
    s_near = s_foot - half

    def pt(s: float, z: float) -> tuple[float, float, float]:
        return (cx + fdx * s, cy + fdy * s, z)

    near = pt(s_near, z_foot)
    far = pt(s_foot + half, z_foot)

    # ditch line (buried, extended) through top & bot in the same profile
    s_top = (top[0] - cx) * fdx + (top[1] - cy) * fdy
    z_top = top[2]
    if abs(s_br - s_top) < 1e-6:
        return None
    g_ditch = (bot[2] - z_top) / (s_br - s_top)

    # connector through the trasse-side apron end (on the surface) up the откос
    inter = line_intersect_s(s_top, z_top, g_ditch, s_near, z_foot, g_scarp)
    if inter is not None:
        s_int, z_int = inter
        # The connector must land on the откос — between the ditch start (s_top)
        # and the подошва (s_foot). On a real откос it does; on a degenerate fill
        # side g_scarp is ill-defined and the intersection runs far away, so reject
        # it and connect the ditch straight to the apron instead.
        if s_top <= s_int <= s_foot:
            return Killer(pt(s_int, z_int), near, far, has_connector=True)

    # No usable connector: join the main ditch directly to the apron (no posrednik),
    # but only when that straight run still drains at an acceptable grade.
    ds2d = math.hypot(near[0] - top[0], near[1] - top[1])
    direct_slope = (top[2] - z_foot) / ds2d if ds2d > 1e-6 else 0.0
    if 0.0 < direct_slope <= cfg.slope_max:
        return Killer(near, near, far, has_connector=False)
    return None
