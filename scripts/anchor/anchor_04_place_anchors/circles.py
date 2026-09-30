"""Anchor circle placement: same-colour crossings, row fill, overlap merge.

Circles sit where a horizontal meets a perpendicular OF THE SAME COLOUR (blue x
blue, red x red) -> staggered pattern. Then, per horizontal, any gap between
neighbouring circles wider than the grid step gets midway circles so no gap
exceeds the step. Finally, circles whose centres fall within one diameter are
merged into a single circle midway between them (no overlap).
"""

from __future__ import annotations

import math
from typing import Any

_EPS = 1e-9


def _seg_seg(
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    p4: tuple[float, float],
) -> tuple[float, float] | None:
    """Intersection point of segments p1-p2 and p3-p4, or None."""
    rx, ry = p2[0] - p1[0], p2[1] - p1[1]
    sx, sy = p4[0] - p3[0], p4[1] - p3[1]
    rxs = rx * sy - ry * sx
    if abs(rxs) < _EPS:
        return None
    qpx, qpy = p3[0] - p1[0], p3[1] - p1[1]
    t = (qpx * sy - qpy * sx) / rxs
    u = (qpx * ry - qpy * rx) / rxs
    if -_EPS <= t <= 1 + _EPS and -_EPS <= u <= 1 + _EPS:
        return (p1[0] + rx * t, p1[1] + ry * t)
    return None


def polyline_hits(
    poly: list[tuple[float, float]], a: tuple[float, float], b: tuple[float, float]
) -> list[tuple[float, tuple[float, float]]]:
    """Return [(arc_length_along_poly, point)] where segment a-b crosses poly."""
    hits: list[tuple[float, tuple[float, float]]] = []
    cum = 0.0
    for i in range(len(poly) - 1):
        h0, h1 = poly[i], poly[i + 1]
        pt = _seg_seg(h0, h1, a, b)
        if pt is not None:
            hits.append((cum + math.dist(h0, pt), pt))
        cum += math.dist(h0, h1)
    return hits


def point_at_arc(poly: list[tuple[float, float]], s: float) -> tuple[float, float]:
    """Point at arc-length ``s`` along the polyline."""
    cum = 0.0
    for i in range(len(poly) - 1):
        seglen = math.dist(poly[i], poly[i + 1])
        if cum + seglen >= s or i == len(poly) - 2:
            t = 0.0 if seglen < _EPS else max(0.0, min(1.0, (s - cum) / seglen))
            a, b = poly[i], poly[i + 1]
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        cum += seglen
    return poly[-1]


def distribute_row(
    hits: list[tuple[float, tuple[float, float]]],
    poly: list[tuple[float, float]],
    spacing: float,
    max_gap: float,
    center_below: float,
    max_shift: float,
) -> list[tuple[float, float]]:
    """Even out one row: fill big gaps, then relax — but bounded by ``max_shift``.

    ``hits`` are (arc_position, point) along the same horizontal; distances are
    straight-line between circles.

    1. Fill — a gap gets ``max(round(d/spacing), ceil(d/max_gap)) - 1`` circles
       inserted evenly, so sub-gaps stay ~``spacing`` and never exceed ``max_gap``.
    2. Relax — an anchor whose nearer neighbour is closer than ``center_below``
       and whose two gaps are uneven is pulled toward the midpoint, but never
       more than ``max_shift`` from its original grid position (no drift).
    """
    s = sorted(h[0] for h in hits)

    def pt(a):
        return point_at_arc(poly, a)

    out: list[float] = [s[0]]
    for i in range(len(s) - 1):
        s0, s1 = s[i], s[i + 1]
        d = math.dist(pt(s0), pt(s1))
        k = max(int(d / spacing + 0.5), math.ceil(d / max_gap - _EPS), 1)
        out.extend(s0 + (s1 - s0) * j / k for j in range(1, k))
        out.append(s1)

    base = list(out)  # original arc positions, for the shift clamp
    for _ in range(6):
        moved = False
        for i in range(1, len(out) - 1):
            g_l = math.dist(pt(out[i - 1]), pt(out[i]))
            g_r = math.dist(pt(out[i]), pt(out[i + 1]))
            if min(g_l, g_r) < center_below and abs(g_l - g_r) > 0.3:
                target = (out[i - 1] + out[i + 1]) / 2.0
                clamped = max(base[i] - max_shift, min(base[i] + max_shift, target))
                new_l = math.dist(pt(out[i - 1]), pt(clamped))
                new_r = math.dist(pt(clamped), pt(out[i + 1]))
                # Only accept a move that does not shrink the anchor's min gap
                # (prevents two neighbours being pulled together into a tight pair).
                if abs(clamped - out[i]) > 1e-6 and min(new_l, new_r) + 1e-6 >= min(
                    g_l, g_r
                ):
                    out[i] = clamped
                    moved = True
        if not moved:
            break

    return [pt(a) for a in out]


def merge_overlaps(
    circles: list[tuple[float, float, int, float]], min_dist: float
) -> list[tuple[float, float, int, float]]:
    """Merge any two circles closer than ``min_dist`` into their midpoint.

    Each circle is (x, y, color, elevation). On merge the colour of the first is
    kept and the elevation averaged; repeats until no pair is too close.
    """
    pts = list(circles)
    changed = True
    while changed:
        changed = False
        for i in range(len(pts)):
            for j in range(i + 1, len(pts)):
                if math.dist(pts[i][:2], pts[j][:2]) < min_dist - _EPS:
                    mx = (pts[i][0] + pts[j][0]) / 2
                    my = (pts[i][1] + pts[j][1]) / 2
                    me = (pts[i][3] + pts[j][3]) / 2
                    merged = (mx, my, pts[i][2], me)
                    pts = [p for k, p in enumerate(pts) if k not in (i, j)]
                    pts.append(merged)
                    changed = True
                    break
            if changed:
                break
    return pts


def in_territory(
    q: tuple[float, float],
    seg: int,
    axis: list[tuple[float, float]],
    dnorms: dict[int, tuple[float, float]],
) -> bool:
    """True if Q is inside segment ``seg``'s territory (between its dividers).

    The start divider sits at axis vertex ``seg`` and the end divider at
    ``seg+1``; end segments have no divider on their outer side. ``dnorms`` maps
    an interior vertex index to the divider's forward (axis-direction) normal.
    """
    m = dnorms.get(seg)
    if m is not None:
        if (q[0] - axis[seg][0]) * m[0] + (q[1] - axis[seg][1]) * m[1] < -1e-6:
            return False
    m = dnorms.get(seg + 1)
    if m is not None:
        if (q[0] - axis[seg + 1][0]) * m[0] + (q[1] - axis[seg + 1][1]) * m[1] > 1e-6:
            return False
    return True


def place_anchors(
    horizontals: list[tuple[list[tuple[float, float]], int, float]],
    grid_lines: list[dict],
    axis: list[tuple[float, float]],
    dnorms: dict[int, tuple[float, float]],
    spacing: float,
    max_gap: float,
    center_below: float,
    max_shift: float,
    min_dist: float,
) -> list[tuple[float, float, int, float]]:
    """Full pipeline -> list of (x, y, color, elevation) circle centres.

    A crossing counts only when it falls inside its line's segment territory, so
    the seam-overlap lines of a neighbour do not place anchors here.
    """
    circles: list[tuple[float, float, int, float]] = []
    for poly, h_color, elev in horizontals:
        hits: list[tuple[float, tuple[float, float]]] = []
        for ln in grid_lines:
            if ln["color"] != h_color:
                continue
            for s, pt in polyline_hits(poly, ln["a"], ln["b"]):
                if in_territory(pt, ln["seg"], axis, dnorms):
                    hits.append((s, pt))
        if not hits:
            continue
        for x, y in distribute_row(
            hits, poly, spacing, max_gap, center_below, max_shift
        ):
            circles.append((x, y, h_color, elev))
    return merge_overlaps(circles, min_dist)
