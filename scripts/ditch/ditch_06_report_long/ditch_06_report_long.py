"""Read longitudinal-ditch property sets and export a quantity ведомость (per trasse + total).

Sums the per-ditch quantities that ditch_03_build_long writes into the
Arhyz_LongDitch property set (откопка / перемещение / щебень / геотекстиль), grouped
by the Canal label (the trasse, e.g. "1а") stored on every ditch. The report only sums
stored values — rates live in ditch_03_build_long/volumes.py.
"""

from __future__ import annotations

import clr
import csv
import datetime
import os
import traceback
from typing import Any

clr.AddReference("AecBaseMgd")
clr.AddReference("AeccDbMgd")
clr.AddReference("acmgd")
clr.AddReference("acdbmgd")
clr.AddReference("AecPropDataMgd")

import sys

import Autodesk.Aec.PropertyData.DatabaseServices as _PD
from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import (
    OpenMode,
    Polyline3d,
    SymbolUtilityServices,
)

_SCRIPTS_ROOT = r"C:\Arhyz\automation\scripts\ditch"
if _SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, _SCRIPTS_ROOT)

from ditch_core.config import ELEV_SPLIT  # noqa: E402  (needs _SCRIPTS_ROOT on sys.path)

# Elevation-band labels for the ведомость split (by the ditch's highest vertex).
_ZONE_BELOW = "<2500"
_ZONE_ABOVE = ">=2500"


def _zone(top_z: float) -> str:
    """Band a ditch by its highest elevation: at/above ELEV_SPLIT vs below."""
    return _ZONE_ABOVE if top_z >= ELEV_SPLIT else _ZONE_BELOW


def _maxz(ent: Any, tx: Any) -> float:
    """Highest vertex Z of a longitudinal-ditch Polyline3d; -inf for anything else."""
    if not isinstance(ent, Polyline3d):
        return float("-inf")
    zs: list[float] = []
    for vid in ent:
        try:
            zs.append(float(tx.GetObject(vid, OpenMode.ForRead).Position.Z))
        except Exception:
            continue
    return max(zs) if zs else float("-inf")


LOG_DIR = r"C:\Arhyz\automation\scripts\ditch\ditch_06_report_long\logs"
os.makedirs(LOG_DIR, exist_ok=True)
TIMESTAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILE = os.path.join(LOG_DIR, f"report_{TIMESTAMP}.log")
CSV_FILE = os.path.join(LOG_DIR, f"longitudinal_volumes_{TIMESTAMP}.csv")

_PS_DEF = "Arhyz_LongDitch"
_FIELDS = (
    "Index",
    "Length3D",
    "VolExcavation",
    "MoveTonnage",
    "VolStone",
    "VolGeotextile",
    "MatCount",
    "MatArea",
    "AnchorCount",
)


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def _psd_id(db: Any) -> Any:
    """ObjectId of the Arhyz_LongDitch PSD, or None if no longitudinal ditches exist."""
    dpsd = _PD.DictionaryPropertySetDefinitions(db)
    if _PS_DEF in list(dpsd.NamesInUse):
        return dpsd.GetAt(_PS_DEF)
    return None


def _read_ps(ent: Any, psd_id: Any, tx: Any) -> Any:
    """Return (trasse, [_FIELDS values]) for a ditch, or None if it has no Arhyz_LongDitch PS.

    The trasse is the Canal label (e.g. "1а"); ditches built before that field existed
    fall back to "(без трассы)" so none are dropped.
    """
    try:
        ps_id = _PD.PropertyDataServices.GetPropertySet(ent, psd_id)
        ps = tx.GetObject(ps_id, OpenMode.ForRead)
        trasse = str(ps.GetAt(ps.PropertyNameToId("Canal"))).strip() or "(без трассы)"
        vals = [float(ps.GetAt(ps.PropertyNameToId(f))) for f in _FIELDS]
    except Exception:
        return None
    return (trasse, vals)


log("=== ditch_06_report_long ===")
log(f"started: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n")

doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database

# (trasse, zone) -> [length, exc, move, stone, geo, mat_c, mat_a, anch]
totals: dict[tuple[str, str], list[float]] = {}
lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        psd_id = _psd_id(db)
        if psd_id is None:
            log("No Arhyz_LongDitch property set in this drawing — nothing to report.")
        else:
            ms_id = SymbolUtilityServices.GetBlockModelSpaceId(db)
            ms = tx.GetObject(ms_id, OpenMode.ForRead)
            for oid in ms:
                try:
                    ent = tx.GetObject(oid, OpenMode.ForRead)
                except Exception:
                    continue
                res = _read_ps(ent, psd_id, tx)
                if res is None:
                    continue
                trasse, vals = res
                # band by the ditch's highest vertex: a run crossing the boundary
                # counts entirely in the at/above band.
                key = (trasse, _zone(_maxz(ent, tx)))
                # vals = [idx, length, exc, move, stone, geo, mat_c, mat_a, anch]
                acc = totals.setdefault(key, [0.0] * 8)
                for i, v in enumerate(vals[1:]):
                    acc[i] += v
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

header = [
    "trasse",
    "zone",
    "length_m",
    "excavation_m3",
    "move_t",
    "stone_m3",
    "geotextile_m2",
    "mattress_pcs",
    "mattress_m2",
    "anchor_pcs",
]
# Per column: how many decimals to round to (mattress_pcs / anchor_pcs are counts).
_DECIMALS = [None, 2, 2, 2, 2, 2, 0, 2, 0]


def _fmt(vals: list[float]) -> list[Any]:
    return [round(v, d) if d else round(v) for v, d in zip(vals, _DECIMALS[1:])]


rows: list[list[Any]] = []
grand = [0.0] * 8
for key in sorted(totals):
    trasse, zone = key
    acc = totals[key]
    rows.append([trasse, zone, *_fmt(acc)])
    for i, v in enumerate(acc):
        grand[i] += v
    log(
        f"  {trasse:18s} {zone:>7} L={acc[0]:8.2f}  exc={acc[1]:8.2f}  move={acc[2]:8.2f}  "
        f"stone={acc[3]:7.2f}  geo={acc[4]:8.2f}  mat={round(acc[5]):>4}шт/{acc[6]:7.2f}m2  "
        f"anch={round(acc[7]):>4}шт"
    )

if rows:
    rows.append(["TOTAL", "", *_fmt(grand)])
    with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(header)
        writer.writerows(rows)
    log(f"\n{len(rows) - 1} (trasse, zone) row(s) exported -> {CSV_FILE}")
    OUT = CSV_FILE
else:
    log("\nNo tagged longitudinal ditches found.")
    OUT = LOG_FILE

log("=== DONE ===")
