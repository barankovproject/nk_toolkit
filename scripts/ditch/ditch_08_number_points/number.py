"""Number the "#" attribute of every "Номер_точки_канавы" block in the drawing.

A single running sequence 1..N across the WHOLE drawing (cross + longitudinal
ditches share one numbering). Order: each block's insertion point is projected onto
the configured alignment; blocks are sorted by station ascending, ties broken by Y
then X. If the alignment can't be found, falls back to (Y, X) ordering. Re-running
renumbers from 1, so it is idempotent.

Placement of the blocks is done by ditch_07_draw_point_blocks; this only fills `#`.
"""

from __future__ import annotations

import clr, datetime, os, sys, traceback
from typing import Any, Optional

clr.AddReference("AecBaseMgd")
clr.AddReference("AeccDbMgd")
clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import (
    AttributeReference,
    BlockReference,
    OpenMode,
    SymbolUtilityServices,
)

# Make ditch_core importable (single CONFIG for the whole ditch set).
_LIB_ROOT = os.environ.get("ARHYZ_LIB_ROOT", r"C:\Arhyz\automation\scripts\ditch")
if _LIB_ROOT not in sys.path:
    sys.path.insert(0, _LIB_ROOT)
for _name in [m for m in list(sys.modules) if m.startswith("ditch_core")]:
    del sys.modules[_name]

from ditch_core.config import CONFIG
from ditch_core.selection import find_alignment_and_surface

# Must match ditch_07_draw_point_blocks._BLOCK_NAME and ._NUM_TAG.
_BLOCK_NAME = "Номер_точки_канавы"
_NUM_TAG = "#"

LOG_DIR = r"C:\Arhyz\automation\scripts\ditch\ditch_08_number_points\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, f"number_{datetime.datetime.now():%Y%m%d_%H%M%S}.log")


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def _eff_name(br: Any, tx: Any) -> str:
    """Effective block name (resolves the anonymous record of a dynamic block)."""
    try:
        if br.IsDynamicBlock:
            return tx.GetObject(br.DynamicBlockTableRecord, OpenMode.ForRead).Name
    except Exception:
        pass
    return tx.GetObject(br.BlockTableRecord, OpenMode.ForRead).Name


def _station(align: Any, x: float, y: float) -> Optional[float]:
    """Station of (x, y) projected onto the alignment, or None if it won't project."""
    if align is None:
        return None
    try:
        res = align.StationOffsetAcceptOutOfRange(x, y, 0.0, 0.0, False)
        if isinstance(res, tuple) and len(res) >= 3:
            return float(res[-3])  # station, offset, outofrange
    except Exception:
        pass
    try:
        res = align.StationOffset(x, y, 0.0, 0.0)
        if isinstance(res, tuple) and len(res) >= 2:
            return float(res[-2])  # station, offset
    except Exception:
        pass
    return None


def _set_number(br: Any, tx: Any, value: int) -> bool:
    """Write `value` into the block's `#` attribute. True if the tag was found."""
    for attr_oid in br.AttributeCollection:
        a = tx.GetObject(attr_oid, OpenMode.ForWrite)
        if isinstance(a, AttributeReference) and a.Tag.strip() == _NUM_TAG:
            a.TextString = str(value)
            return True
    return False


def main(tx: Any, db: Any) -> int:
    try:
        align, _surf = find_alignment_and_surface(
            tx, CONFIG.alignment_name, CONFIG.surface_name
        )
        log(f"alignment '{align.Name}' — ordering by station")
    except Exception as e:
        align = None
        log(
            f"alignment not found ({e}); ordering by (Y, X)",
        )

    ms = tx.GetObject(SymbolUtilityServices.GetBlockModelSpaceId(db), OpenMode.ForRead)
    # (sort_key, block_oid, x, y, station)
    rows: list[
        tuple[tuple[float, float, float], Any, float, float, Optional[float]]
    ] = []
    for oid in ms:
        try:
            ent = tx.GetObject(oid, OpenMode.ForRead)
        except Exception:
            continue
        if not isinstance(ent, BlockReference):
            continue
        name = _eff_name(ent, tx)
        if name.strip().lower() != _BLOCK_NAME.strip().lower():
            continue
        p = ent.Position
        sta = _station(align, float(p.X), float(p.Y))
        # Unprojectable points sort last (within station order) but keep a stable
        # (Y, X) tie-break; with no alignment all share station 0 → pure (Y, X).
        key = (sta if sta is not None else float("inf"), float(p.Y), float(p.X))
        rows.append((key, oid, float(p.X), float(p.Y), sta))

    rows.sort(key=lambda r: r[0])
    log(f"found {len(rows)} '{_BLOCK_NAME}' block(s)")

    numbered = 0
    for i, (_key, oid, x, y, sta) in enumerate(rows, start=1):
        br = tx.GetObject(oid, OpenMode.ForWrite)
        if _set_number(br, tx, i):
            numbered += 1
            sta_s = f"{sta:.2f}" if sta is not None else "n/a"
            log(f"  #{i:>3} -> ({x:.2f}, {y:.2f})  sta={sta_s}")
        else:
            log(f"  #{i:>3} at ({x:.2f}, {y:.2f}): no '{_NUM_TAG}' attribute — skipped")
    return numbered


log("=== ditch_08_number_points ===")
log(f"started: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n")

doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
numbered = 0
lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        numbered = main(tx, db)
        tx.Commit()
    except Exception as e:
        log(f"ERROR: {e}\n{traceback.format_exc()}")
        try:
            tx.Abort()
        except Exception:
            pass
    finally:
        try:
            tx.Dispose()
        except Exception:
            pass
finally:
    try:
        lock.Dispose()
    except Exception:
        pass

log(f"\n=== DONE: numbered={numbered} ===")
OUT = LOG_FILE
