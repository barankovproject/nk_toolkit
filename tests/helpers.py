"""Shared test utilities and stubs for canal_model tests."""

from __future__ import annotations

import math


class MockAlignment:
    """Minimal duck-type for AlignmentWrapper, used in virtual-arc tests.

    Returns ang_in for stations before pi_sta, ang_out for stations at or after.
    XY position follows the X axis: xy_at(sta) = (sta, 0.0).
    """

    def __init__(self, ang_in: float, ang_out: float, pi_sta: float) -> None:
        self._ang_in = ang_in
        self._ang_out = ang_out
        self._pi_sta = pi_sta

    def angle_at(self, sta: float) -> float:
        return self._ang_in if sta < self._pi_sta else self._ang_out

    def xy_at(self, sta: float) -> tuple[float, float]:
        return (sta, 0.0)

    def deflection_at(self, pi_sta: float, eps: float = 0.3) -> float:
        delta = self._ang_out - self._ang_in
        while delta > math.pi:
            delta -= 2 * math.pi
        while delta < -math.pi:
            delta += 2 * math.pi
        return abs(delta)


class MockProfile:
    """Minimal duck-type for ProfileWrapper. Constant slope (default level → mag=1)."""

    def __init__(self, slope: float = 0.0) -> None:
        self._slope = slope

    def slope_at(self, sta: float) -> float:
        return self._slope
