from __future__ import annotations

import math

from ditch_core.rates import LONG_RATES

# Quantity rates for the longitudinal drainage ditch (продольная канава). Loaded
# from ditch_core/rates.json (section "long") — edit the rates there, not here.
# Unlike the cross-ditch, it has no connector and no гаситель — everything is a
# flat per linear metre of 3D ditch length. See memory project-longitudinal-ditch.
EXC_PER_M = LONG_RATES["exc_per_m"]  # откопка, m³ per linear metre
STONE_PER_M = LONG_RATES[
    "stone_per_m"
]  # щебень (заполнение матрацев), m³ per linear metre
GEO_BASE = LONG_RATES["geo_base"]  # геотекстиль base, m² per linear metre
GEO_COEF = LONG_RATES["geo_coef"]  # геотекстиль coefficient
GEO_PER_M = GEO_BASE * GEO_COEF  # m² per linear metre
DENSITY = LONG_RATES["density"]  # bulk density, t/m³, for перемещение вынутого грунта
# Reno mattresses (матрацы «Рено» 3×2×0.2): 1 piece per 2 m of ditch PLUS 1 piece
# per plan turn; one mattress face is 3×2 = 6 m².
MAT_PER_M = LONG_RATES["mat_per_m"]  # 1 шт / 2 м.п.
MAT_PER_TURN = LONG_RATES["mat_per_turn"]  # +1 шт per plan turn
MAT_FACE_M2 = LONG_RATES["mat_face_m2"]  # m² per mattress (3 × 2)
ANCHOR_PER_M = LONG_RATES[
    "anchor_per_m"
]  # забивной анкер Ø8мм: 3 шт / 1.5 м.п. = 2 / m


def ld_volumes(length: float, n_turns: int = 0) -> dict[str, float]:
    """Per-ditch quantities from the 3D ditch length L (metres) and plan-turn count.

    No flat terms for earthwork — the longitudinal ditch has no apron. перемещение
    (t) = откопка (m³) × DENSITY. Reno-mattress and anchor counts are whole pieces
    rounded UP (ceil): mattress count = ceil(L/2 + n_turns), its area = count × 6
    m² (whole mattresses); anchor count = ceil(2 × L).
    """
    exc = EXC_PER_M * length
    mat_count = math.ceil(MAT_PER_M * length + MAT_PER_TURN * n_turns)
    return {
        "VolExcavation": exc,
        "VolStone": STONE_PER_M * length,
        "VolGeotextile": GEO_PER_M * length,
        "MoveTonnage": exc * DENSITY,
        "MatCount": float(mat_count),
        "MatArea": mat_count * MAT_FACE_M2,
        "AnchorCount": float(math.ceil(ANCHOR_PER_M * length)),
    }
