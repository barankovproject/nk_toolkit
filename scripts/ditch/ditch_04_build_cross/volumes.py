from __future__ import annotations

import math
from typing import Any, Optional

from ditch_core.rates import CROSS_RATES

# Quantity rates for cross drainage ditches (поперечные водоотводные канавы).
# Loaded from ditch_core/rates.json (section "cross") — edit the rates there, not
# here. Two rate types: per linear metre of ditch run (3D length L) and a flat
# per-piece amount for the гаситель (stilling apron), applied once when an apron
# exists. Geotextile = geo_base × geo_coef (×1.2). See memory project-ditch-volumes.
EXC_PER_M = CROSS_RATES["exc_per_m"]  # выемка грунта, m³ per linear metre
EXC_KILLER = CROSS_RATES["exc_killer"]  # выемка, m³ flat per гаситель
STONE_PER_M = CROSS_RATES["stone_per_m"]  # укрепление щебнем, m³ per linear metre
STONE_KILLER = CROSS_RATES["stone_killer"]  # щебень, m³ flat per гаситель
GEO_PER_M = CROSS_RATES["geo_base"] * CROSS_RATES["geo_coef"]  # геотекстиль, m²/м.п.
GEO_KILLER = CROSS_RATES["geo_killer"]  # геотекстиль, m² flat per гаситель
DENSITY = CROSS_RATES["density"]  # bulk density, t/m³, for перемещение вынутого грунта


def dist3d(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    """3D distance between two (x, y, z) points."""
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def volumes_from_length(length: float, has_killer: bool) -> dict[str, float]:
    """Per-ditch quantities from the ditch run length L and apron presence.

    The single place rates are applied. `length` is the 3D ditch run (main ditch
    + connector); `has_killer` adds the flat per-гаситель terms. Used both at
    build time (via ditch_volumes) and when recomputing from drawn geometry.
    """
    exc = EXC_PER_M * length + (EXC_KILLER if has_killer else 0.0)
    stone = STONE_PER_M * length + (STONE_KILLER if has_killer else 0.0)
    geo = GEO_PER_M * length + (GEO_KILLER if has_killer else 0.0)
    move = exc * DENSITY
    return {
        "VolExcavation": exc,
        "VolStone": stone,
        "VolGeotextile": geo,
        "MoveTonnage": move,
    }


def ditch_volumes(
    top: tuple[float, float, float],
    ditch_end: tuple[float, float, float],
    killer: Optional[Any],
) -> tuple[dict[str, float], float]:
    """Per-ditch quantities + the 3D ditch length L they are based on.

    L = 3D length of the main ditch (top → ditch_end) plus the connector
    (connector_top → near) when an apron exists. ditch_end already equals
    killer.connector_top when the killer is present, so the connector segment is
    added on top of the main run. The гаситель (near → far) is NOT in L — it is
    the flat per-piece term, added once when an apron exists.

    Returns ({VolExcavation, VolStone, VolGeotextile, MoveTonnage}, L).
    """
    length = dist3d(top, ditch_end)
    has_killer = killer is not None
    if has_killer:
        length += dist3d(killer.connector_top, killer.near)
    return volumes_from_length(length, has_killer), length
