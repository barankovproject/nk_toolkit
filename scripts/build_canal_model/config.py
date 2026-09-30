from __future__ import annotations

import json
import os
from typing import Any

from civil.utils import find_best_match, normalize, pk_to_sta
from paths import (
    CANALS_DIR,
    CANALS_DATA_DIR as DATA_DIR,
    GSI_BASKETS_FILE,
    TROUGH_TYPES_FILE,
    TYPES_FILE,
    TYPES_FILE_STAGE1,
)

__all__ = [
    "find_best_match",
    "normalize",
    "pk_to_sta",
]


class TroughParams:
    """Plain class, not @dataclass -- Dynamo's CPython3 engine has no
    `dataclasses` module (surfaced 2026-09-18 on НК-4А-6; same reason
    build_gsi_apron/config.py and others already use plain classes)."""

    gap = 0.0
    std_len = 2.99
    mono_min_len = 2.0
    mono_min_zone = 0.2
    mono_margin_factor = 1.5
    slice_end_gap = 0.05


class GabionParams:
    """Plain class, not @dataclass -- see TroughParams."""

    loft_step = 2.0
    trans_len = 2.0
    widening_trans = 2.0
    pi_merge_tol = 0.5
    min_trim = 2.0
    # Minimum gabion unit length: a trailing loft remainder shorter than this is
    # merged with the previous step and split evenly (доборные ГСИ rule).
    min_unit = 0.5
    # Safety margin added to the bisector miter pullback for PI-adjacent spans
    # (НК-3А-1: span shorter than the pullback self-intersects → degenerate loft).
    miter_margin = 0.1
    # Safety subtracted from loft_step when capping a PI corner piece so the
    # worst longitudinal 3D edge stays under loft_step despite the linearised
    # reach model (~2% systematic underestimate observed on НК-3А-1 PI 86.284).
    edge_safety = 0.05


class SharpPIParams:
    """Plain class, not @dataclass -- see TroughParams."""

    # At a sharp PI on a wide segment we replace the bisector cut with a virtual
    # circular arc: R = canal_top_width * arc_radius_factor, centered on the inner
    # side of the turn. Cross-sections are sampled radially → "circular staircase"
    # of fan slices, no overlap at inner corner.
    deg = 15.0
    arc_radius_factor = 1.1
    arc_min_steps = 4
    arc_deg_per_step = 6.0
    # A frozenset literal is immutable, so (unlike a list/dict) it is safe to
    # assign directly as a class attribute -- no dataclass default_factory
    # trick needed even before dropping @dataclass.
    wide_types: frozenset[str] = frozenset({"7", "8"})


class RibParams:
    """Plain class, not @dataclass -- see TroughParams."""

    size = 0.17
    gap = 1.0
    step = 1.7
    max_len = 3.0
    min_len = 0.5


TROUGH = TroughParams()
GABION = GabionParams()
SHARP_PI = SharpPIParams()
RIBS = RibParams()


def load_gsi_baskets() -> dict[str, str]:
    """Load basket_key → full GSI designation mapping from gsi_baskets.json."""
    try:
        with open(GSI_BASKETS_FILE, encoding="utf-8-sig") as f:
            return json.load(f).get("baskets", {})
    except Exception:
        return {}


# Closed set of gabion type tables a canal config may select via its own
# "type_table" field -- explicit and hardcoded (not an arbitrary path taken from
# the config) so an unknown name fails loudly instead of opening whatever string
# a JSON file happens to contain. "default" (or an absent field) is today's
# canal_types.json, unchanged for all existing Stage 2 canals.
_TYPE_TABLES: dict[str, str] = {
    "default": TYPES_FILE,
    "stage1": TYPES_FILE_STAGE1,
}


def load_types_table(canal_cfg: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Resolve the gabion type dict for one canal from its own config's optional
    "type_table" field (default: "default" -> canal_types.json). Returns (types
    dict, the file path used) -- the path is for logging/error messages, mirroring
    load_canal_config's own (dict, matched name) return shape."""
    name = canal_cfg.get("type_table", "default")
    if name not in _TYPE_TABLES:
        raise Exception(f"Unknown type_table '{name}' -- one of {sorted(_TYPE_TABLES)}")
    path = _TYPE_TABLES[name]
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)["types"], path


def load_trough_table(canal_cfg: dict[str, Any]) -> dict[str, Any]:
    """Trough types available to this canal -- EMPTY for any non-default
    `type_table`. Every consumer in canal_builder.py/section_params.py decides
    "is this segment a trough or a gabion?" purely by `tp_key in
    trough_cfg_types` (checked BEFORE `tp_key in cfg_types` in several places) --
    trough_types.json's real keys ("9"-"12") always exist there regardless of
    which gabion table a canal uses, so a Stage 1 canal whose OWN gabion type
    happens to reuse one of those numbers (e.g. "11") would otherwise be
    misrouted to trough handling with the wrong (Stage 2 trough) dimensions
    (НК-4А-6, 2026-09-18: `eKeyNotFound` from `TroughBuilder` reaching for
    keys the real trough type dict doesn't have, because it silently treated a
    2.0 m-wide gabion span as a 1.78 m trough). Stage 1 has no troughs of its
    own (user 2026-09-18), so the fix is not to give it any trough keys to
    collide with at all. Extend with a "trough_table" selector, mirroring
    `type_table`, if a non-default canal ever needs real troughs of its own."""
    if canal_cfg.get("type_table", "default") != "default":
        return {}
    with open(TROUGH_TYPES_FILE, encoding="utf-8-sig") as f:
        return json.load(f)["types"]


def load_canal_config(align_name: str) -> dict[str, Any]:
    """Load canal JSON config from config/canals/ by fuzzy-matching alignment name."""
    norm = normalize(align_name)
    for fname in os.listdir(CANALS_DIR):
        if not fname.lower().endswith(".json"):
            continue
        if normalize(fname[:-5]) == norm:
            with open(os.path.join(CANALS_DIR, fname), encoding="utf-8-sig") as f:
                return json.load(f)
    raise Exception(
        f"No canal config for '{align_name}' in {CANALS_DIR}. "
        f"Create config/canals/{align_name}.json"
    )
