"""Median axis from the anchor horizontals: orient, resample, average, re-space.

Pipeline (see anchor_02 builder):
  1. group horizontals by elevation (one line per elevation; longest run wins)
  2. orient them consistently along the SW->NE diagonal so point j of every line
     corresponds across elevations (neighbouring contours run opposite ways)
  3. resample each line to M equal arc-length points
  4. average pointwise across elevations -> central spline
  5. re-space into equal segments, each >= the minimum segment length
"""

from __future__ import annotations

import math
from typing import Any

from Autodesk.AutoCAD.DatabaseServices import OpenMode, Polyline

M_RESAMPLE = 200  # dense sampling before averaging


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_contours_by_elevation(
    tx: Any, db: Any, layer: str
) -> dict[float, list[list[tuple[float, float]]]]:
    """Return {elevation: [run_xy, ...]} for every LWPolyline on ``layer``."""
    groups: dict[float, list[list[tuple[float, float]]]] = {}
    ms = tx.GetObject(db.CurrentSpaceId, OpenMode.ForRead)
    for oid in ms:
        ent = tx.GetObject(oid, OpenMode.ForRead)
        if not isinstance(ent, Polyline) or ent.Layer != layer:
            continue
        elev = round(float(ent.Elevation), 3)
        xy = [
            (ent.GetPoint2dAt(i).X, ent.GetPoint2dAt(i).Y)
            for i in range(int(ent.NumberOfVertices))
        ]
        groups.setdefault(elev, []).append(xy)
    return groups


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def _length(pts: list[tuple[float, float]]) -> float:
    return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def longest_run(runs: list[list[tuple[float, float]]]) -> list[tuple[float, float]]:
    return max(runs, key=_length)


def _orient(
    lines: list[list[tuple[float, float]]],
) -> list[list[tuple[float, float]]]:
    """Flip lines so they all run along the same global diagonal direction."""
    all_pts = [p for ln in lines for p in ln]
    xs = [p[0] for p in all_pts]
    ys = [p[1] for p in all_pts]
    ox, oy = min(xs), min(ys)
    ax, ay = max(xs) - ox, max(ys) - oy
    out: list[list[tuple[float, float]]] = []
    for ln in lines:
        s0 = (ln[0][0] - ox) * ax + (ln[0][1] - oy) * ay
        s1 = (ln[-1][0] - ox) * ax + (ln[-1][1] - oy) * ay
        out.append(list(reversed(ln)) if s0 > s1 else list(ln))
    return out


def resample(pts: list[tuple[float, float]], n: int) -> list[tuple[float, float]]:
    """Resample a polyline to ``n`` points spaced equally by arc length."""
    if n < 2 or len(pts) < 2:
        return list(pts)
    cum = [0.0]
    for i in range(len(pts) - 1):
        cum.append(cum[-1] + math.dist(pts[i], pts[i + 1]))
    total = cum[-1]
    if total == 0:
        return [pts[0]] * n
    out: list[tuple[float, float]] = []
    seg = 0
    for k in range(n):
        target = total * k / (n - 1)
        while seg < len(pts) - 2 and cum[seg + 1] < target:
            seg += 1
        span = cum[seg + 1] - cum[seg]
        t = 0.0 if span == 0 else (target - cum[seg]) / span
        a, b = pts[seg], pts[seg + 1]
        out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out


def _bearing(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.atan2(b[1] - a[1], b[0] - a[0])


def _ang_diff(a: float, b: float) -> float:
    """Smallest absolute angle between two bearings (radians)."""
    d = abs(a - b) % (2 * math.pi)
    return min(d, 2 * math.pi - d)


def simplify_by_angle(
    pts: list[tuple[float, float]], angle_tol_deg: float, min_segment: float
) -> list[tuple[float, float]]:
    """Keep a vertex only where the line has turned more than ``angle_tol_deg``.

    Walks the line accumulating the local turn angle between consecutive
    segments; a vertex is placed once that running total exceeds the tolerance,
    but only if the current run is already at least ``min_segment`` long, so no
    segment is shorter than the floor.
    """
    n = len(pts)
    if n < 3:
        return list(pts)
    tol = math.radians(angle_tol_deg)
    result = [pts[0]]
    anchor = 0
    accum = 0.0
    prev = _bearing(pts[0], pts[1])
    for i in range(1, n - 1):
        b = _bearing(pts[i], pts[i + 1])
        accum += _ang_diff(b, prev)
        prev = b
        run = math.dist(pts[anchor], pts[i])
        if accum > tol and run >= min_segment:
            result.append(pts[i])
            anchor = i
            accum = 0.0
    result.append(pts[-1])
    # Drop a too-short trailing segment by removing the penultimate vertex.
    if len(result) >= 3 and math.dist(result[-2], result[-1]) < min_segment:
        result.pop(-2)
    return result


def median_centerline(
    lines: list[list[tuple[float, float]]],
) -> list[tuple[float, float]]:
    """Dense pointwise-averaged centerline across the oriented contour lines."""
    oriented = _orient(lines)
    sampled = [resample(ln, M_RESAMPLE) for ln in oriented]
    k = len(sampled)
    return [
        (
            sum(s[j][0] for s in sampled) / k,
            sum(s[j][1] for s in sampled) / k,
        )
        for j in range(M_RESAMPLE)
    ]


def median_axis(
    lines: list[list[tuple[float, float]]],
    min_segment: float,
    angle_tol_deg: float,
) -> list[tuple[float, float]]:
    """Build the median axis (angle-simplified) from a set of contour lines."""
    return simplify_by_angle(median_centerline(lines), angle_tol_deg, min_segment)
