"""Canal config validator — runs without Civil 3D or Dynamo.

Usage:
    python automation/scripts/validate_config/validate_config.py
    python automation/scripts/validate_config/validate_config.py config/canals/NK-1A-1.json
"""

from __future__ import annotations

import glob
import json
import math
import os
import re
import sys
from typing import Any

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
_DATA_ROOT = r"C:\arhyz_s2_data"
_CANAL_TYPES_PATH = os.path.join(_DATA_ROOT, "config", "canal_types.json")
_TROUGH_TYPES_PATH = os.path.join(_DATA_ROOT, "config", "trough_types.json")
_CANALS_DIR = os.path.join(_DATA_ROOT, "config", "canals")

_PK_RE = re.compile(r"^ПК(\d+)\+(\d+(?:\.\d+)?)$")

GABION_TYPES = set(range(1, 9))  # 1-8
TROUGH_TYPES = set(range(9, 13))  # 9-12


def parse_pk(s: str) -> float:
    """'ПК1+50.00' -> 150.0  (metres)"""
    m = _PK_RE.match(s.strip())
    if not m:
        raise ValueError(f"Invalid station format: {repr(s)} (expected ПКX+YY.YY)")
    return int(m.group(1)) * 100.0 + float(m.group(2))


def load_json(path: str) -> Any:
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


class ConfigError:
    def __init__(self, path: str, message: str) -> None:
        self.path = path
        self.message = message

    def __str__(self) -> str:
        return f"  ERROR  {self.message}"


def validate_canal(
    path: str, canal_type_keys: set[int], trough_type_keys: set[int]
) -> list[ConfigError]:
    errors: list[ConfigError] = []

    def err(msg: str) -> None:
        errors.append(ConfigError(path, msg))

    try:
        data = load_json(path)
    except json.JSONDecodeError as e:
        err(f"JSON parse error: {e}")
        return errors
    except OSError as e:
        err(f"Cannot read file: {e}")
        return errors

    if not isinstance(data, dict):
        err("Root must be a JSON object")
        return errors

    # --- segments ---
    segments = data.get("segments")
    if segments is None:
        err("Missing 'segments' field")
    elif not isinstance(segments, list):
        err("'segments' must be an array")
    elif len(segments) == 0:
        err("'segments' is empty")
    else:
        prev_to: float | None = None
        for i, seg in enumerate(segments):
            pfx = f"segments[{i}]"
            if not isinstance(seg, dict):
                err(f"{pfx}: must be an object")
                continue

            # from / to
            raw_from = seg.get("from")
            raw_to = seg.get("to")
            sta_from: float | None = None
            sta_to: float | None = None

            if raw_from is None:
                err(f"{pfx}: missing 'from'")
            else:
                try:
                    sta_from = parse_pk(str(raw_from))
                except ValueError as e:
                    err(f"{pfx}.from: {e}")

            if raw_to is None:
                err(f"{pfx}: missing 'to'")
            else:
                try:
                    sta_to = parse_pk(str(raw_to))
                except ValueError as e:
                    err(f"{pfx}.to: {e}")

            if sta_from is not None and sta_to is not None:
                if sta_to <= sta_from:
                    err(f"{pfx}: 'to' ({sta_to}) must be > 'from' ({sta_from})")
                if prev_to is not None and not math.isclose(
                    sta_from, prev_to, abs_tol=0.001
                ):
                    err(
                        f"{pfx}: gap or overlap — expected 'from'={prev_to:.3f}, got {sta_from:.3f}"
                    )
                if sta_to is not None:
                    prev_to = sta_to

            # type
            seg_type = seg.get("type")
            if seg_type is None:
                err(f"{pfx}: missing 'type'")
            elif not isinstance(seg_type, int):
                err(f"{pfx}.type: must be an integer, got {type(seg_type).__name__}")
            elif seg_type in GABION_TYPES and seg_type not in canal_type_keys:
                err(f"{pfx}.type={seg_type}: not found in canal_types.json")
            elif seg_type in TROUGH_TYPES and seg_type not in trough_type_keys:
                err(f"{pfx}.type={seg_type}: not found in trough_types.json")
            elif seg_type not in GABION_TYPES and seg_type not in TROUGH_TYPES:
                err(f"{pfx}.type={seg_type}: unknown type (expected 1-12)")

            # ribs
            ribs = seg.get("ribs")
            if ribs is None:
                err(f"{pfx}: missing 'ribs'")
            elif not isinstance(ribs, bool):
                err(f"{pfx}.ribs: must be true/false, got {type(ribs).__name__}")

    # --- widening ---
    widening = data.get("widening")
    if widening is not None:
        pfx = "widening"
        if not isinstance(widening, dict):
            err(f"'{pfx}' must be an object or null")
        else:
            for field in ("b", "length"):
                v = widening.get(field)
                if v is None:
                    err(f"{pfx}.{field}: missing")
                elif not isinstance(v, (int, float)):
                    err(f"{pfx}.{field}: must be a number")
                elif float(v) <= 0:
                    err(f"{pfx}.{field}: must be > 0, got {v}")
            ribs = widening.get("ribs")
            if ribs is None:
                err(f"{pfx}.ribs: missing")
            elif not isinstance(ribs, bool):
                err(f"{pfx}.ribs: must be true/false")

    # --- unknown top-level keys ---
    known_keys = {"segments", "widening"}
    for k in data:
        if k not in known_keys:
            err(f"Unknown top-level key: '{k}'")

    return errors


def load_type_keys(path: str, label: str) -> set[int]:
    if not os.path.exists(path):
        print(f"  WARN  {label} not found: {path}")
        return set()
    data = load_json(path)
    return {int(k) for k in data.get("types", {}).keys()}


def main(targets: list[str]) -> int:
    canal_keys = load_type_keys(_CANAL_TYPES_PATH, "canal_types.json")
    trough_keys = load_type_keys(_TROUGH_TYPES_PATH, "trough_types.json")

    if not targets:
        targets = sorted(glob.glob(os.path.join(_CANALS_DIR, "*.json")))
        if not targets:
            print(f"No canal configs found in {_CANALS_DIR}")
            return 1

    total_errors = 0
    for path in targets:
        rel = os.path.relpath(path, _REPO_ROOT)
        errors = validate_canal(path, canal_keys, trough_keys)
        if errors:
            print(f"\nFAIL  {rel}")
            for e in errors:
                print(e)
            total_errors += len(errors)
        else:
            print(f"  OK   {rel}")

    print()
    if total_errors == 0:
        print(f"All {len(targets)} config(s) valid.")
        return 0
    else:
        print(f"{total_errors} error(s) in {len(targets)} config(s).")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
