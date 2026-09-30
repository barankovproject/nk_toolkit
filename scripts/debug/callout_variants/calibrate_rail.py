"""Calibrate the offset-rail / "паучок" placement against the manual reference dumped to
out/<canal>.csv. Builds the canal's closed outer outline (P7 left + P4 right), offsets it
OUTWARD by R with rounded corners (the capsule rail), projects every callout point onto the
rail, fans the projections so shelves don't overlap, and reports how close the resulting
pos1x/pos1y are to the manual placement. Sweeps R to find the best fit.

Run:  python automation/scripts/debug/callout_variants/calibrate_rail.py
"""

from __future__ import annotations

import csv
import glob
import json
import math
import os
import statistics as st
import sys

sys.path.insert(0, r"C:\Arhyz\automation\scripts\draw_gabion_view")
import layout  # noqa: E402  (_spread_var for fanning along the rail)

DATA = r"C:\arhyz_s2_data\data\canals"
OUT = r"C:\Arhyz\automation\scripts\debug\dump_callout_blocks\out"
CANALS = ["НК-1A-5", "НК-1A-6", "НК-1A-7", "НК-2B-1", "НК-3С-1"]

_CYR, _LAT = "АВЕКМНОРСТХ", "ABEKMHOPCTX"
_TR = {ord(a): b for a, b in zip(_CYR, _LAT)}
_TR.update({ord(a.lower()): b.lower() for a, b in zip(_CYR, _LAT)})


def _norm(s):
    return "".join(c for c in s.translate(_TR).lower() if c.isalnum())


def _find(name, root, ext):
    for x in glob.glob(os.path.join(root, "*" + ext)):
        if _norm(os.path.basename(x)[: -len(ext)]) == _norm(name):
            return x
    return None


def outward_rail(loop, R, arc_n=10):
    """Outward offset of a closed CCW polygon by R, convex corners filled with arcs."""
    n = len(loop)
    area = sum(
        loop[i][0] * loop[(i + 1) % n][1] - loop[(i + 1) % n][0] * loop[i][1]
        for i in range(n)
    )
    if area < 0:
        loop = loop[::-1]
    rail = []
    for i in range(n):
        a, b, c = loop[i], loop[(i + 1) % n], loop[(i + 2) % n]
        ex, ey = b[0] - a[0], b[1] - a[1]
        L = math.hypot(ex, ey) or 1.0
        ex, ey = ex / L, ey / L
        nx, ny = ey, -ex  # outward normal for CCW
        rail.append((a[0] + R * nx, a[1] + R * ny))
        rail.append((b[0] + R * nx, b[1] + R * ny))
        e2x, e2y = c[0] - b[0], c[1] - b[1]
        L2 = math.hypot(e2x, e2y) or 1.0
        e2x, e2y = e2x / L2, e2y / L2
        if ex * e2y - ey * e2x < 0:  # convex (right) turn → fill arc on the outside
            n2x, n2y = e2y, -e2x
            a0, a1 = math.atan2(ny, nx), math.atan2(n2y, n2x)
            d = a1 - a0
            while d <= -math.pi:
                d += 2 * math.pi
            while d > math.pi:
                d -= 2 * math.pi
            for s in range(1, arc_n):
                t = a0 + d * s / arc_n
                rail.append((b[0] + R * math.cos(t), b[1] + R * math.sin(t)))
    return rail


def nearest_on(rail, p):
    bi, bd = 0, 1e18
    for i, q in enumerate(rail):
        d = (q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2
        if d < bd:
            bd, bi = d, i
    return bi, math.sqrt(bd)


def canal(name):
    fj = _find(name, DATA, ".json")
    fc = _find(name, OUT, ".csv")
    if not fj or not fc:
        return None
    sp = json.load(open(fj, encoding="utf-8-sig"))["section_points"]
    cs = sorted(
        float(x)
        for x in json.load(open(fj, encoding="utf-8-sig")).get("callout_stations", [])
    )
    man = {}
    for r in csv.DictReader(open(fc, encoding="utf-8-sig"), delimiter=";"):
        try:
            man[(r["sec_key"], int(r["sec_idx"]))] = (
                float(r["pos1x"]),
                float(r["pos1y"]),
            )
        except (ValueError, TypeError):
            continue
    keys = sorted(sp.keys(), key=lambda k: float(k))
    loop = [sp[k][8][:2] for k in keys] + [
        sp[k][5][:2] for k in reversed(keys)
    ]  # P7 + P4
    pts = []  # (sec_key, idx, x, y, station)
    for sta in cs:
        k = f"{sta:.3f}"
        if k in sp:
            pts.append((k, 7, sp[k][7][0], sp[k][7][1], sta))
            pts.append((k, 6, sp[k][6][0], sp[k][6][1], sta))
    return loop, pts, man


def evaluate(name, R, fan_gap=2.7):
    data = canal(name)
    if not data:
        return None
    loop, pts, man = data
    rail = outward_rail(loop, R)
    # rail arc-length
    slen = [0.0]
    for i in range(1, len(rail)):
        slen.append(
            slen[-1]
            + math.hypot(rail[i][0] - rail[i - 1][0], rail[i][1] - rail[i - 1][1])
        )
    recs = []  # (key, idx, point, rail_index, arclen)
    for k, idx, x, y, sta in pts:
        ri, _ = nearest_on(rail, (x, y))
        recs.append([k, idx, (x, y), ri, slen[ri]])
    # fan along the rail arc-length so projections don't crowd
    order = sorted(range(len(recs)), key=lambda i: recs[i][4])
    fan = layout._spread_var([recs[i][4] for i in order], [fan_gap] * (len(order) - 1))
    diffs = []
    for pos, i in enumerate(order):
        k, idx, p, ri, _ = recs[i]
        # walk rail to the fanned arc-length
        target = fan[pos]
        j = min(range(len(slen)), key=lambda t: abs(slen[t] - target))
        gx, gy = rail[j]
        p1 = (gx - p[0], gy - p[1])
        if (k, idx) in man:
            diffs.append(math.hypot(p1[0] - man[(k, idx)][0], p1[1] - man[(k, idx)][1]))
    return st.median(diffs), sum(diffs) / len(diffs), max(diffs), len(diffs)


def main():
    for R in (4.0, 5.0, 6.0, 6.8, 7.5):
        print(f"--- R={R} ---")
        for name in CANALS:
            r = evaluate(name, R)
            if r:
                print(
                    f"  {name:9} med={r[0]:.2f} mean={r[1]:.2f} max={r[2]:.2f} n={r[3]}"
                )


if __name__ == "__main__":
    main()
