"""Tests for loft sub-station splitting and the plan-PI miter pullback.

Regression coverage for three field bugs:
- НК-1E-2: a 0.109 m sliver gabion lofted between a PVI and a plan PI 0.109 m
  apart (station-level fix lives in canal_builder; here we lock the dobornie
  split invariants the fix relies on).
- НК-3А-1: the miter wedge span before a 39.37° PI (0.513 m) was shorter than
  the bisector pullback (~0.80 m), the loft self-intersected and AutoCAD
  produced a degenerate 0.017 m³ solid instead of the wedge.
- НК-1А-3: a full 2 m step right after a 39.24° type-6 PI had a 3.21 m outer
  3D edge (2 m + pullback 1.23 m·mag) — every longitudinal gabion edge must
  stay ≤ loft_step, so PI-adjacent corner pieces are capped from above too.
"""

from __future__ import annotations

import math

import pytest

from build_canal_model.config import GABION
from build_canal_model.section_params import (
    corner_piece_len,
    loft_substations,
    miter_pullback,
    pi_reach_at,
)
from helpers import MockAlignment, MockProfile

# one gabion segment covering the whole test span, type-5-like params:
# top_w = bw + 2*(m*d + t*sqrt(1+m^2)) = 2.0 + 2*(1.0*0.8 + 0.3*sqrt(2)) ≈ 4.449
SEGMENTS = [{"from": "ПК0+00.00", "to": "ПК2+00.00", "type": "5"}]
CFG = {"5": {"bottom_w": 2.0, "d": 0.8, "m": 1.0, "t": 0.3}}
TOP_W = 2.0 + 2.0 * (1.0 * 0.8 + 0.3 * math.sqrt(2.0))
STA_END = 200.0

LEVEL = MockProfile(slope=0.0)


def _pullback(deg: float) -> float:
    return 0.5 * TOP_W * math.tan(math.radians(deg / 2.0))


class TestLoftSubstations:
    """loft_substations splits a loft span into ~loft_step pieces with dobornie tail."""

    def test_regular_split(self) -> None:
        assert loft_substations(0.0, 10.0, LEVEL.slope_at) == pytest.approx(
            [0.0, 2.0, 4.0, 6.0, 8.0, 10.0]
        )

    def test_tail_merge_dobornie(self) -> None:
        """Доборные ГСИ rule: 6.4 m → 2, 2, 1.2, 1.2."""
        assert loft_substations(0.0, 6.4, LEVEL.slope_at) == pytest.approx(
            [0.0, 2.0, 4.0, 5.2, 6.4]
        )

    def test_tail_at_exact_min_unit_kept(self) -> None:
        """A 0.5 m remainder is a valid dobornie unit — no merge."""
        assert loft_substations(0.0, 4.5, LEVEL.slope_at) == pytest.approx(
            [0.0, 2.0, 4.0, 4.5]
        )

    def test_short_span_returned_as_is(self) -> None:
        """A 2-station span can't be merged further — station-level fix handles it."""
        assert loft_substations(0.0, 0.3, LEVEL.slope_at) == pytest.approx([0.0, 0.3])

    def test_slope_shortens_plan_step(self) -> None:
        """Along-slope length stays loft_step: plan step = loft_step / sqrt(1+slope²)."""
        slope = 0.75  # mag = 1.25
        sub = loft_substations(0.0, 8.0, MockProfile(slope).slope_at)
        assert sub[1] - sub[0] == pytest.approx(GABION.loft_step / 1.25)

    def test_spans_cover_input_exactly(self) -> None:
        sub = loft_substations(3.7, 17.21, LEVEL.slope_at, reach_tail=0.7)
        assert sub[0] == pytest.approx(3.7)
        assert sub[-1] == pytest.approx(17.21)
        assert all(b > a for a, b in zip(sub, sub[1:]))


class TestCornerPieceReservation:
    """PI-adjacent corner pieces: ≥ pullback+margin (no self-intersection) and
    outer 3D edge (len + pullback)·mag ≤ loft_step."""

    def test_tail_corner_piece_clears_pullback(self) -> None:
        """НК-3А-1 shape: pullback 0.787 → corner piece in [0.887, 1.213]."""
        pb = _pullback(39.37)
        sub = loft_substations(0.0, 12.513, LEVEL.slope_at, reach_tail=pb)
        piece = sub[-1] - sub[-2]
        assert piece >= pb + GABION.miter_margin - 1e-9
        assert piece + pb <= GABION.loft_step + 1e-9  # outer edge ≤ 2 m

    def test_head_corner_piece_capped(self) -> None:
        """НК-1А-3 shape: full step after the PI must shrink so outer ≤ loft_step."""
        pb = _pullback(39.37)
        sub = loft_substations(0.0, 12.513, LEVEL.slope_at, reach_head=pb)
        piece = sub[1] - sub[0]
        assert piece + pb <= GABION.loft_step + 1e-9
        assert piece >= pb + GABION.miter_margin - 1e-9

    def test_outer_edge_cap_accounts_for_slope(self) -> None:
        """Worst 3D edge ≈ piece·mag + reach — steeper slope shrinks the plan piece."""
        pb = _pullback(30.0)
        slope = 0.75  # mag = 1.25
        sub = loft_substations(0.0, 20.0, MockProfile(slope).slope_at, reach_tail=pb)
        piece = sub[-1] - sub[-2]
        assert piece * 1.25 + pb <= GABION.loft_step + 1e-9

    def test_no_pullback_no_reservation(self) -> None:
        assert loft_substations(0.0, 10.0, LEVEL.slope_at, 0.0, 0.0) == pytest.approx(
            [0.0, 2.0, 4.0, 6.0, 8.0, 10.0]
        )

    def test_both_ends_reserved(self) -> None:
        pb = _pullback(30.0)
        sub = loft_substations(0.0, 15.0, LEVEL.slope_at, reach_head=pb, reach_tail=pb)
        for piece in (sub[1] - sub[0], sub[-1] - sub[-2]):
            assert piece + pb <= GABION.loft_step + 1e-9
            assert piece >= pb + GABION.miter_margin - 1e-9
        assert all(
            b - a >= GABION.min_unit - 1e-9 for a, b in zip(sub[1:-1], sub[2:-1])
        )

    def test_span_too_short_to_reserve(self) -> None:
        """Reservation is skipped when the remainder would drop below min_unit."""
        pb = _pullback(39.37)
        sub = loft_substations(0.0, 1.5, LEVEL.slope_at, reach_tail=pb)
        assert sub == pytest.approx([0.0, 1.5])


class TestCornerPieceLen:
    """corner_piece_len picks the longest piece with piece·mag + reach ≤ loft_step − safety."""

    def test_prefers_cap(self) -> None:
        pb = 0.5
        assert corner_piece_len(pb, 1.0) == pytest.approx(
            GABION.loft_step - GABION.edge_safety - pb
        )

    def test_floor_wins_when_window_empty(self) -> None:
        """Type-6 @ 39° (НК-1А-3): pullback 1.23 → window empty → floor.
        Such PIs go to the virtual arc; the floor is a backstop only."""
        pb = 1.23
        assert corner_piece_len(pb, 1.0) == pytest.approx(pb + GABION.miter_margin)


class TestMiterPullback:
    """miter_pullback = half_top_w * tan(deflection/2) at a plan PI."""

    def _pb(self, deg: float) -> float:
        align = MockAlignment(ang_in=0.0, ang_out=math.radians(-deg), pi_sta=100.0)
        return miter_pullback(100.0, align, SEGMENTS, CFG, STA_END, None)

    def test_39_deg_turn(self) -> None:
        """НК-3А-1 PI 133.562: 39.37° on a ~4.45 m wide section → ~0.79 m."""
        assert self._pb(39.37) == pytest.approx(_pullback(39.37))

    def test_zero_deflection(self) -> None:
        assert self._pb(0.0) == pytest.approx(0.0)

    def test_grows_with_angle(self) -> None:
        assert self._pb(40.0) > self._pb(10.0)


class _KinkProfile:
    """Profile with a grade break at kink_sta (slope_in before, slope_out after)."""

    def __init__(self, s_in: float, s_out: float, kink_sta: float) -> None:
        self._s_in, self._s_out, self._kink = s_in, s_out, kink_sta

    def slope_at(self, sta: float) -> float:
        return self._s_in if sta < self._kink else self._s_out


class TestPiReachAt:
    """pi_reach_at = pullback + top-wall lean at a PI, 0.0 elsewhere."""

    _ALIGN = MockAlignment(ang_in=0.0, ang_out=math.radians(-39.37), pi_sta=100.0)

    def _at(self, sta: float, profile=LEVEL) -> float:
        return pi_reach_at(
            sta, [100.0], self._ALIGN, profile.slope_at, SEGMENTS, CFG, STA_END, None
        )

    def test_at_pi_level_profile(self) -> None:
        """No grade break → reach is the pure plan pullback."""
        assert self._at(100.0) == pytest.approx(_pullback(39.37))

    def test_away_from_pi(self) -> None:
        assert self._at(50.0) == pytest.approx(0.0)

    def test_grade_break_adds_top_lean(self) -> None:
        """НК-3А-1 PI 250.307 shape: Δslope on the PI advances top points by
        d·|Δ(slope/mag)| on top of the plan pullback."""
        s_in, s_out = -0.05, -0.49
        lean = 0.8 * abs(
            s_in / math.sqrt(1 + s_in**2) - s_out / math.sqrt(1 + s_out**2)
        )
        got = self._at(100.0, _KinkProfile(s_in, s_out, 100.0))
        assert got == pytest.approx(_pullback(39.37) + lean)
