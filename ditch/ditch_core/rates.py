"""Single source of the ditch quantity rates (расход материалов).

The rates used to compute per-ditch volumes (выемка / щебень / геотекстиль /
перемещение, plus the longitudinal Reno-mattress + anchor counts) live in
`rates.json` next to this module, split into two sections:

  * "cross" — поперечные водоотводные канавы (ditch_04_build_cross/volumes.py)
  * "long"  — продольные водоотводные канавы (ditch_03_build_long/volumes.py)

Edit `rates.json` to change a rate, then re-run the volume refresh (step 6) —
the build modules read their section from here, so a rate change needs no code
edit. Geotextile keeps its `geo_base` and `geo_coef` (×1.2) as separate fields so
the m²/м.п. value (geo_base × geo_coef) is traceable to its source numbers.
"""

from __future__ import annotations

import json
import os
from typing import Any

_RATES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rates.json")


def _load() -> dict[str, Any]:
    with open(_RATES_PATH, encoding="utf-8") as f:
        return json.load(f)


RATES: dict[str, Any] = _load()
CROSS_RATES: dict[str, float] = RATES["cross"]
LONG_RATES: dict[str, float] = RATES["long"]
