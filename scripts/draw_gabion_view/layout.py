"""Pure callout-shelf placement geometry (no Civil 3D / .NET imports).

Model (reverse-engineered from the user's manual layout on 8 canals, ~600 blocks):
- shelf placed along the section TRANSVERSE direction (unit u = P6->P5, computed per
  station), on the side its point sits; the block is NOT rotated, so the transverse
  offset is decomposed into world Pos1X/Pos1Y. P6 goes to the -u side, P5 to the +u
  side, pushed out just enough that its box clears the gabion (rule 1). For a vertical
  canal u = world +X and this reduces exactly to the old left/right-in-X layout.
- the "fan" spreads shelves along the perpendicular ALONG-CANAL direction (v = perp u),
  using the projection of each point onto v; per side, shelves are spread with a minimum
  gap by the classic label-spreading / pool-adjacent-violators algorithm, so a tight
  cluster of break/dobornie points splits symmetrically (top shelves tilt up, bottom
  tilt down — the user never leaves a leader horizontal), while isolated shelves stay
  put. This both avoids shelf overlap (rule 2) and reproduces the up/down balance.
- изломы are mandatory; a доборный whose fanned leader grows past the budget is
  dropped (the user's "thinning").

Kept import-free so tests/draw_gabion_view can exercise the exact code offline.
"""

from __future__ import annotations

import math


class ShelfCfg:
    """Placement knobs (calibrated against the manual эталон)."""

    def __init__(self, w=4.7, h=2.5, gap=5.0, fan_gap=2.7, drop_pos1y=8.0):
        self.w = w  # drawn shelf footprint
        self.h = h
        self.gap = gap  # min clear gap between shelf near-edge and gabion edge (rule 1)
        self.fan_gap = fan_gap  # min vertical spacing between stacked shelves (the fan)
        self.drop_pos1y = drop_pos1y  # |Pos1Y| past which a доборный is dropped


def _spread(desired: list[float], g: float) -> list[float]:
    """Assign y positions (top→bottom) ≥ g apart, minimal displacement, centred.

    Pool-adjacent-violators: merge neighbours that are closer than g into a block
    positioned at its members' mean, then lay members out symmetrically at g spacing.
    Isolated points keep their desired y (no forced tilt); clusters fan from centre.
    `desired` must be sorted descending (top first).
    """
    blocks: list[list[float]] = []  # [sum_desired, count]
    for d in desired:
        blocks.append([d, 1])
        while len(blocks) > 1:
            s2, n2 = blocks[-1]
            s1, n1 = blocks[-2]
            bottom1 = s1 / n1 - (n1 - 1) / 2.0 * g
            top2 = s2 / n2 + (n2 - 1) / 2.0 * g
            if bottom1 - top2 < g - 1e-9:  # overlap → merge
                blocks[-2] = [s1 + s2, n1 + n2]
                blocks.pop()
            else:
                break
    ys = []
    for s, n in blocks:
        c = s / n
        for k in range(n):
            ys.append(c + ((n - 1) / 2.0 - k) * g)
    return ys


def _spread_var(desired: list[float], gaps: list[float]) -> list[float]:
    """Centred spread with a per-pair minimum gap: output o ascends with
    o[k+1] - o[k] >= gaps[k], least-squares closest to `desired`.

    Subtracting the cumulative gap ramp turns the spacing constraints into a plain
    monotone (isotonic) regression solved by pool-adjacent-violators.
    """
    if not desired:
        return []
    cum = [0.0]
    for g in gaps:
        cum.append(cum[-1] + g)
    e = [desired[k] - cum[k] for k in range(len(desired))]
    blocks: list[list[float]] = []  # [sum, count]
    for v in e:
        blocks.append([v, 1])
        while (
            len(blocks) > 1
            and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]
        ):
            s2, n2 = blocks.pop()
            s1, n1 = blocks.pop()
            blocks.append([s1 + s2, n1 + n2])  # merge the inversion into a shared mean
    flat: list[float] = []
    for s, n in blocks:
        flat += [s / n] * n
    return [flat[k] + cum[k] for k in range(len(desired))]


def _sample(verts: list, slen: list, dirs: list, target: float):
    """At arc-length `target` along polyline `verts` return (x, y, dx, dy): the point and
    the per-vertex direction `dirs` interpolated there (a smooth field, e.g. the section
    transverse u). Extrapolates past either end with the end point/direction.
    """
    if len(verts) == 1:
        return verts[0][0], verts[0][1], dirs[0][0], dirs[0][1]

    def _unit(vx, vy):
        m = math.hypot(vx, vy) or 1.0
        return vx / m, vy / m

    if target <= slen[0]:
        sx, sy = _unit(verts[1][0] - verts[0][0], verts[1][1] - verts[0][1])
        f = target - slen[0]
        return verts[0][0] + sx * f, verts[0][1] + sy * f, dirs[0][0], dirs[0][1]
    if target >= slen[-1]:
        sx, sy = _unit(verts[-1][0] - verts[-2][0], verts[-1][1] - verts[-2][1])
        f = target - slen[-1]
        return verts[-1][0] + sx * f, verts[-1][1] + sy * f, dirs[-1][0], dirs[-1][1]
    lo, hi = 0, len(slen) - 1
    while hi - lo > 1:  # binary search for the containing segment
        mid = (lo + hi) // 2
        if slen[mid] <= target:
            lo = mid
        else:
            hi = mid
    seg = slen[hi] - slen[lo] or 1.0
    f = (target - slen[lo]) / seg
    dx, dy = _unit(
        dirs[lo][0] + (dirs[hi][0] - dirs[lo][0]) * f,
        dirs[lo][1] + (dirs[hi][1] - dirs[lo][1]) * f,
    )
    return (
        verts[lo][0] + (verts[hi][0] - verts[lo][0]) * f,
        verts[lo][1] + (verts[hi][1] - verts[lo][1]) * f,
        dx,
        dy,
    )


def plan_shelves(stations: list[dict], cfg: "ShelfCfg | None" = None):
    """Place the top-of-wall callouts for every station.

    stations: ordered list of dicts with p7, p6 (xy of idx 7/6 = P6/P5), u (transverse
    unit P6->P5), a (axis midpoint xy), ext_plus/ext_minus (gabion extent measured along
    +u / -u from the axis), izlom (bool). The list MUST be in along-canal (station) order.
    Returns, per station, a list of placed callouts (0..2): (point_idx, flip, pos1x, pos1y).
    pos1x/pos1y are WORLD offsets fed to the non-rotated block's grips.
    """
    cfg = cfg or ShelfCfg()

    # centreline polyline (axis points, station order) + cumulative arc-length: the stable
    # rail the fan runs on (never folds, ≈uniform step), unlike an offset curve.
    verts_c = [s["a"] for s in stations]
    slen_c = [0.0]
    for k in range(1, len(verts_c)):
        slen_c.append(
            slen_c[-1]
            + math.hypot(
                verts_c[k][0] - verts_c[k - 1][0], verts_c[k][1] - verts_c[k - 1][1]
            )
        )

    # 1. per point: offset distance o that clears the gabion (rule 1) and the OUTWARD side
    #    direction su = sign·u (P6 idx 7 on -u, P5 idx 6 on +u — intrinsic, any bearing).
    #    bx,by is the un-fanned label, used only to size the fan (compression).
    sides = {0.0: [], 1.0: []}  # flip -> list of point records
    for si, s in enumerate(stations):
        ux, uy = s["u"]
        ax, ay = s["a"]
        for pt, idx, sign in ((s["p7"], 7, -1.0), (s["p6"], 6, 1.0)):
            ext = s["ext_plus"] if sign > 0 else s["ext_minus"]
            o = ext + cfg.w / 2.0 + cfg.gap
            sides[1.0 if sign > 0 else 0.0].append(
                {
                    "si": si,
                    "idx": idx,
                    "o": o,
                    "sux": sign * ux,
                    "suy": sign * uy,
                    "bx": ax + sign * o * ux,
                    "by": ay + sign * o * uy,
                    "px": pt[0],
                    "py": pt[1],
                    "izlom": s["izlom"],
                }
            )

    # 2. per side: fan along the CENTRELINE arc (monotone ⇒ never crosses) with a per-pair
    #    gap scaled by 1/compression — on the inside of a bend the labels (offset by o) crowd
    #    by (offset step)/(centreline step), so we demand a proportionally larger centreline
    #    gap and they clear once offset out. Each label is placed on the centreline at its
    #    fanned arc and offset by o along the section transverse u INTERPOLATED there (a
    #    smooth field, = the original u at every station, so straight canals are unchanged
    #    and there is no corner jitter). A доборный whose shift exceeds the budget is dropped
    #    and re-fanned (изломы are never dropped); leaders near a sharp bend grow long and
    #    slanted, as in the manual layout.
    placed = {}  # (si, idx) -> (flip, pos1x, pos1y)
    for flip, recs in sides.items():
        asc = sorted(recs, key=lambda r: r["si"])  # along-canal order
        dirs = [(r["sux"], r["suy"]) for r in asc]  # outward side direction per station
        active = list(range(len(asc)))
        boost = {}  # si -> extra centreline gap added to a pair whose shelves still collide
        xy = {}
        for _ in range(
            8 * len(asc) + 8
        ):  # solve → check → widen colliding pairs → re-solve
            sc = [slen_c[asc[k]["si"]] for k in active]
            # start minimal (fan_gap everywhere) so labels stay near their points; only the
            # feedback below grows a gap, and only for a pair that actually still overlaps —
            # this keeps leaders short (no "разлёт") instead of pre-spreading by 1/compression.
            gaps = [
                cfg.fan_gap + boost.get(asc[active[p]]["si"], 0.0)
                for p in range(len(active) - 1)
            ]
            fan = _spread_var(sc, gaps)
            # drop the farthest over-budget доборный (изломы are never dropped), then re-solve
            worst, worst_d = None, cfg.drop_pos1y
            for pos, k in enumerate(active):
                if not asc[k]["izlom"] and abs(fan[pos] - sc[pos]) > worst_d:
                    worst, worst_d = pos, abs(fan[pos] - sc[pos])
            if worst is not None:
                active.pop(worst)
                continue
            # place, then check real shelf boxes: where two still collide, widen the
            # centreline gap for that pair (the offset swings back on a fold, so spacing on
            # the centreline must grow until the offset positions actually separate).
            xy = {}
            for pos, k in enumerate(active):
                cx, cy, dx, dy = _sample(verts_c, slen_c, dirs, fan[pos])
                xy[k] = (cx + asc[k]["o"] * dx, cy + asc[k]["o"] * dy)
            widened = False
            for p in range(len(active) - 1):
                ax2, ay2 = xy[active[p]]
                bx2, by2 = xy[active[p + 1]]
                if abs(ax2 - bx2) < cfg.w and abs(ay2 - by2) < cfg.h:
                    si0 = asc[active[p]]["si"]
                    boost[si0] = boost.get(si0, 0.0) + cfg.fan_gap  # grow minimally
                    widened = True
            if not widened:
                break
        for k in active:
            r = asc[k]
            placed[(r["si"], r["idx"])] = (flip, xy[k][0] - r["px"], xy[k][1] - r["py"])

    # 3. assemble per station (dropped points simply have no placed entry)
    out = []
    for si in range(len(stations)):
        here = [(idx,) + placed[(si, idx)] for idx in (7, 6) if (si, idx) in placed]
        out.append([(idx, flip, p1x, p1y) for idx, flip, p1x, p1y in here])
    return out
