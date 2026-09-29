"""Check that every longitudinal gabion edge in canal JSON exports is <= max length.

Usage: python automation/tools/check_edge_lengths.py [canal ...]
Without args, checks every JSON in the arhyz_s2_data repo's data/canals/.

For each pair of consecutive section_points stations, the 3D distance between
same-index points is a longitudinal edge of one gabion unit. The standard
GSI basket is 2 m, so any edge materially over loft_step (2 m) is an error
(НК-1А-3: 3.21 m edge after a 39° PI). Trough segments are skipped — troughs
are sliced at 2.99 m by their own rules.
"""

from __future__ import annotations

import json
import math
import os
import sys

CANALS_DIR = r"C:\arhyz_s2_data\data\canals"
MAX_EDGE = 2.0
TOL = 0.02  # numeric slack on top of MAX_EDGE


def gabion_ranges(data: dict) -> list[tuple[float, float]]:
    return [
        (float(s["station_start"]), float(s["station_end"]))
        for s in data.get("segments", [])
        if s.get("kind") != "trough"
    ]


def check_canal(path: str, pi_only: bool = False) -> list[str]:
    data = json.load(open(path, encoding="utf-8"))
    sp = data.get("section_points", {})
    keys = sorted(sp, key=float)
    ranges = gabion_ranges(data)
    pis = [float(p["station"]) for p in data.get("plan_pis", [])]
    issues: list[str] = []
    for k0, k1 in zip(keys, keys[1:]):
        s0, s1 = float(k0), float(k1)
        mid = (s0 + s1) / 2.0
        if not any(a - 0.01 <= mid <= b + 0.01 for a, b in ranges):
            continue
        near_pi = any(abs(s0 - p) < 0.01 or abs(s1 - p) < 0.01 for p in pis)
        if pi_only and not near_pi:
            continue
        p0, p1 = sp[k0], sp[k1]
        worst = max(math.dist(a, b) for a, b in zip(p0, p1))
        if worst > MAX_EDGE + TOL:
            tag = " [PI]" if near_pi else ""
            issues.append(f"  {k0} -> {k1}: max edge {worst:.3f} m{tag}")
    return issues


def main() -> int:
    args = sys.argv[1:]
    pi_only = "--pi-only" in args
    names = [a for a in args if not a.startswith("--")]
    files = (
        [os.path.join(CANALS_DIR, f"{n}.json") for n in names]
        if names
        else [
            os.path.join(CANALS_DIR, f)
            for f in sorted(os.listdir(CANALS_DIR))
            if f.endswith(".json")
        ]
    )
    bad = 0
    for path in files:
        issues = check_canal(path, pi_only=pi_only)
        name = os.path.splitext(os.path.basename(path))[0]
        if issues:
            bad += 1
            print(f"{name}: {len(issues)} edge(s) over {MAX_EDGE} m")
            for line in issues:
                print(line)
    print(f"checked {len(files)} canal(s), {bad} with violations")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
