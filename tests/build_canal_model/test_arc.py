"""Tests for virtual-arc geometry: compute_virtual_arc and arc_pt_dir.

A "virtual arc" replaces a sharp plan PI with a circular arc of radius R,
tangent to both incoming and outgoing alignment arms.
"""

from __future__ import annotations

import math

import pytest

from build_canal_model.geometry import arc_pt_dir, compute_virtual_arc
from helpers import MockAlignment


@pytest.fixture
def right_turn_90():
    """90-degree right turn (phi = -pi/2), R = 1.0 m, PI at sta = 10.0."""
    align = MockAlignment(ang_in=0.0, ang_out=-math.pi / 2, pi_sta=10.0)
    return compute_virtual_arc(pi_sta=10.0, R=1.0, align_w=align, eps=0.3)


class TestComputeVirtualArc:
    """compute_virtual_arc derives the key arc parameters from alignment tangent angles."""

    def test_deflection_angle(self, right_turn_90) -> None:
        assert right_turn_90["phi"] == pytest.approx(-math.pi / 2)

    def test_tangent_length(self, right_turn_90) -> None:
        """L = R * tan(|phi| / 2); for a 90-degree turn this equals R."""
        assert right_turn_90["L"] == pytest.approx(1.0)

    def test_pc_pt_stations(self, right_turn_90) -> None:
        assert right_turn_90["pc_sta"] == pytest.approx(9.0)
        assert right_turn_90["pt_sta"] == pytest.approx(11.0)

    def test_center_equidistant_from_pc_and_pt(self, right_turn_90) -> None:
        """Arc center must be exactly R away from both PC and PT."""
        cx, cy = right_turn_90["center"]
        pc = (9.0, 0.0)
        pt = (10.0, -1.0)
        assert math.hypot(cx - pc[0], cy - pc[1]) == pytest.approx(1.0, abs=1e-6)
        assert math.hypot(cx - pt[0], cy - pt[1]) == pytest.approx(1.0, abs=1e-6)


class TestArcPtDir:
    """arc_pt_dir returns the XY position and unit tangent at any station along the arc."""

    def test_endpoint_position(self, right_turn_90) -> None:
        """At pt_sta the arc must end exactly on the PT point."""
        x, y, _, _ = arc_pt_dir(right_turn_90, right_turn_90["pt_sta"])
        assert x == pytest.approx(10.0, abs=1e-6)
        assert y == pytest.approx(-1.0, abs=1e-6)

    def test_tangent_at_endpoint_equals_ang_out(self, right_turn_90) -> None:
        """Tangent direction at pt_sta must equal ang_out = -pi/2 (due south)."""
        _, _, ax, ay = arc_pt_dir(right_turn_90, right_turn_90["pt_sta"])
        assert ax == pytest.approx(math.cos(-math.pi / 2), abs=1e-6)
        assert ay == pytest.approx(math.sin(-math.pi / 2), abs=1e-6)

    def test_tangent_is_unit_vector(self, right_turn_90) -> None:
        """Tangent must be a unit vector at any point on the arc."""
        for sta in (9.0, 9.5, 10.0, 10.5, 11.0):
            _, _, ax, ay = arc_pt_dir(right_turn_90, sta)
            assert math.hypot(ax, ay) == pytest.approx(1.0, abs=1e-6), f"sta={sta}"
