from __future__ import annotations

from typing import Any, Optional

from .geometry import first_slope_break, outward_scarp


def _sample_elevations(
    surface: Any,
    cx: float,
    cy: float,
    dx: float,
    dy: float,
    step: float,
    max_reach: float,
) -> list[float]:
    """Surface elevations along (cx,cy)+t·(dx,dy) for t = 0, step, … ≤ max_reach.

    Stops early when the ray leaves the surface (FindElevationAtXY throws),
    so the last element is the last on-surface sample on that side.
    """
    elevs: list[float] = []
    t = 0.0
    while t <= max_reach + 1e-9:
        try:
            e = surface.FindElevationAtXY(cx + dx * t, cy + dy * t)
        except Exception:
            break  # off the surface — edge reached
        elevs.append(float(e))
        t += step
    return elevs


def break_point(
    surface: Any,
    cx: float,
    cy: float,
    dx: float,
    dy: float,
    step: float,
    max_reach: float,
    threshold: float,
    steep_slope: float = 0.3,
) -> tuple[Optional[tuple[float, float]], str, Optional[float]]:
    """Find the first surface slope-break (бровка) from the axis along (dx,dy).

    The ray is sampled well past the бровка (up to max_reach); the break point
    truncates the ditch, but the samples beyond it are kept to read the откос.

    Returns (point, status, scarp_rise):
      status — "break" (a real slope break), "edge" (no break before the surface
               edge; point is the last on-surface sample, or None if the axis is
               itself off-surface), or "cap" (no break up to max_reach).
      scarp_rise — height climbed/dropped along the откос that starts at the
               бровка (metres): > 0 the face climbs (откос выемки / cut), < 0 it
               drops (откос насыпи / fill). None unless a break was found.
    """
    elevs = _sample_elevations(surface, cx, cy, dx, dy, step, max_reach)
    if not elevs:
        return None, "edge", None  # axis is off the surface

    k = first_slope_break(elevs, step, threshold)
    if k is not None:
        t = k * step
        rise = outward_scarp(elevs, k, step, steep_slope)
        return (cx + dx * t, cy + dy * t), "break", rise

    # no break: either we ran into the surface edge or hit the reach cap
    last_t = (len(elevs) - 1) * step
    if last_t < max_reach - 1e-9:
        return (cx + dx * last_t, cy + dy * last_t), "edge", None
    return (cx + dx * max_reach, cy + dy * max_reach), "cap", None
