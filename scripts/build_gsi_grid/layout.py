"""Pure-geometry GSI wall layout for one gabion ring (no DB, no Z).

Shared by `build_gsi_grid` (draws the polygons as 2D polylines for visual verification) and
`build_gsi_well` (extrudes them into 3D Solid3d tiers). Given a boundary ring, an inner ring and
an `along` pitch, `layout_ring` returns the filler polygons that tile the ring between the two
contours: straight rectangular blocks along each wall, plus the corner handling

  - right-angle corner: the more axis-aligned wall runs through (covered by its blocks, no wedge);
  - gentle obtuse corner (turn = 180 - interior <= 90): a fan-shaped wedge fanned from the
    opposite corner and split into ~`along` slices;
  - sharp corner (turn > 90): the post wall runs through clipped to the contour, and the single
    leftover triangle on the butt side is one patch.

Only XY and plain numbers here so the 2D and 3D callers never drift.
"""

from __future__ import annotations

import math
from typing import Callable, Optional

_ORTHO_TOL = 10.0  # corners within this many degrees of 90 are treated as right angles
_EPS = 1e-9

Pt = tuple[float, float]


def _signed_area(pts: list[Pt]) -> float:
    s = 0.0
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        s += a[0] * b[1] - b[0] * a[1]
    return s / 2.0


def _ccw(pts: list[Pt]) -> list[Pt]:
    return pts if _signed_area(pts) > 0 else list(reversed(pts))


def _dist(a: Pt, b: Pt) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _lerp(a: Pt, b: Pt, t: float) -> Pt:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def _best_offset(ref: list[Pt], other: list[Pt]) -> int:
    """Rotation k aligning `other` corners to `ref` corners (min total distance)."""
    n = len(ref)
    best, best_d = 0, None
    for k in range(n):
        d = sum(_dist(ref[i], other[(i + k) % n]) for i in range(n))
        if best_d is None or d < best_d:
            best_d, best = d, k
    return best


def _interior_angle_deg(prev: Pt, cur: Pt, nxt: Pt) -> float:
    """Angle of the wedge at `cur` between edges cur->prev and cur->nxt, in degrees."""
    ux, uy = prev[0] - cur[0], prev[1] - cur[1]
    vx, vy = nxt[0] - cur[0], nxt[1] - cur[1]
    lu, lv = math.hypot(ux, uy), math.hypot(vx, vy)
    if lu < _EPS or lv < _EPS:
        return 180.0
    c = max(-1.0, min(1.0, (ux * vx + uy * vy) / (lu * lv)))
    return math.degrees(math.acos(c))


def _foot(p: Pt, a: Pt, b: Pt) -> tuple[Optional[Pt], float]:
    """Foot of the perpendicular from p onto segment a->b and its parameter t (0..1 = on it)."""
    abx, aby = b[0] - a[0], b[1] - a[1]
    l2 = abx * abx + aby * aby
    if l2 < _EPS:
        return None, -1.0
    t = ((p[0] - a[0]) * abx + (p[1] - a[1]) * aby) / l2
    return (a[0] + t * abx, a[1] + t * aby), t


def _verticality(a: Pt, b: Pt) -> float:
    L = _dist(a, b)
    return abs(b[1] - a[1]) / L if L > _EPS else 0.0


def _axis(a: Pt, b: Pt) -> float:
    """How axis-aligned an edge is: 1.0 for horizontal/vertical, ~0.707 at 45 deg."""
    dx, dy = abs(b[0] - a[0]), abs(b[1] - a[1])
    L = math.hypot(dx, dy)
    return max(dx, dy) / L if L > _EPS else 0.0


def _post_key(a: Pt, b: Pt) -> tuple[float, float]:
    """Sort key for choosing the wall that runs through a corner (the "post").

    Prefer the more axis-aligned wall (a box side over a slanted roof, so its extension stays
    inside the contour), breaking ties by verticality (keeps right-angle behaviour: the vertical
    wall owns the corner square, the horizontal one butts).
    """
    return (_axis(a, b), _verticality(a, b))


def _line_intersect(p1: Pt, p2: Pt, p3: Pt, p4: Pt) -> Optional[Pt]:
    """Intersection of the infinite lines (p1,p2) and (p3,p4); None if (near) parallel."""
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4
    den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(den) < _EPS:
        return None
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
    return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))


def _split(length: float, unit: float = 1.0, min_cut: float = 0.5) -> list[float]:
    """Split a wall length into GSI block lengths (`unit` side along the wall).

    floor(L) whole `unit` blocks + one leftover; if the leftover is < `min_cut`, drop the
    last whole block and split the combined (unit + leftover) into two equal halves so no
    piece is shorter than min_cut. L < unit -> a single cut piece.
    """
    if length < unit - 1e-9:
        return [length]
    n = int(math.floor(length / unit + 1e-9))
    rem = length - n * unit
    if rem < 1e-9:
        return [unit] * n
    if rem >= min_cut - 1e-9:
        return [unit] * n + [rem]
    half = (unit + rem) / 2.0
    return [unit] * (n - 1) + [half, half]


def _dedupe(pts: list[Pt]) -> list[Pt]:
    """Drop consecutive duplicate points (and a closing duplicate) from a polygon ring."""
    out: list[Pt] = []
    for p in pts:
        if not out or _dist(out[-1], p) > 1e-6:
            out.append(p)
    if len(out) > 1 and _dist(out[0], out[-1]) < 1e-6:
        out.pop()
    return out


def _wedge_slices(
    bound: list[Pt], apex: Pt, unit: float = 1.0, min_cut: float = 0.5
) -> list[list[Pt]]:
    """Divide a corner wedge into ~`unit` slices fanned from `apex`.

    `bound` is the wedge's outer boundary polyline (foot -> outer corner -> foot); the wedge is
    that boundary closed back through the single inner `apex`. The WHOLE boundary length is split
    into `unit` + leftover pieces by `_split` (same rule as the walls) and each piece is a
    triangle/quad from its boundary sub-segment back to the apex -- so a long wedge is neither
    left as one piece nor merely halved by the diagonal.
    """
    seglens = [_dist(bound[i], bound[i + 1]) for i in range(len(bound) - 1)]
    total = sum(seglens)
    if total < 1e-6:
        return []

    def at(s: float) -> Pt:
        acc = 0.0
        for i, L in enumerate(seglens):
            if s <= acc + L or i == len(seglens) - 1:
                t = (s - acc) / L if L > _EPS else 0.0
                return _lerp(bound[i], bound[i + 1], max(0.0, min(1.0, t)))
            acc += L
        return bound[-1]

    slices: list[list[Pt]] = []
    s0 = 0.0
    for seg in _split(total, unit, min_cut):
        s1 = s0 + seg
        pts = [at(s0)]
        acc = 0.0
        for i in range(len(seglens) - 1):
            acc += seglens[i]
            if (
                s0 + 1e-9 < acc < s1 - 1e-9
            ):  # slice straddles an interior boundary vertex
                pts.append(bound[i + 1])
        pts.append(at(s1))
        pts.append(apex)
        slices.append(pts)
        s0 = s1
    return slices


def _end_cut(
    outer: list[Pt], inner: list[Pt], n: int, off: int, i: int, at_start: bool
) -> tuple[Pt, Pt]:
    """(outer, inner) points bounding one end of wall i's straight region.

    At a RIGHT-ANGLE or SHARP (interior < 90) corner the more axis-aligned wall (the "post") runs
    through the corner with rectangular blocks, but is CLIPPED so it stays inside the contour: its
    far cut sits where its inner rail meets the other wall's outer edge (point R). At a right
    angle R is the outer corner itself; at a sharp corner (a slanted neighbour) R is short of the
    corner, so the straight blocks stop at the outer contour instead of poking past it. The other
    wall butts with its own perpendicular. The leftover triangle between the post's clip and the
    outer corner is filled separately (see `layout_ring`).
    """
    oe_a, oe_b = outer[i], outer[(i + 1) % n]
    ie_a, ie_b = inner[(i + off) % n], inner[(i + 1 + off) % n]
    o_corner, i_corner = (oe_a, ie_a) if at_start else (oe_b, ie_b)

    # angle at this corner and which of the two meeting edges is the more axis-aligned "post"
    c = i if at_start else (i + 1) % n
    prev_o, cur_o, next_o = outer[(c - 1) % n], outer[c], outer[(c + 1) % n]
    ang = _interior_angle_deg(prev_o, cur_o, next_o)
    if ang <= 90.0 + _ORTHO_TOL:
        other = (prev_o, cur_o) if at_start else (cur_o, next_o)
        if _post_key(oe_a, oe_b) >= _post_key(other[0], other[1]):
            # post: extend through the corner but clip at R = (this inner rail) x (other outer
            # edge) so the extension stays inside the contour; outer point = R across the wall
            # depth (its perpendicular foot on this wall's outer edge). At a right angle R == the
            # outer corner, reproducing the run-through square.
            r = _line_intersect(ie_a, ie_b, other[0], other[1])
            if r is not None:
                pout, _ = _foot(r, oe_a, oe_b)
                if pout is not None:
                    return pout, r
            foot_line, _ = _foot(o_corner, ie_a, ie_b)
            return o_corner, (foot_line if foot_line is not None else i_corner)
        # otherwise butt against the owner (inset by depth via the perpendicular below)

    foot, t = _foot(i_corner, oe_a, oe_b)
    if foot is not None and -1e-9 <= t <= 1.0 + 1e-9:
        return foot, i_corner
    foot2, t2 = _foot(o_corner, ie_a, ie_b)
    if foot2 is not None and -1e-9 <= t2 <= 1.0 + 1e-9:
        return o_corner, foot2
    return o_corner, i_corner


def layout_ring(
    boundary: list[Pt],
    inner: list[Pt],
    along: float = 1.0,
    min_cut: float = 0.5,
    along_of: Optional[Callable[[float], float]] = None,
    rows_of: Optional[Callable[[float], list[float]]] = None,
) -> list[tuple[str, list[Pt]]]:
    """Filler polygons for one gabion ring between `boundary` and `inner`.

    Returns (kind, polygon) tuples with kind in:
      - "region": the straight-layout rectangle per wall (a construction outline, not a solid);
      - "block":  a gabion block quad;
      - "wedge":  a fan slice at a gentle obtuse corner;
      - "patch":  the triangular patch at a sharp corner.

    `along` is the block pitch along the perimeter (1.0 for lower OUTER..INNER tiers, 1.5 for the
    rotated top MIDDLE..INNER tier). The block depth is the ring width (boundary->inner), implicit
    in each polygon.

    `along_of`, when given, OVERRIDES `along` per WALL (not per corner wedge/patch -- those keep
    using the plain `along`): called with that wall's own measured depth (boundary->inner
    distance), its return value becomes that wall's pitch instead of the fixed `along`. Lets a
    caller rotate the block on just the walls whose depth doesn't match the ring's nominal
    orientation -- e.g. `build_gsi_well`'s top tier is normally INNER->MIDDLE depth 1.0 with the
    gabion's long (1.5) side along the wall, but a well whose MIDDLE contour steps one wall out to
    the full 1.5 lower-tier depth needs THAT wall's gabion rotated the other way (short 1.0 side
    along the wall) same as the lower tiers, not squashed into a non-existent 1.5x1.5 block (user
    2026-09-16: "если какой-то участок верхнего уровня 1.5м, можно просто развернуть блоки, как
    на нижних уровнях"). Requires the two rings to have matching vertex counts (raises ValueError
    otherwise so the caller can fall back to a plain ring prism).

    `rows_of`, when given, further splits ONE WALL's own depth RADIALLY into multiple
    stacked rows: called with that wall's own measured depth (the same value `along_of`
    already sees), it returns a list of row depths (outer-to-inner order) instead of a
    single float -- a one-element return means "no split" (today's behaviour, and the
    default `rows_of=None` skips this entirely). Needed when a single wall's real depth
    does not match any single catalog gabion unit at all but IS a sum of them (e.g. a
    2.0 m-deep wall on an otherwise-1.0 m band needs two 1.0 m rows, not one non-existent
    2.0 m block) -- `along_of` alone can only ROTATE a wall's single row between the two
    catalog sides, it cannot split it (user 2026-09-18, `dump_gsi_well_oversized_block`:
    13 consecutive gabion solids read `[1.0, 2.0, 1.0, 2.0]`, confirming one real wall
    was 2.0 m deep while the rest of that same tier was 1.0 m). Each row gets its OWN
    `along_of(row_depth)` pitch, so a 2-row 2.0 m wall reads exactly like two normal
    1.0 m-deep walls stacked radially, not one oversized block. Corner wedges/patches are
    NOT split by `rows_of` -- they still span the wall's full depth as one piece, a known
    limitation (see `.agents/prompts/layout-ring-per-wall-rows.md`) accepted for now since
    no reported case needs a multi-row corner.
    """
    b = _ccw(boundary)
    inr = _ccw(inner)
    n = len(b)
    if n < 3 or len(inr) != n:
        raise ValueError(
            f"boundary has {n} corners but inner has {len(inr)}; contours must match"
        )
    off = _best_offset(b, inr)
    out: list[tuple[str, list[Pt]]] = []

    # corners: gentle obtuse -> fan wedge; sharp -> triangular patch; right angle -> run-through
    for c in range(n):
        o_prev, o_cur, o_next = b[(c - 1) % n], b[c], b[(c + 1) % n]
        ang = _interior_angle_deg(o_prev, o_cur, o_next)
        if abs(ang - 90.0) <= _ORTHO_TOL:
            continue  # right-angle corner is covered by the run-through post, no wedge
        i_cur = inr[(c + off) % n]
        pout_e, pin_e = _end_cut(b, inr, n, off, (c - 1) % n, False)
        pout_s, pin_s = _end_cut(b, inr, n, off, c, True)
        turn = 180.0 - ang  # angle between the two perpendiculars
        if turn > 90.0:
            if _post_key(o_prev, o_cur) >= _post_key(o_cur, o_next):
                post_in, butt_out = pin_e, pout_s  # wall (c-1) post, wall c butt
            else:
                post_in, butt_out = pin_s, pout_e  # wall c post, wall (c-1) butt
            patch = _dedupe([i_cur, post_in, butt_out])
            if len(patch) >= 3:
                out.append(("patch", patch))
        else:
            if _dist(pout_e, pout_s) > 1e-6:
                bnd, apex = [pout_e, o_cur, pout_s], i_cur
            else:
                bnd, apex = [pin_e, i_cur, pin_s], o_cur
            for slc in _wedge_slices(bnd, apex, along, min_cut):
                out.append(("wedge", slc))

    # walls: straight-layout rectangle + gabion blocks split by `along` (or by
    # `along_of(depth)` when this wall's own depth calls for a rotated block),
    # further split radially into multiple rows when `rows_of(depth)` says this
    # wall's own depth needs more than one catalog row (see docstring).
    for i in range(n):
        pout_s, pin_s = _end_cut(b, inr, n, off, i, True)
        pout_e, pin_e = _end_cut(b, inr, n, off, i, False)
        out.append(("region", [pout_s, pout_e, pin_e, pin_s]))
        length = _dist(pout_s, pout_e)
        if length < 1e-6:
            continue
        depth = (_dist(pout_s, pin_s) + _dist(pout_e, pin_e)) / 2.0
        row_depths = rows_of(depth) if rows_of is not None else [depth]
        t_bounds = [0.0]
        for rd in row_depths:
            step = (rd / depth) if depth > 1e-9 else 1.0
            t_bounds.append(min(1.0, t_bounds[-1] + step))
        for row_idx, rd in enumerate(row_depths):
            t0, t1 = t_bounds[row_idx], t_bounds[row_idx + 1]
            row_pout_s = _lerp(pout_s, pin_s, t0)
            row_pin_s = _lerp(pout_s, pin_s, t1)
            row_pout_e = _lerp(pout_e, pin_e, t0)
            row_pin_e = _lerp(pout_e, pin_e, t1)
            wall_along = along_of(rd) if along_of is not None else along
            pos = 0.0
            for seg in _split(length, wall_along, min_cut):
                f0, f1 = pos / length, (pos + seg) / length
                pos += seg
                o0, o1 = (
                    _lerp(row_pout_s, row_pout_e, f0),
                    _lerp(row_pout_s, row_pout_e, f1),
                )
                i1, i0 = (
                    _lerp(row_pin_s, row_pin_e, f1),
                    _lerp(row_pin_s, row_pin_e, f0),
                )
                out.append(("block", [o0, o1, i1, i0]))
    return out
