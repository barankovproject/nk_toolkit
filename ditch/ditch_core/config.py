from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class CrossDitchParams:
    """Tunable parameters for cross-ditch placement.

    alignment_name — name (or unique fragment) of the target Alignment. Fuzzy-
                     matched against the drawing's alignments.
    surface_name   — name (or unique fragment) of the target TIN Surface.
    step           — spacing between ditches along the alignment (metres), as
                     plan distance. No slope correction (2D plan feature).
    sample_step    — spacing of the transverse surface samples used to build each
                     ditch's own cross-profile (metres). Smaller = finer break
                     detection, more FindElevationAtXY calls.
    slope_break    — slope-change threshold that marks a бровка: the first node
                     (walking out from the axis) where the cross-profile slope
                     jumps by more than this is the ditch end on that side.
                     Dimensionless (Δ rise/run); 0.15 ≈ a 15 % grade kink.
    max_reach      — half-length cap of a ditch on each side of the axis (metres);
                     also the limit of the transverse sampling.
    ditch_depth    — how far each end is dropped below the surface at its бровка
                     (metres). Both ends drop equally, so the longitudinal grade
                     comes from the бровка height difference, not the depth.
    slope_min/max  — target longitudinal grade band along the ditch. The skew
                     angle is grown until the grade lands in [slope_min, slope_max]
                     (water must drain toward the low-side откос).
    theta_step_deg — skew-angle search increment (degrees).
    theta_max_deg  — skew-angle ceiling (degrees); also bounded so the ditch's
                     along-alignment projection stays within one `step`
                     (neighbouring ditches must not overlap in plan).
    """

    alignment_name: str = ""
    surface_name: str = ""
    step: float = 20.0
    sample_step: float = 0.5
    slope_break: float = 0.15
    max_reach: float = 50.0
    ditch_depth: float = 0.55
    slope_min: float = 0.02
    # Target ceiling 0.04, not the hard physical 0.05: pick_theta selects the
    # smallest skew that lands in band, i.e. the steep edge, so a 0.04 target keeps
    # ~0.01 margin under 0.05 and survives small re-sampling jitter on a rebuild.
    slope_max: float = 0.04
    theta_step_deg: float = 1.0
    theta_max_deg: float = 75.0
    # When True, the skew search stops as soon as a ditch's along-alignment
    # projection exceeds step/2 on either side, so neighbouring ditches can never
    # overlap in plan. Set False to let θ grow up to theta_max_deg regardless of
    # spacing (safe when `step` is large enough that overlap is impossible) — this
    # lets steep stretches reach a flatter grade instead of going out_of_band.
    forbid_neighbour_overlap: bool = True
    start_marker_d: float = 3.0  # diameter of the circle marking the ditch start
    # Min slope (rise/run) that counts as an откос face when reading cut-vs-fill
    # just past the бровка: walk along the face while segments stay this steep,
    # its sign = cut (climbs) or fill (drops). Откосы are ~45° (slope ~1); 0.3
    # (~17°) is a safe floor above бровка-floor noise. Following the face this
    # way works for short steep and long shallow откосы without a fixed window.
    scarp_min_slope: float = 0.3
    # Probe arm (m) along the alignment for the terrain-fall direction (sets the
    # skew sign). Long enough that a local bump doesn't flip one ditch against
    # its neighbours.
    grade_probe: float = 10.0
    # Max along-alignment distance (m) for a ditch to count as a "neighbour" in
    # the start-side consistency pass. Ditches farther than this sit on a
    # different stretch of terrain, so their orientation must not force this one.
    neighbour_max_dist: float = 50.0
    # Half-length of the гаситель (stilling apron) along the ditch at the foot of
    # the откос насыпи: full width = 2 * killer_half (1.4 m → 0.7 + 0.7).
    killer_half: float = 0.7


# ─────────────────────────────────────────────────────────────────────────────
# SINGLE CONFIG for the whole ditch script set (ditch_01/03/04/05/06 + legacy
# ditch_core builder). Edit the alignment / surface names here ONCE before running
# any ditch script — they all read from this module.
# ─────────────────────────────────────────────────────────────────────────────
CONFIG = CrossDitchParams(
    alignment_name="Трасса основная",
    surface_name="Трассы (1)",
)

# Human canal label (e.g. "1а") written into every ditch property set so each
# ditch records which canal it belongs to. Used as the DEFAULT trasse for ditches
# drawn on a base ditch layer (no suffix); see trasse_for_layer below.
CANAL = "1a"

# Cross-ditch base layer (the main run; the refresh derives the trasse from its
# suffix the same way it does for the longitudinal SOURCE_LAYER).
CROSS_DITCH_LAYER = "inf_md_ditch"


def trasse_for_layer(layer: str, base: str, default: str = CANAL) -> Optional[str]:
    """Trasse (canal) label encoded as a suffix on a ditch layer name.

    One drawing holds ditches for many canals. Instead of a single global CANAL,
    each canal's ditches are moved onto their own layer named `<base>_<trasse>`
    (e.g. inf_ct_toe_1в → "1в"); ditches left on the bare `base` layer take the
    `default` (CANAL). The volume refresh reads this per ditch so the ведомость
    groups quantities by canal without any code edit when a new trasse appears.

    Returns the trasse string, or None if `layer` is neither `base` nor a
    `base_<...>` layer (i.e. not a ditch layer of this type).
    """
    if layer == base:
        return default
    prefix = base + "_"
    if layer.startswith(prefix):
        suffix = layer[len(prefix) :].strip()
        return suffix or default
    return None


def layer_for_trasse(base: str, canal: str) -> str:
    """Inverse of trasse_for_layer: the layer a canal's ditches are drawn on.

    The build step routes each run's geometry onto `<base>_<canal>` so the refresh's
    suffix isolation can tell canals apart; a blank canal falls back to the bare base
    layer (the default bucket). Must stay an exact inverse of trasse_for_layer — both
    use the single `_` separator — or the refresh would mis-group quantities.
    """
    canal = (canal or "").strip()
    return f"{base}_{canal}" if canal else base


# Cut-toe line (ditch_01_draw_cut_toe): min scarp rise (m) that counts a bank as
# a cut side (откос выемки).
CUT_EPS = 0.3

# Longitudinal ditch (ditch_03_build_long): user's 2D polylines live on this layer;
# the 3D ditch bottom is draped DROP metres below the trasse surface.
SOURCE_LAYER = "inf_ct_toe"
DROP = 0.46

# Elevation band split for the ведомости (ditch_06_report_*): quantities are reported
# separately below and at/above this surface elevation (m). A ditch is classified by
# its нагорный (highest) end, so a ditch that crosses the boundary counts entirely in
# the at/above band. Edit here once — both cross + long reports read it.
ELEV_SPLIT = 2500.0
