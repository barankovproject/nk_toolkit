"""Tests for export._rib_records: rib station stepping + lateral segment layout."""

from __future__ import annotations

import pytest

from build_canal_model.config import RIBS
from build_canal_model.export import _rib_records
from data import CFG, SEG, WIDENING
from helpers import MockProfile


def _records(
    segments=None,
    widening=None,
    cfg_types=None,
    trough_cfg_types=None,
    sta_end=100.0,
    slope=0.0,
):
    return _rib_records(
        MockProfile(slope),
        segments if segments is not None else [],
        widening,
        cfg_types or {},
        trough_cfg_types or {},
        sta_end,
    )


class TestSegmentRibs:
    """Regular (non-widening) segment ribs span the full bottom width, one per step."""

    def test_full_bottom_width(self) -> None:
        recs = _records(segments=[SEG], cfg_types=CFG, sta_end=20.0)
        assert recs
        for r in recs:
            assert r["laterals"] == [[-1.0, 1.0]]  # half_w = bottom_w / 2

    def test_first_station_offset_half_rib(self) -> None:
        recs = _records(segments=[SEG], cfg_types=CFG, sta_end=20.0)
        assert max(r["station"] for r in recs) == pytest.approx(20.0 - RIBS.size / 2.0)

    def test_step_equals_rib_step_when_level(self) -> None:
        recs = _records(segments=[SEG], cfg_types=CFG, sta_end=20.0)
        stas = sorted(r["station"] for r in recs)
        for i in range(len(stas) - 1):
            assert stas[i + 1] - stas[i] == pytest.approx(RIBS.step)

    def test_ribs_false_skipped(self) -> None:
        seg = {**SEG, "ribs": False}
        assert _records(segments=[seg], cfg_types=CFG, sta_end=20.0) == []

    def test_trough_type_skipped(self) -> None:
        seg = {**SEG, "type": 10}
        recs = _records(
            segments=[seg],
            cfg_types={"10": {"bottom_w": 2.0}},
            trough_cfg_types={"10": {}},
            sta_end=20.0,
        )
        assert recs == []

    def test_clipped_at_widening_start(self) -> None:
        # segment runs 0..40 but widening occupies the last 10 m → ribs clipped to 30
        seg = {"from": "PK0+00.00", "to": "PK0+40.00", "type": 5, "ribs": True}
        recs = _records(
            segments=[seg],
            cfg_types=CFG,
            widening={"b": 5.0, "length": 10.0, "ribs": False},
            sta_end=40.0,
        )
        assert max(r["station"] for r in recs) <= 30.0


class TestWideningRibs:
    """Widening ribs are staggered: alternating rows of n_a and n_a-1 lateral pieces."""

    def test_alternating_row_sizes(self) -> None:
        recs = _records(widening=WIDENING, sta_end=50.0)
        sizes = {len(r["laterals"]) for r in recs}
        assert sizes == {1, 2}  # b=5 → n_a=2, n_b=1

    def test_top_row_is_full(self) -> None:
        recs = _records(widening=WIDENING, sta_end=50.0)
        top = max(recs, key=lambda r: r["station"])
        assert len(top["laterals"]) == 2

    def test_piece_width_and_gap(self) -> None:
        recs = _records(widening=WIDENING, sta_end=50.0)
        for r in recs:
            if len(r["laterals"]) == 2:
                (a0, a1), (b0, b1) = r["laterals"]
                assert a1 - a0 == pytest.approx(2.0)  # rib_len
                assert b1 - b0 == pytest.approx(2.0)
                assert b0 - a1 == pytest.approx(RIBS.gap)  # 1.0 gap between pieces
                assert a0 == pytest.approx(-b1)  # symmetric about centre
            else:
                ((c0, c1),) = r["laterals"]
                assert c1 - c0 == pytest.approx(2.0)
                assert c0 == pytest.approx(-c1)

    def test_starts_at_flat_zone(self) -> None:
        recs = _records(widening=WIDENING, sta_end=50.0)
        # flat_start = sta_end - length + GABION.widening_trans = 50 - 10 + 2 = 42
        assert min(r["station"] for r in recs) >= 42.0 - 1e-6
        assert max(r["station"] for r in recs) == pytest.approx(50.0 - RIBS.size / 2.0)

    def test_ribs_false_skipped(self) -> None:
        w = {**WIDENING, "ribs": False}
        assert _records(widening=w, sta_end=50.0) == []


class TestOutput:
    """Output ordering and combined segment + widening behaviour."""

    def test_sorted_by_station(self) -> None:
        recs = _records(
            segments=[
                {"from": "PK0+00.00", "to": "PK0+30.00", "type": 5, "ribs": True}
            ],
            cfg_types=CFG,
            widening=WIDENING,
            sta_end=50.0,
        )
        stas = [r["station"] for r in recs]
        assert stas == sorted(stas)

    def test_empty_when_nothing(self) -> None:
        assert _records(sta_end=50.0) == []
