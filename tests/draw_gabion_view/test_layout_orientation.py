"""plan_shelves must split the P6/P5 callouts onto opposite sides of the section at
any plan bearing. Before the transverse-frame rewrite a near-horizontal canal decided
the side by world-X and collapsed both callouts to one side (НК-2B-1 bug)."""

from __future__ import annotations

from draw_gabion_view import layout
from draw_gabion_view.layout import ShelfCfg


def _station(u, a, ext=2.0, t=0.0):
    """One callout station: P6 on -u, P5 on +u, gabion reaching `ext` each side."""
    ux, uy = u
    ax, ay = a
    return {
        "p7": (ax - ext * ux, ay - ext * uy),  # idx 7 = P6 (-u side)
        "p6": (ax + ext * ux, ay + ext * uy),  # idx 6 = P5 (+u side)
        "u": (ux, uy),
        "a": (ax, ay),
        "ext_plus": ext,
        "ext_minus": ext,
        "t": t,
        "izlom": True,  # mandatory point, never thinned out
    }


def _placed_by_idx(out_for_station):
    return {idx: (flip, p1x, p1y) for idx, flip, p1x, p1y in out_for_station}


def test_vertical_canal_splits_in_x():
    # transverse u = world +X  -> classic left/right layout, leaders ~horizontal
    out = layout.plan_shelves([_station((1.0, 0.0), (0.0, 0.0))], ShelfCfg())
    by_idx = _placed_by_idx(out[0])
    assert set(by_idx) == {7, 6}
    p6_flip, p6_x, p6_y = by_idx[7]
    p5_flip, p5_x, p5_y = by_idx[6]
    assert p6_x < 0 < p5_x  # P6 pushed left, P5 right (opposite X sides)
    assert abs(p6_y) < 1e-6 and abs(p5_y) < 1e-6  # no vertical drift for a lone station
    assert (p6_flip, p5_flip) == (0.0, 1.0)


def test_horizontal_canal_splits_in_y():
    # transverse u = world +Y  -> the 2B-1 case: callouts must go up/down, not collapse
    out = layout.plan_shelves([_station((0.0, 1.0), (0.0, 0.0))], ShelfCfg())
    by_idx = _placed_by_idx(out[0])
    assert set(by_idx) == {7, 6}
    _, p6_x, p6_y = by_idx[7]
    _, p5_x, p5_y = by_idx[6]
    assert p6_y < 0 < p5_y  # opposite Y sides (the fix) — not both one side
    assert abs(p6_x) < 1e-6 and abs(p5_x) < 1e-6  # no transverse drift in world X


def test_diagonal_canal_keeps_sides_opposite():
    # 45deg: continuous frame, no threshold jump — sides stay opposite along u
    import math

    inv = 1.0 / math.sqrt(2.0)
    out = layout.plan_shelves([_station((inv, inv), (0.0, 0.0))], ShelfCfg())
    by_idx = _placed_by_idx(out[0])
    _, p6_x, p6_y = by_idx[7]
    _, p5_x, p5_y = by_idx[6]
    # projection of each shelf offset onto u must have opposite sign
    assert (p6_x * inv + p6_y * inv) < 0 < (p5_x * inv + p5_y * inv)


def _seg_cross(a, b, c, d):
    """Proper intersection of open segments ab, cd (shared endpoints ignored)."""

    def ccw(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    return ((ccw(c, d, a) > 0) != (ccw(c, d, b) > 0)) and (
        (ccw(a, b, c) > 0) != (ccw(a, b, d) > 0)
    )


def _norm(s):
    cyr, lat = "АВЕКМНОРСТХ", "ABEKMHOPCTX"
    tr = {ord(a): b for a, b in zip(cyr, lat)}
    tr.update({ord(a.lower()): b.lower() for a, b in zip(cyr, lat)})
    return "".join(c for c in s.translate(tr).lower() if c.isalnum())


def _real_canal_stations(name):
    """Build plan_shelves input from a real exported canal JSON, as builder does.

    Returns None if the data file is not present (keeps the test optional in CI)."""
    import glob
    import json
    import math
    import os

    data_dir = r"C:\arhyz_s2_data\data\canals"
    if not os.path.isdir(data_dir):
        return None
    target = _norm(name)
    hit = next(
        (
            p
            for p in glob.glob(os.path.join(data_dir, "*.json"))
            if _norm(os.path.basename(p)[:-5]) == target
        ),
        None,
    )
    if hit is None:
        return None
    d = json.load(open(hit, encoding="utf-8-sig"))
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
    return stations


def _side_labels(stations, placed):
    """Per flip side: list of (point_xy, label_xy) for every placed callout."""
    sides: dict[float, list] = {0.0: [], 1.0: []}
    for si, pl in enumerate(placed):
        for idx, flip, p1x, p1y in pl:
            pt = stations[si]["p7"] if idx == 7 else stations[si]["p6"]
            sides[flip].append((pt, (pt[0] + p1x, pt[1] + p1y)))
    return sides


def test_no_leader_crossings_on_real_bent_canal():
    # НК-2B-1 is near-horizontal and bends — the canal that exposed the crossing bug.
    import pytest

    stations = _real_canal_stations("НК-2B-1")
    if not stations:
        pytest.skip("НК-2B-1 export not available")
    for recs in _side_labels(
        stations, layout.plan_shelves(stations, ShelfCfg(w=1.6, h=0.8))
    ).values():
        for i in range(len(recs)):
            for j in range(i + 1, len(recs)):
                assert not _seg_cross(recs[i][0], recs[i][1], recs[j][0], recs[j][1]), (
                    "callout leaders cross on НК-2B-1"
                )


def test_no_shelf_overlaps_on_real_bent_canal():
    # The sharp bends of НК-2B-1 are where shelves used to overlap; the solver must
    # spread them along the legs so no two axis-aligned label boxes (w×h) collide.
    import pytest

    stations = _real_canal_stations("НК-2B-1")
    if not stations:
        pytest.skip("НК-2B-1 export not available")
    w, h = 1.6, 0.8
    for recs in _side_labels(
        stations, layout.plan_shelves(stations, ShelfCfg(w=w, h=h))
    ).values():
        for i in range(len(recs)):
            for j in range(i + 1, len(recs)):
                a, b = recs[i][1], recs[j][1]
                assert not (abs(a[0] - b[0]) < w and abs(a[1] - b[1]) < h), (
                    "callout shelves overlap on НК-2B-1"
                )
