"""Region-based perpendicular grid along the anchor axis, clipped to the band.

The anchor band is the strip between the lowest and highest horizontals (the
outer contours). Perpendiculars are normal to each straight axis segment and
clipped to that band + overhang, so they cross only the anchor rows (no long
needles across the much larger slope boundary). Each interior axis vertex also
gets a bisector divider (region separator), clipped to the same band.
"""

from __future__ import annotations

import math
from typing import Any

from Autodesk.AutoCAD.DatabaseServices import OpenMode, Polyline

_EPS = 1e-9


def load_axis(tx: Any, db: Any, layer: str) -> tuple[list[tuple[float, float]], float]:
    """Return (vertices, elevation) of the (longest) polyline on ``layer``."""
    best: list[tuple[float, float]] = []
    best_elev = 0.0
    best_len = -1.0
    ms = tx.GetObject(db.CurrentSpaceId, OpenMode.ForRead)
    for oid in ms:
        ent = tx.GetObject(oid, OpenMode.ForRead)
        if not isinstance(ent, Polyline) or ent.Layer != layer:
            continue
        pts = _verts(ent)
        ln = _polylen(pts)
        if ln > best_len:
            best, best_elev, best_len = pts, float(ent.Elevation), ln
    return best, best_elev


def load_band_contours(tx: Any, db: Any, layer: str) -> list[list[tuple[float, float]]]:
    """Return [lowest_contour, highest_contour] — longest run at min/max elevation."""
    by_elev: dict[float, list[tuple[float, float]]] = {}
    ms = tx.GetObject(db.CurrentSpaceId, OpenMode.ForRead)
    for oid in ms:
        ent = tx.GetObject(oid, OpenMode.ForRead)
        if not isinstance(ent, Polyline) or ent.Layer != layer:
            continue
        elev = round(float(ent.Elevation), 3)
        pts = _verts(ent)
        if elev not in by_elev or _polylen(pts) > _polylen(by_elev[elev]):
            by_elev[elev] = pts
    if len(by_elev) < 2:
        return list(by_elev.values())
    return [by_elev[min(by_elev)], by_elev[max(by_elev)]]


def _verts(ent: Any) -> list[tuple[float, float]]:
    return [
        (ent.GetPoint2dAt(i).X, ent.GetPoint2dAt(i).Y)
        for i in range(int(ent.NumberOfVertices))
    ]


def _polylen(pts: list[tuple[float, float]]) -> float:
    return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


# ---------------------------------------------------------------------------
# Vector helpers
# ---------------------------------------------------------------------------


def _unit(vx: float, vy: float) -> tuple[float, float]:
    n = math.hypot(vx, vy) or 1.0
    return (vx / n, vy / n)


def _perp(vx: float, vy: float) -> tuple[float, float]:
    return (-vy, vx)


def _avg_tangent(axis, i):
    d_in = _unit(axis[i][0] - axis[i - 1][0], axis[i][1] - axis[i - 1][1])
    d_out = _unit(axis[i + 1][0] - axis[i][0], axis[i + 1][1] - axis[i][1])
    return _unit(d_in[0] + d_out[0], d_in[1] + d_out[1])


def divider_dirs(axis: list[tuple[float, float]]) -> dict[int, tuple[float, float]]:
    """Bisector divider direction at each interior vertex {index: unit_dir}."""
    # The divider line runs across the band, perpendicular to the average tangent.
    return {i: _perp(*_avg_tangent(axis, i)) for i in range(1, len(axis) - 1)}


def divider_normals(axis: list[tuple[float, float]]) -> dict[int, tuple[float, float]]:
    """Forward (axis-direction) normal of each divider {index: unit_dir}.

    A point Q is past divider ``i`` (toward higher segments) when
    dot(Q - axis[i], normal[i]) > 0. Used to test which segment territory a
    crossing belongs to.
    """
    return {i: _avg_tangent(axis, i) for i in range(1, len(axis) - 1)}


# ---------------------------------------------------------------------------
# Ray clipping against the band (open contour polylines)
# ---------------------------------------------------------------------------


def _seg_s(
    p: tuple[float, float],
    n: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> float | None:
    """Signed distance s along ray p+s*n where it meets segment c-d, else None."""
    ex, ey = d[0] - c[0], d[1] - c[1]
    det = n[0] * (-ey) - (-ex) * n[1]
    if abs(det) < _EPS:
        return None
    rx, ry = c[0] - p[0], c[1] - p[1]
    s = (rx * (-ey) - (-ex) * ry) / det
    u = (n[0] * ry - n[1] * rx) / det
    if -_EPS <= u <= 1 + _EPS:
        return s
    return None


def _crossings(
    p: tuple[float, float],
    n: tuple[float, float],
    contours: list[list[tuple[float, float]]],
) -> list[float]:
    out: list[float] = []
    for poly in contours:
        for i in range(len(poly) - 1):
            s = _seg_s(p, n, poly[i], poly[i + 1])
            if s is not None:
                out.append(s)
    return out


def clip_to_band(
    p: tuple[float, float],
    n: tuple[float, float],
    contours: list[list[tuple[float, float]]],
    overhang: float,
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """Clip ray p+s*n to the band (nearest contour crossing each side) + overhang."""
    crossings = _crossings(p, n, contours)
    neg = [s for s in crossings if s < 0]
    pos = [s for s in crossings if s > 0]
    if not neg or not pos:
        return None
    s_lo = max(neg) - overhang
    s_hi = min(pos) + overhang
    return (
        (p[0] + n[0] * s_lo, p[1] + n[1] * s_lo),
        (p[0] + n[0] * s_hi, p[1] + n[1] * s_hi),
    )


# ---------------------------------------------------------------------------
# Stations + builders
# ---------------------------------------------------------------------------


def _stations(axis: list[tuple[float, float]], step: float):
    """Yield (position, unit_normal) every ``step`` along the axis (segment normal)."""
    cum = [0.0]
    for i in range(len(axis) - 1):
        cum.append(cum[-1] + math.dist(axis[i], axis[i + 1]))
    total = cum[-1]
    d = 0.0
    seg = 0
    while d <= total + _EPS:
        while seg < len(axis) - 2 and cum[seg + 1] < d:
            seg += 1
        a, b = axis[seg], axis[seg + 1]
        span = cum[seg + 1] - cum[seg]
        t = 0.0 if span < _EPS else (d - cum[seg]) / span
        pos = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        yield pos, _perp(*_unit(b[0] - a[0], b[1] - a[1]))
        d += step


def build_perpendiculars(
    axis: list[tuple[float, float]],
    contours: list[list[tuple[float, float]]],
    step: float,
    overhang: float,
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """One perpendicular per station, clipped to the band + overhang."""
    out = []
    for pos, normal in _stations(axis, step):
        clipped = clip_to_band(pos, normal, contours, overhang)
        if clipped is not None:
            out.append(clipped)
    return out


# ---------------------------------------------------------------------------
# Phase-locked per-segment grid (seams aligned on the outer contour)
# ---------------------------------------------------------------------------


def _ray_contour_point(p, n, contour):
    """Nearest crossing point of the full line p±s*n with the contour, or None."""
    best = None
    best_abs = None
    for i in range(len(contour) - 1):
        s = _seg_s(p, n, contour[i], contour[i + 1])
        if s is not None and (best_abs is None or abs(s) < best_abs):
            best_abs = abs(s)
            best = (p[0] + n[0] * s, p[1] + n[1] * s)
    return best


def _arc_pos(contour, pt):
    """Arc length from contour[0] to the point on the contour nearest ``pt``."""
    cum = 0.0
    best = 0.0
    best_d = None
    for i in range(len(contour) - 1):
        a, b = contour[i], contour[i + 1]
        seg = math.dist(a, b)
        if seg < _EPS:
            continue
        t = ((pt[0] - a[0]) * (b[0] - a[0]) + (pt[1] - a[1]) * (b[1] - a[1])) / (
            seg * seg
        )
        tc = max(0.0, min(1.0, t))
        proj = (a[0] + (b[0] - a[0]) * tc, a[1] + (b[1] - a[1]) * tc)
        dd = math.dist(pt, proj)
        if best_d is None or dd < best_d:
            best_d = dd
            best = cum + seg * tc
        cum += seg
    return best


def _segment_phase(prev_cross, a, d, n, contours, line_step):
    """Offset (along d from a) so the first line lines up on the outer contour."""
    lo, hi = contours
    c_lo = _ray_contour_point(a, n, lo)
    c_hi = _ray_contour_point(a, n, hi)
    if prev_cross is None or c_lo is None or c_hi is None:
        return 0.0
    # Outer contour = the one with the larger default gap at this seam.
    gap_lo = abs(_arc_pos(lo, c_lo) - _arc_pos(lo, prev_cross["lo"]))
    gap_hi = abs(_arc_pos(hi, c_hi) - _arc_pos(hi, prev_cross["hi"]))
    outer, prev_pt = (
        (hi, prev_cross["hi"]) if gap_hi >= gap_lo else (lo, prev_cross["lo"])
    )
    target = _arc_pos(outer, prev_pt) + line_step
    # Scan t so the line's outer crossing arc is closest to target.
    best_t = 0.0
    best_err = None
    t = -2.0 * line_step
    while t <= 2.0 * line_step + _EPS:
        p = (a[0] + d[0] * t, a[1] + d[1] * t)
        cp = _ray_contour_point(p, n, outer)
        if cp is not None:
            err = abs(_arc_pos(outer, cp) - target)
            if best_err is None or err < best_err:
                best_err = err
                best_t = t
        t += line_step / 40.0
    # Reduce to a phase within [0, line_step).
    return best_t - line_step * math.floor(best_t / line_step)


def build_phase_locked(
    axis: list[tuple[float, float]],
    contours: list[list[tuple[float, float]]],
    line_step: float,
    overhang: float,
    seam_overlap: float,
):
    """Per-segment parallel grid; each segment phase-locked to the previous on
    the outer contour so the spacing stays even across the seam. Lines run
    ``seam_overlap`` metres past the segment's own territory into the neighbours
    (overshoot that no longer crosses the band is dropped by the clip).

    Returns a list of dicts: {a, b, seg, parity}. ``parity`` (0/1) follows the
    global axis lattice so red/blue alternation continues across seams.
    """
    out = []
    prev_cross = None
    seg_start = 0.0  # cumulative axis arc at the segment start
    for i in range(len(axis) - 1):
        a, b = axis[i], axis[i + 1]
        seg_len = math.dist(a, b)
        d = _unit(b[0] - a[0], b[1] - a[1])
        n = _perp(*d)
        phase = _segment_phase(prev_cross, a, d, n, contours, line_step)
        lo_t = -seam_overlap
        hi_t = seg_len + seam_overlap
        k = math.ceil((lo_t - phase) / line_step)
        last_p = None  # last line WITHIN the territory, used to lock the next seam
        while True:
            t = phase + k * line_step
            if t > hi_t + _EPS:
                break
            if t >= lo_t - _EPS:
                p = (a[0] + d[0] * t, a[1] + d[1] * t)
                clipped = clip_to_band(p, n, contours, overhang)
                if clipped is not None:
                    parity = int(round((seg_start + t) / line_step)) % 2
                    out.append(
                        {"a": clipped[0], "b": clipped[1], "seg": i, "parity": parity}
                    )
                if -_EPS <= t <= seg_len + _EPS:
                    last_p = p
            k += 1
        if last_p is not None:
            prev_cross = {
                "lo": _ray_contour_point(last_p, n, contours[0]),
                "hi": _ray_contour_point(last_p, n, contours[1]),
            }
        seg_start += seg_len
    return out


def build_dividers(
    axis: list[tuple[float, float]],
    contours: list[list[tuple[float, float]]],
    dividers: dict[int, tuple[float, float]],
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Region-separator segments (one per interior vertex), clipped to the band."""
    out = []
    for i, d in dividers.items():
        seg = clip_to_band(axis[i], d, contours, 0.0)
        if seg is not None:
            out.append(seg)
    return out
