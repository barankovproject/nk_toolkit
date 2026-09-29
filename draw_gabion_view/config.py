import json
import os

from civil.utils import find_best_match, normalize, pk_to_sta
from paths import CANALS_DIR, CANALS_DATA_DIR as DATA_DIR, TYPES_FILE

__all__ = [
    "find_best_match",
    "normalize",
    "pk_to_sta",
]


# Plain classes with class attributes: Dynamo's CPython engine chokes on
# dataclasses, so constants are kept as simple attribute containers.
class AlgoParams:
    loft_step = 2.0
    widening_trans = 2.0


class LayoutParams:
    # Shelf placed in WORLD-X on the point's side, pushed out just enough to clear
    # the gabion (rule 1) and other shelves (rule 2). Values calibrated against the
    # hand-placed эталон (7 canals). The block was shrunk from the old XYZ callout
    # (321) to a small point-number label; drawn footprint is now 1.6 x 0.8.
    shelf_w = 1.6
    shelf_h = 0.8
    gap = 5.0  # clear gap between shelf near-edge and gabion edge (rule 1)
    fan_gap = 2.7  # min vertical spacing between stacked shelves (the fan)
    drop_pos1y = 8.0  # |Pos1Y| past which a доборный is dropped (thinning)
    # --- offset-rail ("паучок") placement ---
    rail_offset = 4.0  # OFFSET distance of the canal outline → the shelf-start rail
    rail_gap = 2.5  # min spacing between shelf-starts along the rail
    # The block's Положение1 grip is the FAR (text) end of the polka; the "red point" that
    # must land on the rail is the polka↔leader junction, polka_len further along world +X
    # (mirrored by flip). Measured from the block at its 0.42 scale.
    polka_len = 1.647


class DrawingParams:
    block_name = "point_number"
    gnum_block = "Номер_ГСИ"


ALGO = AlgoParams()
LAYOUT = LayoutParams()
DRAWING = DrawingParams()


def load_canal_config(align_name):
    norm = normalize(align_name)
    for fname in os.listdir(CANALS_DIR):
        if not fname.lower().endswith(".json"):
            continue
        if normalize(fname[:-5]) == norm:
            with open(os.path.join(CANALS_DIR, fname), encoding="utf-8-sig") as f:
                return json.load(f)
    raise Exception(f"No canal config for '{align_name}' in {CANALS_DIR}")


def section_params_at(sta, segments, cfg_types, sta_end, widening):
    last_gabion_key = next(
        (str(s["type"]) for s in reversed(segments) if str(s["type"]) in cfg_types),
        str(segments[0]["type"]),
    )
    if widening is not None:
        w_b = float(widening["b"])
        w_len = float(widening["length"])
        trans_start = sta_end - w_len
        flat_start = trans_start + ALGO.widening_trans
        if sta >= trans_start:
            tp = cfg_types[last_gabion_key]
            d, m_s, t = float(tp["d"]), float(tp["m"]), float(tp["t"])
            last_bw = float(tp["bottom_w"])
            bw = (
                w_b
                if sta >= flat_start
                else last_bw
                + (sta - trans_start) / ALGO.widening_trans * (w_b - last_bw)
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
