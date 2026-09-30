from __future__ import annotations

import math
from typing import Optional


def first_slope_break(
    elevs: list[float], step: float, threshold: float
) -> Optional[int]:
    """Index of the first slope break walking outward from the axis.

    `elevs` are surface elevations sampled at t = 0, step, 2·step, … along one
    side of the cross-profile (index 0 is on the alignment axis). The slope of
    segment k is (elevs[k+1] − elevs[k]) / step; a break at node k is where that
    slope changes by more than `threshold` from the previous segment
    (|slope[k] − slope[k−1]| > threshold). Returns the node index k (so the
    break point is at distance k·step), or None if the profile never breaks.
    """
    n = len(elevs)
    if n < 3:
        return None
    prev_slope = (elevs[1] - elevs[0]) / step
    for k in range(1, n - 1):
        slope = (elevs[k + 1] - elevs[k]) / step
        if abs(slope - prev_slope) > threshold:
            return k
        prev_slope = slope
    return None


def outward_scarp(
    elevs: list[float], k: int, step: float, steep_slope: float
) -> Optional[float]:
    """Height climbed/dropped along the откос that starts at the бровка at k.

    The откос is a ~45° face right at the бровка, monotone (выемка climbs the
    whole way, насыпь drops). Walk outward while segments stay steep
    (|slope| ≥ steep_slope) AND keep the first segment's direction; sum the rise.
    Stop where it flattens (откос ends) or reverses (crest / тальвег) — so a
    short откос is never overshot onto the terrain beyond its crest. Returns the
    total rise over the run: > 0 climbs (откос выемки / cut), < 0 drops (откос
    насыпи / fill). None if the segment at the бровка is not a steep face.
    """
    n = len(elevs)
    if k + 1 >= n:
        return None
    first = elevs[k + 1] - elevs[k]
    if abs(first) < steep_slope * step:
        return None  # nothing steep at the бровка
    climbing = first > 0
    total = 0.0
    j = k
    while j + 1 < n:
        seg = elevs[j + 1] - elevs[j]
        if abs(seg) < steep_slope * step:  # flattened out — откос ended
            break
        if (seg > 0) != climbing:  # reversed — crest / тальвег
            break
        total += seg
        j += 1
    return total


def classify_start_side(
    rise_a: Optional[float],
    z_a: float,
    rise_b: Optional[float],
    z_b: float,
    eps: float = 0.3,
) -> str:
    """Decide which bank ('a' or 'b') is the ditch START (подошва откоса выемки).

    The start is the cut side — where the ground rises along the откос beyond the
    бровка (rise > eps metres); the end is the fill side (rise < −eps, откос
    насыпи). The откос sign wins over height: a single clear cut bank is the
    start even if it is LOWER than the other bank (подошва выемки can sit below
    the бровка насыпи — НК station 280). Only when the откос gives no answer
    (both cut, both fill, or both unknown) does height decide: higher = start.
    """
    a_cut = rise_a is not None and rise_a > eps
    a_fill = rise_a is not None and rise_a < -eps
    b_cut = rise_b is not None and rise_b > eps
    b_fill = rise_b is not None and rise_b < -eps

    # a single clear cut face (выемка) is the start, regardless of height
    if a_cut and not b_cut:
        return "a"
    if b_cut and not a_cut:
        return "b"
    # no single cut → a single clear fill face (насыпь) is the END
    if a_fill and not b_fill:
        return "b"
    if b_fill and not a_fill:
        return "a"
    # откос is no help (both cut / both fill / both unknown) → higher bank
    return "a" if z_a >= z_b else "b"


def consistent_neighbour_sign(neighbours: list[Optional[float]]) -> Optional[float]:
    """Return the common sign of the neighbours if they all agree, else None.

    `neighbours` are the start-side signs (+1/-1) of the ditches around the one
    under test (e.g. the 2 before and 2 after); None entries (missing / skipped
    ditches) are ignored. Returns the shared sign only when every present
    neighbour matches — otherwise there is no clear row direction to enforce.
    """
    vals = [s for s in neighbours if s is not None]
    if not vals:
        return None
    first = vals[0]
    return first if all(v == first for v in vals) else None


def line_intersect_s(
    s0: float, z0: float, g0: float, s1: float, z1: float, g1: float
) -> Optional[tuple[float, float]]:
    """Intersection of two lines in the (s, Z) profile plane.

    Line A passes through (s0, z0) with d Z/d s = g0; line B through (s1, z1)
    with slope g1. Returns (s, Z) of the crossing, or None if (near-)parallel.
    Used to meet the extended ditch (slope g0) with the connector along the
    откос насыпи (slope g1).
    """
    denom = g0 - g1
    if abs(denom) < 1e-9:
        return None
    s = (z1 - z0 + g0 * s0 - g1 * s1) / denom
    z = z0 + g0 * (s - s0)
    return s, z


def rotate(dx: float, dy: float, ang: float) -> tuple[float, float]:
    """Rotate vector (dx, dy) by ang radians (CCW). Returns the rotated vector."""
    c, s = math.cos(ang), math.sin(ang)
    return dx * c - dy * s, dx * s + dy * c


def pick_theta(
    candidates: list[tuple[float, float]],
    slope_min: float,
    slope_max: float,
) -> Optional[tuple[float, float]]:
    """Choose the skew angle from (theta, slope) candidates, ordered by ascending theta.

    Returns the first candidate whose slope is within [slope_min, slope_max]
    (the smallest skew that achieves the target longitudinal grade). If none
    lands in range, returns the candidate whose slope is closest to the band
    (so the caller can still draw something and flag it), or None if empty.
    """
    if not candidates:
        return None
    for theta, slope in candidates:
        if slope_min <= slope <= slope_max:
            return theta, slope

    def dist_to_band(slope: float) -> float:
        if slope < slope_min:
            return slope_min - slope
        if slope > slope_max:
            return slope - slope_max
        return 0.0

    return min(candidates, key=lambda c: dist_to_band(c[1]))
