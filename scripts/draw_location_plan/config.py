from __future__ import annotations

import json
import os
from dataclasses import dataclass

from civil.utils import find_best_match, normalize, pk_to_sta
from paths import CANALS_DIR, TYPES_FILE

__all__ = [
    "find_best_match",
    "normalize",
    "pk_to_sta",
    "TROUGH_TYPES",
    "DRAWING",
    "load_canal_config",
    "section_params_at",
]

TROUGH_TYPES: frozenset[int] = frozenset({9, 10, 11, 12})

WIDENING_TRANS: float = 2.0


@dataclass(frozen=True)
class DrawingParams:
    step: float = 2.0
    station_tick_m: float = 10.0
    tick_half_len: float = 1.5

    centerline_layer: str = "inf_lp_centerline"
    outline_layer: str = "inf_lp_outline"
    hatch_layer: str = "inf_lp_hatch"
    gabions_layer: str = "inf_lp_gabions"
    stations_layer: str = "inf_lp_stations"

    hatch_pattern: str = "ANSI31"
    hatch_scale: float = 0.5
    hatch_angle: float = 0.7854  # 45 degrees in radians

    text_height: float = 2.0


DRAWING = DrawingParams()


def load_canal_config(align_name: str) -> dict:
    norm = normalize(align_name)
    for fname in os.listdir(CANALS_DIR):
        if not fname.lower().endswith(".json"):
            continue
        if normalize(fname[:-5]) == norm:
            with open(os.path.join(CANALS_DIR, fname), encoding="utf-8-sig") as f:
                return json.load(f)
    raise Exception(f"No canal config for '{align_name}' in {CANALS_DIR}")


def section_params_at(
    sta: float,
    segments: list,
    cfg_types: dict,
    sta_end: float,
    widening: dict | None,
) -> tuple[float, float, float, float]:
    """Return (bw, d, m, t) for the gabion type at station sta.

    Trough stations fall back to the last gabion type for outline continuity.
    """
    last_gabion_key = next(
        (str(s["type"]) for s in reversed(segments) if str(s["type"]) in cfg_types),
        str(segments[0]["type"]),
    )
    if widening is not None:
        w_b = float(widening["b"])
        w_len = float(widening["length"])
        trans_start = sta_end - w_len
        flat_start = trans_start + WIDENING_TRANS
        if sta >= trans_start:
            tp = cfg_types[last_gabion_key]
            d, m_s, t = float(tp["d"]), float(tp["m"]), float(tp["t"])
            last_bw = float(tp["bottom_w"])
            bw = (
                w_b
                if sta >= flat_start
                else last_bw + (sta - trans_start) / WIDENING_TRANS * (w_b - last_bw)
            )
            return bw, d, m_s, t
    tp_key = last_gabion_key
    for seg in segments:
        if pk_to_sta(seg["from"]) <= sta <= pk_to_sta(seg["to"]) + 0.001:
            candidate = str(seg["type"])
            if candidate in cfg_types:
                tp_key = candidate
                break
    tp = cfg_types[tp_key]
    return float(tp["bottom_w"]), float(tp["d"]), float(tp["m"]), float(tp["t"])
