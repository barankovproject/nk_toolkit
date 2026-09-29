"""Tests for cross-section geometry: slope_uvw, section_pts, trough_section_pts."""

from __future__ import annotations

import math

import pytest

from build_canal_model.geometry import section_pts, slope_uvw, trough_section_pts

_SECTION_BASE = dict(
    cx=0.0,
    cy=0.0,
    cz=0.0,
    rx=1.0,
    ry=0.0,
    ax=1.0,
    ay=0.0,
    slope=0.0,
    bx=0.0,
    by=0.0,
    bz=0.0,
    bottom_w=1.0,
    d=0.5,
    m=1.0,
    t=0.1,
)

TROUGH_TYPE_10 = {
    "outer_w": 1.18,
    "outer_h": 0.88,
    "inner_top_w": 1.06,
    "inner_bot_w": 0.76,
    "bot_wall": 0.10,
    "cover_t": 0.12,
    "chamfer": 0.05,
    "prep_overhang": 0.10,
    "prep_t": 0.10,
}


class TestSlopeUvw:
    """slope_uvw converts a profile slope + cross-axis pair into a unit up-vector.

    The result drives the tilt of the cross-section plane so that cuts remain
    perpendicular to the 3D canal tangent when the profile is not level.
    """

    def test_level_alignment(self) -> None:
        assert slope_uvw(0.0, 1.0, 0.0) == pytest.approx((0.0, 0.0, 1.0))

    def test_always_unit_vector(self) -> None:
        for slope in (-2.0, -1.0, -0.5, 0.5, 1.0, 2.0):
            for rx, ry in ((1.0, 0.0), (0.0, 1.0), (math.cos(0.3), math.sin(0.3))):
                ux, uy, uz = slope_uvw(slope, rx, ry)
                assert math.hypot(ux, uy, uz) == pytest.approx(1.0), (
                    f"slope={slope} rx={rx} ry={ry}"
                )

    def test_uz_equals_1_over_mag(self) -> None:
        slope = 1.0
        _, _, uz = slope_uvw(slope, 1.0, 0.0)
        assert uz == pytest.approx(1.0 / math.sqrt(1.0 + slope**2))


class TestGabionSection:
    """section_pts returns 9 Point3d vertices for one gabion canal cross-section.

    Vertex order: P0–P8 starting at the top-left outer corner, going clockwise
    through the inner profile and back up the right side.
    """

    def _pts(self, **override):
        return section_pts(**{**_SECTION_BASE, **override})

    def test_returns_nine_points(self) -> None:
        assert len(self._pts()) == 9

    def test_lateral_symmetry(self) -> None:
        """With slope=0 the cross-section must be symmetric about the canal centre."""
        pts = self._pts()
        for a, b in ((0, 4), (1, 3), (5, 8), (6, 7)):
            assert pts[a].X == pytest.approx(-pts[b].X), f"P{a}/P{b} not symmetric"
            assert pts[a].Y == pytest.approx(pts[b].Y)
            assert pts[a].Z == pytest.approx(pts[b].Z)

    def test_invert_at_z_zero(self) -> None:
        """P1, P2, P3 sit at the canal invert (z=0) when the profile is level."""
        pts = self._pts()
        for i in (1, 2, 3):
            assert pts[i].Z == pytest.approx(0.0), f"P{i}.Z = {pts[i].Z}"

    def test_top_wall_at_d(self) -> None:
        """P0, P4, P5, P8 sit at z=d (top of the gabion wall)."""
        pts = self._pts()
        for i in (0, 4, 5, 8):
            assert pts[i].Z == pytest.approx(0.5), f"P{i}.Z = {pts[i].Z}"

    def test_slope_tilts_top_wall(self) -> None:
        """A non-zero slope tilts the section plane: top-wall Z shifts relative to the level case."""
        flat = self._pts(slope=0.0)
        sloped = self._pts(slope=1.0)
        assert flat[0].Z != pytest.approx(sloped[0].Z)

    def test_base_offset_shifts_all_points(self) -> None:
        """bx / by / bz translate every point rigidly without changing relative geometry."""
        pts0 = self._pts()
        pts1 = self._pts(bx=1.0, by=2.0, bz=3.0)
        for i in range(9):
            assert pts1[i].X - pts0[i].X == pytest.approx(1.0)
            assert pts1[i].Y - pts0[i].Y == pytest.approx(2.0)
            assert pts1[i].Z - pts0[i].Z == pytest.approx(3.0)


class TestTroughSection:
    """trough_section_pts returns three point lists for one ЛК trough cross-section.

    body (10 pts) — outer trough shell including bottom
    cover (4 pts)  — rectangular lid
    prep (4 pts)   — sand preparation slab beneath the trough
    """

    def _call(self, tp=TROUGH_TYPE_10):
        return trough_section_pts(0.0, 0.0, 0.0, 1.0, 0.0, tp)

    def test_point_counts(self) -> None:
        body, cover, prep = self._call()
        assert len(body) == 10
        assert len(cover) == 4
        assert len(prep) == 4

    def test_cover_above_body_top(self) -> None:
        """Cover top edge must sit above the cover bottom edge."""
        _, cover, _ = self._call()
        assert cover[2].Z > cover[0].Z

    def test_prep_below_body_bottom(self) -> None:
        """Sand preparation slab must be entirely below the trough body."""
        body, _, prep = self._call()
        assert prep[-1].Z < body[-1].Z

    def test_prep_extends_beyond_outer_wall(self) -> None:
        """Prep width = outer_w + 2 * prep_overhang on each side."""
        _, _, prep = self._call()
        expected_hw = TROUGH_TYPE_10["outer_w"] / 2.0 + TROUGH_TYPE_10["prep_overhang"]
        assert prep[1].X == pytest.approx(expected_hw)
        assert prep[0].X == pytest.approx(-expected_hw)

    def test_body_lateral_symmetry(self) -> None:
        """Body points are symmetric about the trough centre (X = 0)."""
        body, _, _ = self._call()
        for a, b in ((0, 7), (1, 6), (2, 5), (3, 4)):
            assert body[a].X == pytest.approx(-body[b].X), (
                f"body[{a}].X={body[a].X}  body[{b}].X={body[b].X}"
            )
