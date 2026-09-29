"""Tests for the manual-flip toggle logic (build_cross_ditches.flips_store).

A user picks a ditch with a Dynamo ObjectSelection node to flip it; the flip is
remembered per alignment so it survives a full rebuild, and picking the same
ditch again restores it (toggle). Only the pure list logic is tested here — file
I/O and the AcDb selection read are exercised in Civil 3D.
"""

from __future__ import annotations

from build_cross_ditches.flips_store import is_flipped, toggle


class TestToggle:
    def test_add_when_absent(self) -> None:
        assert toggle([], 280.0) == [280.0]

    def test_remove_when_present(self) -> None:
        assert toggle([280.0], 280.0) == []

    def test_add_keeps_others_sorted(self) -> None:
        assert toggle([100.0, 300.0], 200.0) == [100.0, 200.0, 300.0]

    def test_remove_within_tolerance(self) -> None:
        # the selected station may be a hair off the stored grid value
        assert toggle([280.0], 280.4) == []

    def test_add_outside_tolerance(self) -> None:
        assert toggle([280.0], 282.0) == [280.0, 282.0]

    def test_round_trip(self) -> None:
        f = toggle([], 60.0)
        f = toggle(f, 60.0)
        assert f == []


class TestIsFlipped:
    def test_present(self) -> None:
        assert is_flipped([20.0, 60.0], 60.0) is True

    def test_within_tolerance(self) -> None:
        assert is_flipped([60.0], 60.3) is True

    def test_absent(self) -> None:
        assert is_flipped([20.0, 60.0], 40.0) is False

    def test_empty(self) -> None:
        assert is_flipped([], 60.0) is False
