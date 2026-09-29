"""Offline calibration harness for the callout shelf placement.

Runs the real draw_gabion_view.layout.plan_shelves on each canal's section_points
and compares the resulting Pos1X/Pos1Y against the user's manual layout (the per-canal
xlsx dumped from the drawing). Sweeps the ShelfCfg knobs to minimise the median
shelf-position difference. No Civil 3D needed.

Run:  python tests/draw_gabion_view/compare_shelves.py
"""

from __future__ import annotations

import glob
import json
import math
import os
import statistics as st
import sys

import openpyxl

_PKG = r"C:\Arhyz\automation\scripts\draw_gabion_view"
sys.path.insert(0, _PKG)
import layout  # noqa: E402

OUT = r"C:\Arhyz\automation\scripts\debug\dump_callout_blocks\out"
DATA = r"C:\arhyz_s2_data\data\canals"

_CYR, _LAT = "АВЕКМНОРСТХ", "ABEKMHOPCTX"
_TR = {ord(a): b for a, b in zip(_CYR, _LAT)}
_TR.update({ord(a.lower()): b.lower() for a, b in zip(_CYR, _LAT)})


def _norm(s):
    return "".join(c for c in s.translate(_TR).lower() if c.isalnum())


_DJS = {
    _norm(os.path.basename(x)[:-5]): x for x in glob.glob(os.path.join(DATA, "*.json"))
}


def near(a, pool, t=0.12):
    return any(abs(a - b) <= t for b in pool)


def load_canal(xlsx):
    """Return (stations, manual) for one canal.

    stations: plan_shelves input list. manual: {(sec_key, idx): (pos1x, pos1y)}.
    """
    name = os.path.basename(xlsx)[:-5]
    d = json.load(open(_DJS[_norm(name)], encoding="utf-8-sig"))
    sp = d["section_points"]
    cs = sorted(float(x) for x in d.get("callout_stations", []))
    izl = [float(x) for x in d.get("pvi_stations", [])]
    izl += [float(p["station"]) for p in d.get("plan_pis", [])]

    stations, keys = [], []
    for sta in cs:
        k = f"{sta:.3f}"
        if k not in sp:
            continue
        pts = sp[k]
        ax = (pts[7][0] + pts[6][0]) / 2.0
        ay = (pts[7][1] + pts[6][1]) / 2.0
        dx, dy = pts[6][0] - pts[7][0], pts[6][1] - pts[7][1]  # P6 -> P5
        mag = math.hypot(dx, dy) or 1.0
        ux, uy = dx / mag, dy / mag
        proj = [(p[0] - ax) * ux + (p[1] - ay) * uy for p in pts]
        stations.append(
            {
                "p7": (pts[7][0], pts[7][1]),
                "p6": (pts[6][0], pts[6][1]),
                "u": (ux, uy),
                "a": (ax, ay),
                "ext_plus": max(proj),
                "ext_minus": max(-q for q in proj),
                "t": float(sta),
                "izlom": near(sta, izl),
            }
        )
        keys.append(k)

    ws = openpyxl.load_workbook(xlsx).active
    rows = list(ws.iter_rows(values_only=True))
    hdr = rows[0]
    manual = {}
    for r in rows[1:]:
        row = dict(zip(hdr, r))
        try:
            manual[(str(row["sec_key"]), int(row["sec_idx"]))] = (
                float(row["pos1x"]),
                float(row["pos1y"]),
            )
        except (ValueError, TypeError):
            continue
    return name, stations, keys, manual


def evaluate(cfg, canals):
    diffs, overl_tot, drop_script = [], 0, 0
    up = down = horiz = 0
    for _name, stations, keys, manual in canals:
        placed = layout.plan_shelves(stations, cfg)
        left, right = [], []
        for k, s, pl in zip(keys, stations, placed):
            got = {idx for idx, *_ in pl}
            for idx in (7, 6):
                if idx not in got and manual.get((k, idx)) is not None:
                    drop_script += 1
            for idx, flip, p1x, p1y in pl:
                pt = s["p7"] if idx == 7 else s["p6"]
                (left if flip == 0.0 else right).append((pt[0] + p1x, pt[1] + p1y))
                if p1y > 0.5:
                    up += 1
                elif p1y < -0.5:
                    down += 1
                else:
                    horiz += 1
                man = manual.get((k, idx))
                if man:
                    diffs.append(math.hypot(p1x - man[0], p1y - man[1]))
        for col in (left, right):
            for i in range(len(col)):
                for j in range(i + 1, len(col)):
                    if (
                        abs(col[i][0] - col[j][0]) < cfg.w
                        and abs(col[i][1] - col[j][1]) < cfg.h
                    ):
                        overl_tot += 1
    tot = up + down + horiz or 1
    return {
        "median": st.median(diffs) if diffs else 999,
        "overlaps": overl_tot,
        "drop_script_vs_user_kept": drop_script,
        "up%": round(100 * up / tot),
        "horiz%": round(100 * horiz / tot),
    }


def main():
    canals = [load_canal(x) for x in sorted(glob.glob(os.path.join(OUT, "*.xlsx")))]

    print(
        "=== sweep gap / fan_gap (median diff to manual; manual up%≈42, horiz%≈9) ==="
    )
    best = None
    for gap in (4.0, 5.0, 6.0):
        for fg in (2.5, 2.7, 3.0, 3.5):
            cfg = layout.ShelfCfg(gap=gap, fan_gap=fg)
            r = evaluate(cfg, canals)
            tag = f"gap={gap} fan_gap={fg}"
            print(
                f" {tag:22} median={r['median']:.2f} overlaps={r['overlaps']} "
                f"bad_drops={r['drop_script_vs_user_kept']} up%={r['up%']} horiz%={r['horiz%']}"
            )
            score = (r["overlaps"], r["drop_script_vs_user_kept"], r["median"])
            if best is None or score < best[0]:
                best = (score, tag, cfg)

    print(f"\nBEST: {best[1]}")
    print("\n=== per-canal at best cfg ===")
    for name, stations, keys, manual in canals:
        r = evaluate(best[2], [(name, stations, keys, manual)])
        print(
            f" {name:9} median={r['median']:.2f} overlaps={r['overlaps']} "
            f"bad_drops={r['drop_script_vs_user_kept']}"
        )


if __name__ == "__main__":
    main()
