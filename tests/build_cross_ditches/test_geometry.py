"""Tests for cross-ditch break detection (build_cross_ditches.geometry).

Each ditch ends at the first slope break (бровка) walking out from the axis on
its own transverse surface cross-profile: the first node where the profile slope
jumps by more than the threshold. These tests lock that pure detector,
independent of the Civil 3D surface sampling.
"""

from __future__ import annotations

import math

import pytest

from build_cross_ditches.geometry import (
    classify_start_side,
    consistent_neighbour_sign,
    first_slope_break,
    line_intersect_s,
    outward_scarp,
    pick_theta,
    rotate,
)


class TestFirstSlopeBreak:
    """first_slope_break finds the first node whose slope change exceeds threshold."""

    def test_flat_then_steep(self) -> None:
        # flat floor (slope 0) then a steep rise; break = last floor node (t=2)
        elevs = [0.0, 0.0, 0.0, 1.0, 2.0]  # slopes 0,0,1,1 → jump at node 2
        assert first_slope_break(elevs, 1.0, 0.15) == 2

    def test_immediate_break(self) -> None:
        # gentle then steep; jump is at node 2 (start of the steep segment)
        elevs = [0.0, 0.05, 0.10, 1.10]  # slopes .05,.05,1.0 → jump at node 2
        assert first_slope_break(elevs, 1.0, 0.15) == 2

    def test_no_break_constant_slope(self) -> None:
        # a perfectly straight ramp never breaks
        elevs = [0.0, 1.0, 2.0, 3.0, 4.0]
        assert first_slope_break(elevs, 1.0, 0.15) is None

    def test_no_break_under_threshold(self) -> None:
        # slope drifts but each step change stays below threshold
        elevs = [0.0, 0.1, 0.25, 0.45, 0.70]  # Δslope = .05,.05,.05 < .15
        assert first_slope_break(elevs, 1.0, 0.15) is None

    def test_returns_first_of_several(self) -> None:
        # slopes 0,.5,0,1.5 → first jump at node 1, a later one at node 2
        elevs = [0.0, 0.0, 0.5, 0.5, 2.0]
        assert first_slope_break(elevs, 1.0, 0.15) == 1

    def test_step_scales_slope(self) -> None:
        # same elevations, larger sample step → smaller slopes → no break
        elevs = [0.0, 0.0, 0.0, 1.0]
        assert first_slope_break(elevs, 1.0, 0.5) == 2  # slope jump 0→1 > .5
        assert first_slope_break(elevs, 10.0, 0.5) is None  # slope jump 0→.1 < .5

    def test_too_few_samples(self) -> None:
        assert first_slope_break([], 1.0, 0.15) is None
        assert first_slope_break([0.0], 1.0, 0.15) is None
        assert first_slope_break([0.0, 1.0], 1.0, 0.15) is None

    def test_downward_break_detected(self) -> None:
        # a drop is a break too (abs slope change); last flat node is t=2
        elevs = [0.0, 0.0, 0.0, -1.0, -2.0]
        assert first_slope_break(elevs, 1.0, 0.15) == 2

    def test_threshold_boundary_not_exceeded(self) -> None:
        # Δslope exactly == threshold does not count (strict >)
        elevs = [0.0, 0.0, 0.15]  # slopes 0, .15 → Δ = .15, not > .15
        assert first_slope_break(elevs, 1.0, 0.15) is None


class TestRotate:
    """rotate spins a vector CCW by an angle in radians."""

    def test_quarter_turn(self) -> None:
        x, y = rotate(1.0, 0.0, math.pi / 2)
        assert x == pytest.approx(0.0, abs=1e-9)
        assert y == pytest.approx(1.0)

    def test_zero_angle_identity(self) -> None:
        assert rotate(0.3, -0.7, 0.0) == pytest.approx((0.3, -0.7))

    def test_preserves_length(self) -> None:
        x, y = rotate(3.0, 4.0, 0.9)
        assert math.hypot(x, y) == pytest.approx(5.0)

    def test_negative_angle(self) -> None:
        x, y = rotate(0.0, 1.0, -math.pi / 2)
        assert x == pytest.approx(1.0)
        assert y == pytest.approx(0.0, abs=1e-9)


class TestPickTheta:
    """pick_theta selects the smallest skew whose grade is in band, else nearest."""

    def test_first_in_band(self) -> None:
        # θ ascending; grade grows with θ; first one ≥ 0.02 and ≤ 0.05 wins
        cands = [(0.0, 0.0), (1.0, 0.01), (2.0, 0.03), (3.0, 0.06)]
        assert pick_theta(cands, 0.02, 0.05) == (2.0, 0.03)

    def test_skips_below_band(self) -> None:
        cands = [(0.0, 0.005), (1.0, 0.045)]
        assert pick_theta(cands, 0.02, 0.05) == (1.0, 0.045)

    def test_none_in_band_returns_nearest(self) -> None:
        # all below band → closest to lower edge (the largest grade)
        cands = [(0.0, 0.005), (1.0, 0.012), (2.0, 0.018)]
        assert pick_theta(cands, 0.02, 0.05) == (2.0, 0.018)

    def test_none_in_band_overshoot(self) -> None:
        # all above band → closest to upper edge (the smallest grade)
        cands = [(5.0, 0.08), (6.0, 0.06), (7.0, 0.12)]
        assert pick_theta(cands, 0.02, 0.05) == (6.0, 0.06)

    def test_empty(self) -> None:
        assert pick_theta([], 0.02, 0.05) is None

    def test_exact_band_edges_in(self) -> None:
        cands = [(0.0, 0.02)]
        assert pick_theta(cands, 0.02, 0.05) == (0.0, 0.02)


class TestOutwardScarp:
    """outward_scarp sums the rise along the steep откос starting at the бровка."""

    def test_cut_face_climbs(self) -> None:
        # ~45° откос (slope 1) for 3 steps then flat → выемка, +3
        elevs = [0.0, 0.0, 1.0, 2.0, 3.0, 3.0, 3.0]  # k=1, step=1, steep=0.3
        assert outward_scarp(elevs, 1, 1.0, 0.3) == pytest.approx(3.0)

    def test_fill_face_drops(self) -> None:
        elevs = [0.0, 0.0, -1.0, -2.0, -3.0, -3.0]  # k=1 → −3 over the face
        assert outward_scarp(elevs, 1, 1.0, 0.3) == pytest.approx(-3.0)

    def test_short_steep_face_not_overshot(self) -> None:
        # short откос (1 step up), then terrain DROPS beyond the crest; a fixed
        # window would net ~0 / negative, but following the face gives +1 (cut)
        elevs = [0.0, 0.0, 1.0, 0.5, 0.0, -0.5]  # k=1: up 1, then gentle/down
        assert outward_scarp(elevs, 1, 1.0, 0.3) == pytest.approx(1.0)

    def test_long_shallow_face(self) -> None:
        # 0.4 slope (~22°) counts as a face at steep=0.3; sums the whole run
        elevs = [0.0, 0.0, 0.4, 0.8, 1.2, 1.2]  # k=1 → +1.2
        assert outward_scarp(elevs, 1, 1.0, 0.3) == pytest.approx(1.2)

    def test_no_scarp_at_break(self) -> None:
        # gentle right at the бровка (below steep) → no откос there
        elevs = [0.0, 0.0, 0.1, 0.2]  # slope 0.1 < 0.3
        assert outward_scarp(elevs, 1, 1.0, 0.3) is None

    def test_steep_scaled_by_step(self) -> None:
        # same elevations, larger step lowers the slope below steep → no face
        elevs = [0.0, 0.0, 1.0, 2.0]
        assert outward_scarp(elevs, 1, 1.0, 0.3) == pytest.approx(2.0)
        assert outward_scarp(elevs, 1, 10.0, 0.3) is None  # slope 0.1 < 0.3


class TestClassifyStartSide:
    """classify_start_side picks the cut bank (откос вверх) as the ditch start."""

    def test_a_cut_b_fill(self) -> None:
        # side a climbs (выемка) → start; side b falls (насыпь) → end
        assert classify_start_side(0.5, 100.0, -0.4, 99.0) == "a"

    def test_b_cut_a_fill(self) -> None:
        assert classify_start_side(-0.4, 99.0, 0.5, 100.0) == "b"

    def test_both_cut_fallback_to_higher(self) -> None:
        # no насыпь — both banks climb; higher bank is the start
        assert classify_start_side(0.5, 101.0, 0.6, 102.0) == "b"
        assert classify_start_side(0.5, 103.0, 0.6, 102.0) == "a"

    def test_both_fill_fallback_to_higher(self) -> None:
        assert classify_start_side(-0.5, 100.0, -0.4, 99.0) == "a"

    def test_cut_beats_height_when_other_is_edge(self) -> None:
        # НК sta 280 (#15): one side is a clear cut (+5.91), the other is edge
        # (None), AND the cut bank is LOWER. Cut still wins → it is the start.
        assert classify_start_side(None, 2829.32, 5.91, 2828.37) == "b"
        assert classify_start_side(5.91, 2828.37, None, 2829.32) == "a"

    def test_cut_beats_height_when_cut_is_lower(self) -> None:
        # подошва выемки below бровка насыпи: cut side is lower but still start
        assert classify_start_side(5.0, 100.0, -4.0, 101.0) == "a"

    def test_single_fill_makes_other_the_start(self) -> None:
        # one clear fill (насыпь = end), other side unknown → other is start
        assert classify_start_side(None, 98.0, -3.19, 99.0) == "a"

    def test_both_unknown_fallback_to_higher(self) -> None:
        assert classify_start_side(None, 100.0, None, 101.0) == "b"

    def test_flat_within_eps_fallback(self) -> None:
        # both slopes within ±eps (flat) → higher bank
        assert classify_start_side(0.01, 100.0, -0.02, 100.5) == "b"


class TestLineIntersectS:
    """line_intersect_s crosses two lines in the (s, Z) profile plane."""

    def test_basic_cross(self) -> None:
        # A: through (0,0) rising +1; B: through (2,0) falling −1 → meet at (1,1)
        assert line_intersect_s(0.0, 0.0, 1.0, 2.0, 0.0, -1.0) == pytest.approx(
            (1.0, 1.0)
        )

    def test_parallel_returns_none(self) -> None:
        assert line_intersect_s(0.0, 0.0, -0.03, 5.0, 1.0, -0.03) is None

    def test_ditch_meets_connector(self) -> None:
        # gentle ditch (slope −0.03 from s=0,Z=10) meets a steep connector
        # (slope −1.0 through s=20,Z=0) — connector_top is the crossing
        s, z = line_intersect_s(0.0, 10.0, -0.03, 20.0, 0.0, -1.0)
        # on ditch line: Z = 10 − 0.03·s
        assert z == pytest.approx(10.0 - 0.03 * s)
        # on connector line: Z = 0 − 1.0·(s − 20)
        assert z == pytest.approx(-(s - 20.0))


class TestConsistentNeighbourSign:
    """consistent_neighbour_sign returns the shared sign only if all neighbours agree."""

    def test_all_agree(self) -> None:
        assert consistent_neighbour_sign([1.0, 1.0, 1.0, 1.0]) == 1.0
        assert consistent_neighbour_sign([-1.0, -1.0, -1.0, -1.0]) == -1.0

    def test_disagree_returns_none(self) -> None:
        assert consistent_neighbour_sign([1.0, 1.0, -1.0, 1.0]) is None

    def test_ignores_missing(self) -> None:
        # None entries (edge of row / skipped ditches) are ignored
        assert consistent_neighbour_sign([None, 1.0, 1.0, None]) == 1.0

    def test_all_missing_returns_none(self) -> None:
        assert consistent_neighbour_sign([None, None, None, None]) is None

    def test_single_neighbour(self) -> None:
        assert consistent_neighbour_sign([None, -1.0, None, None]) == -1.0
