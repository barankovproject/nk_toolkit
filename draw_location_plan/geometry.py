from __future__ import annotations

import math
from typing import Any


def get_xy(align: Any, sta: float) -> tuple[float, float]:
    ac = align.GetPointAtDist(sta)
    return float(ac.X), float(ac.Y)


def get_xy_angle(align: Any, sta: float, sta_end: float, delta: float = 0.01) -> float:
    s0 = max(float(align.StartingStation), sta - delta)
    s1 = min(sta_end, sta + delta)
    p0 = align.GetPointAtDist(s0)
    p1 = align.GetPointAtDist(s1)
    return math.atan2(float(p1.Y) - float(p0.Y), float(p1.X) - float(p0.X))


def outline_pts_at_sta(
    align: Any,
    sta: float,
    sta_end: float,
    bw: float,
    d: float,
    m: float,
    t: float,
) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
    """Return (center, left_outer, right_outer) XY for the canal plan outline at sta.

    half_outer = bw/2 + m*d + t — plan-view half-width to the outer gabion wall edge.
    Right perpendicular vector: rx = -sin(ang), ry = cos(ang).
    Left outer uses -rx, -ry; right outer uses +rx, +ry.
    """
    x, y = get_xy(align, sta)
    ang = get_xy_angle(align, sta, sta_end)
    rx, ry = -math.sin(ang), math.cos(ang)
    half_outer = bw / 2.0 + m * d + t
    return (
        (x, y),
        (x - rx * half_outer, y - ry * half_outer),
        (x + rx * half_outer, y + ry * half_outer),
    )


def tick_pts(
    align: Any, sta: float, sta_end: float, half_len: float
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Return (p1, p2) endpoints of a station tick perpendicular to the alignment."""
    x, y = get_xy(align, sta)
    ang = get_xy_angle(align, sta, sta_end)
    rx, ry = -math.sin(ang), math.cos(ang)
    return (x - rx * half_len, y - ry * half_len), (
        x + rx * half_len,
        y + ry * half_len,
    )


def sta_to_label(sta: float) -> str:
    pk = int(sta // 100)
    m = sta % 100
    return f"{pk}+{m:05.2f}"
