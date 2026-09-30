"""Parse the anchor CSV: each row maps a slope elevation to an anchor length.

Format is intentionally loose. The user types lines like ``100 - 6`` (elevation
on the left, anchor length on the right). Separators may be ``-``, ``,``, a tab,
or plain whitespace. Blank lines and ``#`` comments are ignored. The length is
carried through for later phases (block insertion); it is not used geometrically
when building the flat surfaces.
"""

from __future__ import annotations

import os
import re
from typing import Any

# Split on a dash surrounded by spaces, a comma, a tab, or a run of whitespace.
_SEP = re.compile(r"\s*-\s*|\s*,\s*|\t+|\s+")


def parse_anchor_csv(path: str) -> list[tuple[float, float]]:
    """Return ``[(elevation, length), ...]`` parsed from ``path``.

    Raises a clear error if the file is missing or no row parses. Rows are
    returned in file order; duplicate elevations are kept (the caller decides
    how to name/collapse them).
    """
    if not os.path.exists(path):
        raise Exception(f"Anchor CSV not found: {path}")

    rows: list[tuple[float, float]] = []
    bad: list[str] = []
    with open(path, encoding="utf-8-sig") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p for p in _SEP.split(line) if p != ""]
            if len(parts) < 2:
                bad.append(line)
                continue
            try:
                elevation = float(parts[0])
                length = float(parts[1])
            except ValueError:
                bad.append(line)
                continue
            rows.append((elevation, length))

    if not rows:
        detail = f" Unparseable lines: {bad}" if bad else ""
        raise Exception(f"No anchor rows parsed from {path}.{detail}")
    return rows


def fmt_elevation(elevation: float) -> str:
    """Format an elevation for use in a surface name: ``100``, ``106.5``."""
    return f"{elevation:g}"


def csv_path_next_to(module_file: str, name: str = "anchors.csv") -> str:
    """Resolve the CSV path that sits beside the calling module file."""
    return os.path.join(os.path.dirname(os.path.abspath(module_file)), name)
