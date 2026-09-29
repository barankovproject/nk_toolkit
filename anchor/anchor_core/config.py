from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AnchorParams:
    """Tunable parameters for the whole anchor script set (anchor_01..04).

    Edit values here ONCE; every anchor script reads this single CONFIG.

    Axis (anchor_02_build_axis):
      min_segment   — floor on the length of an axis segment (metres); longer is
                      fine. No axis segment is shorter than this.
      angle_tol_deg — a vertex is kept only where the median has turned more than
                      this (degrees) since the last vertex. Bigger = fewer, longer
                      segments on straight stretches.

    Grid (anchor_03_build_grid):
      step          — spacing of SAME-colour perpendicular lines (metres). Lines
                      alternate red/blue, so the lines themselves sit at step/2
                      (see line_step). A red and the next red are `step` apart.
      overhang      — how far each perpendicular extends past the outer contours
                      (metres per end). The band itself is between the lowest and
                      highest horizontals.

    Circles (anchor_04_place_anchors):
      diameter      — anchor circle diameter (metres); also the overlap distance
                      (centres closer than this are merged to one).
      Row spacing of anchors is ``step``: a row gap is split into
      round(gap / step) even sub-gaps, so fill circles land ~one step from their
      neighbours (never crammed against one). Distance is straight-line.

    Colours (ACI): even-indexed lines/rows are color_even, odd are color_odd.

    Layers: names every script reads/draws on (kept here so cross-script
    references stay in one place; per-script layers.json defines their style).
    """

    # anchor_02 — axis
    min_segment: float = 6.0
    angle_tol_deg: float = 20.0

    # anchor_03 — grid
    step: float = 4.0
    overhang: float = 5.0
    # how far each segment's lines run past its own territory into the neighbours
    # (metres). Extra service lines that no longer cross the band are dropped, so
    # this only fills the seams — overshoot is harmless.
    seam_overlap: float = 8.0

    # anchor_04 — circles
    diameter: float = 1.0
    # max distance an anchor may be nudged from its grid crossing when relaxing
    # row spacing (metres). Keeps the staggered grid recognisable (no drift).
    max_shift: float = 0.5
    # a row gap wider than max_gap_factor * step is a "hole" and gets a fill
    # anchor. Lower = fill more holes (denser); higher = tolerate bigger gaps.
    max_gap_factor: float = 1.2

    # colours (ACI)
    color_even: int = 1  # red
    color_odd: int = 5  # blue

    # layers
    horiz_layer: str = "inf_md_anchor"
    axis_layer: str = "inf_md_anchor_axis"
    grid_layer: str = "inf_md_anchor_grid"
    div_layer: str = "inf_md_anchor_div"
    pts_layer: str = "inf_md_anchor_pts"

    @property
    def line_step(self) -> float:
        """Actual spacing of the perpendicular lines (alternating colours)."""
        return self.step / 2.0


# ─────────────────────────────────────────────────────────────────────────────
# SINGLE CONFIG for the whole anchor script set. Edit here before running.
# ─────────────────────────────────────────────────────────────────────────────
CONFIG = AnchorParams()
