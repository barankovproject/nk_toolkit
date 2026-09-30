from __future__ import annotations

import json
import os
from typing import Any

from paths import CANALS_DATA_DIR

# Manual ditch flips persist here, per alignment, so hand corrections survive a
# full rebuild. last_handle guards against the .dyn auto-run re-toggling the same
# selection every cycle: a flip fires only when the selected handle changes.
_FLIPS_FILE = os.path.join(CANALS_DATA_DIR, "cross_ditch_flips.json")

# Station match tolerance: ditches are on a coarse grid (step), so a 1 m window
# safely maps a selected ditch to its station entry.
_STA_TOL = 1.0


def _load_all() -> dict[str, Any]:
    try:
        with open(_FLIPS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_all(data: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(_FLIPS_FILE), exist_ok=True)
    with open(_FLIPS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load(alignment: str) -> tuple[list[float], str]:
    """Return (flipped_stations, last_handle) for an alignment."""
    entry = _load_all().get(alignment, {})
    flipped = [float(s) for s in entry.get("flipped", [])]
    last_handle = str(entry.get("last_handle", ""))
    return flipped, last_handle


def save(alignment: str, flipped: list[float], last_handle: str) -> None:
    data = _load_all()
    data[alignment] = {
        "flipped": sorted(round(s, 3) for s in flipped),
        "last_handle": last_handle,
    }
    _save_all(data)


def is_flipped(flipped: list[float], sta: float, tol: float = _STA_TOL) -> bool:
    """True if station sta is in the flipped list (within tol)."""
    return any(abs(sta - f) <= tol for f in flipped)


def toggle(flipped: list[float], sta: float, tol: float = _STA_TOL) -> list[float]:
    """Add sta to the flipped list, or remove it if already present (within tol)."""
    kept = [f for f in flipped if abs(sta - f) > tol]
    if len(kept) == len(flipped):  # was not present → add
        kept.append(round(sta, 3))
    return sorted(kept)
