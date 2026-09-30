"""Offline reproduction of the callout-leader crossing on НК-2B-1.

Rebuilds the per-station dicts exactly as builder._label_params, runs the real
layout.plan_shelves with the production ShelfCfg, then reports, per side, the
along-canal order of points vs the fan order of labels and any leader crossings.
"""

from __future__ import annotations

import glob
import json
import math
import os
import sys

_PKG = r"C:\Arhyz\automation\scripts\draw_gabion_view"
sys.path.insert(0, _PKG)
import layout  # noqa: E402

DATA = r"C:\arhyz_s2_data\data\canals"
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG, exist_ok=True)
OUTF = os.path.join(LOG, "diag.log")

_CYR, _LAT = "АВЕКМНОРСТХ", "ABEKMHOPCTX"
_TR = {ord(a): b for a, b in zip(_CYR, _LAT)}
_TR.update({ord(a.lower()): b.lower() for a, b in zip(_CYR, _LAT)})


def _norm(s):
    return "".join(c for c in s.translate(_TR).lower() if c.isalnum())


def near(a, pool, t=0.12):
    return any(abs(a - b) <= t for b in pool)


def seg_cross(a, b, c, d):
    """True if open segments ab and cd properly intersect (shared endpoints ignored)."""

    def ccw(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    d1, d2 = ccw(c, d, a), ccw(c, d, b)
    d3, d4 = ccw(a, b, c), ccw(a, b, d)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)):
        return True
    return False


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "НК-2B-1"
    target = _norm(name)
    f = next(
        x
        for x in glob.glob(os.path.join(DATA, "*.json"))
        if _norm(os.path.basename(x)[:-5]) == target
    )
    d = json.load(open(f, encoding="utf-8-sig"))
    sp = d["section_points"]
    cs = sorted(float(x) for x in d.get("callout_stations", []))
    izl = [float(x) for x in d.get("pvi_stations", [])]
    izl += [float(p["station"]) for p in d.get("plan_pis", [])]

    stations, meta = [], []
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
                "izlom": near(sta, izl),
            }
        )
        meta.append((sta, p6, p5))

    cfg = layout.ShelfCfg(w=1.6, h=0.8, gap=5.0, fan_gap=2.7, drop_pos1y=8.0)
    placed = layout.plan_shelves(stations, cfg)

    # collect leaders per side: (sta, idx, point_xy, label_xy)
    sides = {0.0: [], 1.0: []}
    for si, pl in enumerate(placed):
        sta, p6, p5 = meta[si]
        for idx, flip, p1x, p1y in pl:
            pt = stations[si]["p7"] if idx == 7 else stations[si]["p6"]
            label = (pt[0] + p1x, pt[1] + p1y)
            sides[flip].append((sta, idx, pt, label))

    out = []
    total_cross = 0
    total_ovl = 0
    W, H = 1.6, 0.8
    for flip, recs in sides.items():
        recs_sta = sorted(recs, key=lambda r: r[0])  # along-canal (station) order
        out.append(f"\n=== side flip={flip}  ({len(recs)} callouts) ===")
        # crossings
        cross_pairs = []
        ovl_pairs = []
        for i in range(len(recs)):
            for j in range(i + 1, len(recs)):
                if seg_cross(recs[i][2], recs[i][3], recs[j][2], recs[j][3]):
                    cross_pairs.append((recs[i][0], recs[j][0]))
                li, lj = recs[i][3], recs[j][3]
                if abs(li[0] - lj[0]) < W and abs(li[1] - lj[1]) < H:
                    ovl_pairs.append((recs[i][0], recs[j][0]))
        total_cross += len(cross_pairs)
        total_ovl += len(ovl_pairs)
        out.append(
            f"leader crossings: {len(cross_pairs)}   label overlaps: {len(ovl_pairs)}"
        )
        for a, b in cross_pairs[:40]:
            out.append(f"  cross: sta {a:.2f} x {b:.2f}")
        for a, b in ovl_pairs[:40]:
            out.append(f"  overlap: sta {a:.2f} x {b:.2f}")
        # order check: is label vertical/along-canal order == station order?
        out.append("station-ordered (sta | point_xy | label_xy):")
        for sta, idx, pt, lab in recs_sta:
            out.append(
                f"  {sta:8.2f} idx{idx} pt=({pt[0]:.2f},{pt[1]:.2f}) lab=({lab[0]:.2f},{lab[1]:.2f})"
            )

    leads = []
    for flip, recs in sides.items():
        for _sta, _idx, pt, lab in recs:
            leads.append((math.hypot(lab[0] - pt[0], lab[1] - pt[1]), _sta, flip))
    leads.sort(reverse=True)
    out.insert(
        0,
        "longest leaders: "
        + ", ".join(f"{ll:.1f}m@{st:.1f}" for ll, st, _fl in leads[:8]),
    )
    out.insert(
        0,
        f"canal file: {os.path.basename(f)}  stations={len(stations)}  "
        f"TOTAL CROSSINGS={total_cross}  TOTAL OVERLAPS={total_ovl}",
    )
    text = "\n".join(out)
    with open(OUTF, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text[:3000])
    print(f"\n... full report: {OUTF}")


if __name__ == "__main__":
    main()
