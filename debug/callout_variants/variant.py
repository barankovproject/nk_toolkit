"""Sandbox for trying alternative callout-placement variants WITHOUT touching the
committed layout.plan_shelves. Builds the per-station input for a real canal, runs both
the production solver and an experimental `plan_shelves_variant`, and prints metrics
(leader crossings, shelf overlaps, longest leaders) side by side so a new idea can be
compared objectively before it ever lands in layout.py.

Run:  python automation/scripts/debug/callout_variants/variant.py [CANAL]   (default НК-2B-1)
"""

from __future__ import annotations

import glob
import json
import math
import os
import sys

_PKG = r"C:\Arhyz\automation\scripts\draw_gabion_view"
sys.path.insert(0, _PKG)
import layout  # noqa: E402  (production solver — the baseline)

DATA = r"C:\arhyz_s2_data\data\canals"
_CYR, _LAT = "АВЕКМНОРСТХ", "ABEKMHOPCTX"
_TR = {ord(a): b for a, b in zip(_CYR, _LAT)}
_TR.update({ord(a.lower()): b.lower() for a, b in zip(_CYR, _LAT)})


def _norm(s):
    return "".join(c for c in s.translate(_TR).lower() if c.isalnum())


def _seg_cross(a, b, c, d):
    def ccw(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    return ((ccw(c, d, a) > 0) != (ccw(c, d, b) > 0)) and (
        (ccw(a, b, c) > 0) != (ccw(a, b, d) > 0)
    )


def load_stations(name):
    f = next(
        x
        for x in glob.glob(os.path.join(DATA, "*.json"))
        if _norm(os.path.basename(x)[:-5]) == _norm(name)
    )
    d = json.load(open(f, encoding="utf-8-sig"))
    sp = d["section_points"]
    cs = sorted(float(x) for x in d.get("callout_stations", []))
    izl = [float(x) for x in d.get("pvi_stations", [])]
    izl += [float(p["station"]) for p in d.get("plan_pis", [])]
    stations = []
    for sta in cs:
        k = f"{sta:.3f}"
        if k not in sp:
            continue
        pts = sp[k]
        p6, p5 = pts[7], pts[6]
        ax, ay = (p6[0] + p5[0]) / 2.0, (p6[1] + p5[1]) / 2.0
        dx, dy = p5[0] - p6[0], p5[1] - p6[1]
        mag = math.hypot(dx, dy) or 1.0
        ux, uy = dx / mag, dy / mag
        proj = [(p[0] - ax) * ux + (p[1] - ay) * uy for p in pts]
        stations.append(
            {
                "p7": (p6[0], p6[1]),
                "p6": (p5[0], p5[1]),
                "u": (ux, uy),
                "a": (ax, ay),
                "ext_plus": max(proj),
                "ext_minus": max(-q for q in proj),
                "t": float(sta),
                "izlom": any(abs(sta - z) <= 0.12 for z in izl),
            }
        )
    return os.path.basename(f), stations


def metrics(stations, placed, w=1.6, h=0.8):
    sides = {0.0: [], 1.0: []}
    for si, pl in enumerate(placed):
        for idx, flip, p1x, p1y in pl:
            pt = stations[si]["p7"] if idx == 7 else stations[si]["p6"]
            sides[flip].append((pt, (pt[0] + p1x, pt[1] + p1y)))
    cross = ovl = 0
    leads = []
    for recs in sides.values():
        for i in range(len(recs)):
            leads.append(
                math.hypot(recs[i][1][0] - recs[i][0][0], recs[i][1][1] - recs[i][0][1])
            )
            for j in range(i + 1, len(recs)):
                if _seg_cross(recs[i][0], recs[i][1], recs[j][0], recs[j][1]):
                    cross += 1
                a, b = recs[i][1], recs[j][1]
                if abs(a[0] - b[0]) < w and abs(a[1] - b[1]) < h:
                    ovl += 1
    leads.sort(reverse=True)
    return cross, ovl, leads[:5]


# ---------------------------------------------------------------------------
# EXPERIMENTAL VARIANT — Delaunay-style "equal triangles": per side, place labels
# in TWO staggered columns (near = offset o, far = o + col_gap). Consecutive
# stations alternate columns, so the leaders form a strip of near-equal triangles.
# Because a crowded cluster is shown by staggering across columns (not by sliding
# far along the canal), the leader length is bounded (≤ o + col_gap) — no "разлёт".
# ---------------------------------------------------------------------------
def plan_shelves_variant(stations, cfg=None):
    cfg = cfg or layout.ShelfCfg()
    verts_c = [s["a"] for s in stations]
    slen_c = [0.0]
    for k in range(1, len(verts_c)):
        slen_c.append(
            slen_c[-1]
            + math.hypot(
                verts_c[k][0] - verts_c[k - 1][0], verts_c[k][1] - verts_c[k - 1][1]
            )
        )
    col_gap = (
        cfg.w + 0.4
    )  # perpendicular spacing between the two columns (clears a box)
    sides = {0.0: [], 1.0: []}
    for si, s in enumerate(stations):
        ux, uy = s["u"]
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
                    "px": pt[0],
                    "py": pt[1],
                }
            )
    sep_same = (
        cfg.fan_gap
    )  # min along-canal spacing between two labels in the SAME column
    placed = {}
    for flip, recs in sides.items():
        asc = sorted(recs, key=lambda r: r["si"])
        dirs = [(r["sux"], r["suy"]) for r in asc]
        near_last = far_last = -1e9  # arc of the last label placed in each column
        for r in asc:
            arc = slen_c[r["si"]]  # natural along-canal position
            # greedy: use the near column if free there, else the far column, else push the
            # less-occupied column forward just enough. Single column when sparse (no
            # crossings); the far column only kicks in where the near one is crowded.
            if arc >= near_last + sep_same:
                far = False
                near_last = arc
                pos_arc = arc
            elif arc >= far_last + sep_same:
                far = True
                far_last = arc
                pos_arc = arc
            elif near_last <= far_last:
                far = False
                pos_arc = near_last + sep_same
                near_last = pos_arc
            else:
                far = True
                pos_arc = far_last + sep_same
                far_last = pos_arc
            cx, cy, dx, dy = layout._sample(verts_c, slen_c, dirs, pos_arc)
            o = r["o"] + (col_gap if far else 0.0)
            placed[(r["si"], r["idx"])] = (
                flip,
                cx + o * dx - r["px"],
                cy + o * dy - r["py"],
            )
    result = []
    for si in range(len(stations)):
        result.append(
            [(idx,) + placed[(si, idx)] for idx in (7, 6) if (si, idx) in placed]
        )
    return result


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "НК-2B-1"
    fname, stations = load_stations(name)
    cfg = layout.ShelfCfg(w=1.6, h=0.8, gap=5.0, fan_gap=2.7, drop_pos1y=8.0)
    print(f"canal: {fname}  stations={len(stations)}")
    for label, fn in (
        ("production", layout.plan_shelves),
        ("variant", plan_shelves_variant),
    ):
        c, o, leads = metrics(stations, fn(stations, cfg))
        print(
            f"  {label:11} crossings={c}  overlaps={o}  "
            f"longest={', '.join(f'{x:.1f}' for x in leads)}"
        )


if __name__ == "__main__":
    main()
