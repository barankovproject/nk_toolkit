"""Read cross-ditch property sets and export a quantity ведомость + a slope table.

Two outputs, both read-only (stored values are never recomputed unless RECOMPUTE):
  * ditch_volumes_<ts>.csv  — per-trasse + total quantities (выемка / перемещение /
    щебень / геотекстиль), summed from the Arhyz_CrossDitch property set, plus the
    total built ditch length (length_total_m): the 3D length of every ditch part —
    основа (main run) + соединитель (connector) + гаситель (apron) — measured from
    the drawn polylines on the inf_md_ditch / inf_md_connector / inf_md_killer layer
    families and grouped by trasse from the layer suffix.
  * ditch_slopes_<ts>.csv   — one row per ditch (Canal, Index, Station, ThetaDeg,
    Slope, ZStart, ZEnd, Length2D, Status) with the longitudinal grade and a flag
    for any ditch whose slope falls outside the target band [slope_min, slope_max].

A rate change lives in ditch_04_build_cross/volumes.py alone (then a rebuild); the
slope band lives in ditch_core/config.py (CONFIG.slope_min / slope_max).
"""

from __future__ import annotations

import clr
import csv
import datetime
import math
import os
import sys
import traceback
from typing import Any, Optional

clr.AddReference("AecBaseMgd")
clr.AddReference("AeccDbMgd")
clr.AddReference("acmgd")
clr.AddReference("acdbmgd")
clr.AddReference("AecPropDataMgd")

import Autodesk.Aec.PropertyData.DatabaseServices as _PD
from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import (
    OpenMode,
    Polyline3d,
    SymbolUtilityServices,
)

# Set True to recompute every ditch's volume PS from the current drawn geometry
# before summing (same as running ditch_05_build_cross_volumes first). False = read-only:
# sum whatever is already stored.
RECOMPUTE = False

_SCRIPTS_ROOT = r"C:\Arhyz\automation\scripts\ditch"
if _SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, _SCRIPTS_ROOT)

from ditch_core.config import CONFIG, ELEV_SPLIT, trasse_for_layer  # noqa: E402  (needs _SCRIPTS_ROOT on sys.path)

# Elevation-band labels for the ведомость split (by the ditch's нагорный/top end).
_ZONE_BELOW = "<2500"
_ZONE_ABOVE = ">=2500"


def _zone(top_z: float) -> str:
    """Band a ditch/part by its highest elevation: at/above ELEV_SPLIT vs below."""
    return _ZONE_ABOVE if top_z >= ELEV_SPLIT else _ZONE_BELOW


LOG_DIR = r"C:\Arhyz\automation\scripts\ditch\ditch_06_report_cross\logs"
os.makedirs(LOG_DIR, exist_ok=True)
TIMESTAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILE = os.path.join(LOG_DIR, f"report_{TIMESTAMP}.log")
CSV_FILE = os.path.join(LOG_DIR, f"ditch_volumes_{TIMESTAMP}.csv")
SLOPE_CSV = os.path.join(LOG_DIR, f"ditch_slopes_{TIMESTAMP}.csv")

_PS_DEF = "Arhyz_CrossDitch"
_LAYER = "inf_md_ditch"
# Connector (соединитель) + гаситель (apron) layer families. These carry no PS,
# only geometry, so the total ditch length is measured from their polylines and
# grouped by trasse via the layer suffix (same convention as the ditch layer).
_LAYER_CONN = "inf_md_connector"
_LAYER_KILLER = "inf_md_killer"
_FIELDS = ("VolExcavation", "MoveTonnage", "VolStone", "VolGeotextile")


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def _poly_len_3d(ent: Any, tx: Any) -> float:
    """3D length of a Polyline3d (sum over its vertices); 0.0 for anything else.

    Start-marker circles share the ditch layer but are not Polyline3d, so they
    contribute nothing to the length.
    """
    if not isinstance(ent, Polyline3d):
        return 0.0
    pts: list[tuple[float, float, float]] = []
    for vid in ent:
        try:
            p = tx.GetObject(vid, OpenMode.ForRead).Position
            pts.append((float(p.X), float(p.Y), float(p.Z)))
        except Exception:
            continue
    return sum(
        math.sqrt(
            (pts[i + 1][0] - pts[i][0]) ** 2
            + (pts[i + 1][1] - pts[i][1]) ** 2
            + (pts[i + 1][2] - pts[i][2]) ** 2
        )
        for i in range(len(pts) - 1)
    )


def _poly_maxz(ent: Any, tx: Any) -> float:
    """Highest vertex Z of a Polyline3d (the part's top); -inf for anything else."""
    if not isinstance(ent, Polyline3d):
        return float("-inf")
    zs: list[float] = []
    for vid in ent:
        try:
            zs.append(float(tx.GetObject(vid, OpenMode.ForRead).Position.Z))
        except Exception:
            continue
    return max(zs) if zs else float("-inf")


def _psd_id(db: Any) -> Any:
    """ObjectId of the Arhyz_CrossDitch PSD, or None if no ditches were ever built."""
    dpsd = _PD.DictionaryPropertySetDefinitions(db)
    if _PS_DEF in list(dpsd.NamesInUse):
        return dpsd.GetAt(_PS_DEF)
    return None


def _read_ps(ent: Any, psd_id: Any, tx: Any) -> Optional[dict[str, Any]]:
    """Return a dict of the ditch's stored fields, or None if it has no PS.

    The trasse is the Canal label (e.g. "1а") stored on every ditch; ditches built
    before that field existed fall back to "(без трассы)" so none are dropped.
    Start-marker circles share the inf_md_ditch layer but carry no property set,
    so GetPropertySet throws on them and they are skipped. Slope diagnostics are
    read defensively (0.0 when a field predates the schema).
    """
    try:
        ps_id = _PD.PropertyDataServices.GetPropertySet(ent, psd_id)
        ps = tx.GetObject(ps_id, OpenMode.ForRead)
        trasse = str(ps.GetAt(ps.PropertyNameToId("Canal"))).strip() or "(без трассы)"
        vols = [float(ps.GetAt(ps.PropertyNameToId(f))) for f in _FIELDS]
    except Exception:
        return None

    def _num(name: str) -> float:
        try:
            return float(ps.GetAt(ps.PropertyNameToId(name)))
        except Exception:
            return 0.0

    def _txt(name: str) -> str:
        try:
            return str(ps.GetAt(ps.PropertyNameToId(name))).strip()
        except Exception:
            return ""

    return {
        "trasse": trasse,
        "vols": vols,
        "index": int(_num("Index")),
        "station": _num("Station"),
        "theta": _num("ThetaDeg"),
        "slope": _num("Slope"),
        "z_start": _num("ZStart"),
        "z_end": _num("ZEnd"),
        "length_2d": _num("Length2D"),
        "status": _txt("Status"),
    }


log("=== ditch_06_report_cross ===")
log(f"started: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n")

doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database

# (trasse, zone) -> [count, exc_m3, move_t, stone_m3, geo_m2]
totals: dict[tuple[str, str], list[float]] = {}
# (trasse, zone) -> total built ditch length (m), summing the 3D length of every part:
# основа (inf_md_ditch) + соединитель (inf_md_connector) + гаситель (inf_md_killer)
length_totals: dict[tuple[str, str], float] = {}
# one entry per ditch for the slope table
slope_rows: list[dict[str, Any]] = []

lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        psd_id = _psd_id(db)
        if psd_id is None:
            log("No Arhyz_CrossDitch property set in this drawing — nothing to report.")
        else:
            ms_id = SymbolUtilityServices.GetBlockModelSpaceId(db)
            ms = tx.GetObject(ms_id, OpenMode.ForRead)
            if RECOMPUTE:
                from ditch_04_build_cross.refresh import refresh_volumes

                n = refresh_volumes(ms, tx, psd_id, lambda m, level="INFO": log(m))
                log(f"recomputed {n} ditch(es) from current geometry\n")
            for oid in ms:
                try:
                    ent = tx.GetObject(oid, OpenMode.ForRead)
                    layer = ent.Layer
                except Exception:
                    continue

                # соединитель / гаситель: no PS, contribute only to the total
                # built length; trasse comes from the layer suffix.
                conn_t = trasse_for_layer(layer, _LAYER_CONN)
                kill_t = trasse_for_layer(layer, _LAYER_KILLER)
                if conn_t is not None or kill_t is not None:
                    t = conn_t if conn_t is not None else kill_t
                    key = (t, _zone(_poly_maxz(ent, tx)))
                    length_totals[key] = length_totals.get(key, 0.0) + _poly_len_3d(
                        ent, tx
                    )
                    continue

                # основа: base layer + per-trasse layers inf_md_ditch_<trasse>
                if layer != _LAYER and not layer.startswith(_LAYER + "_"):
                    continue
                rec = _read_ps(ent, psd_id, tx)
                if rec is None:
                    continue
                trasse = rec["trasse"]
                # band the ditch by its нагорный (highest) end: a ditch crossing the
                # boundary counts entirely in the at/above band.
                key = (trasse, _zone(max(rec["z_start"], rec["z_end"])))
                exc, move, stone, geo = rec["vols"]
                acc = totals.setdefault(key, [0.0, 0.0, 0.0, 0.0, 0.0])
                acc[0] += 1
                acc[1] += exc
                acc[2] += move
                acc[3] += stone
                acc[4] += geo
                length_totals[key] = length_totals.get(key, 0.0) + _poly_len_3d(ent, tx)
                slope_rows.append(rec)
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

# ── quantity ведомость ──────────────────────────────────────────────────────
header = [
    "trasse",
    "zone",
    "ditch_count",
    "length_total_m",
    "excavation_m3",
    "move_t",
    "stone_m3",
    "geotextile_m2",
]
rows: list[list[Any]] = []
grand = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
# Union of keys: a part (connector/killer) may land in a different band than its run.
for key in sorted(set(totals) | set(length_totals)):
    trasse, zone = key
    c, exc, move, stone, geo = totals.get(key, [0.0, 0.0, 0.0, 0.0, 0.0])
    length = length_totals.get(key, 0.0)
    rows.append(
        [
            trasse,
            zone,
            int(c),
            round(length, 2),
            round(exc, 2),
            round(move, 2),
            round(stone, 2),
            round(geo, 2),
        ]
    )
    for i, v in enumerate((c, length, exc, move, stone, geo)):
        grand[i] += v
    log(
        f"  {trasse:18s} {zone:>7}  n={int(c):>3}  len={length:9.2f}  exc={exc:9.2f}  "
        f"move={move:9.2f}  stone={stone:8.2f}  geo={geo:8.2f}"
    )

if rows:
    rows.append(
        [
            "TOTAL",
            "",
            int(grand[0]),
            round(grand[1], 2),
            round(grand[2], 2),
            round(grand[3], 2),
            round(grand[4], 2),
            round(grand[5], 2),
        ]
    )
    with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(header)
        writer.writerows(rows)
    log(f"\n{len(rows) - 1} (trasse, zone) row(s) exported -> {CSV_FILE}")
    OUT = CSV_FILE
else:
    log("\nNo tagged ditches found on layer inf_md_ditch.")
    OUT = LOG_FILE

# ── slope table ─────────────────────────────────────────────────────────────
# One row per ditch with the longitudinal grade; any slope outside the target
# band [slope_min, slope_max] is flagged so a too-steep ditch (terrain-limited
# out_of_band) is easy to spot. Sorted by trasse then station.
s_min, s_max = CONFIG.slope_min, CONFIG.slope_max
if slope_rows:
    slope_rows.sort(key=lambda r: (r["trasse"], r["station"]))
    s_header = [
        "trasse",
        "index",
        "station_m",
        "theta_deg",
        "slope",
        "z_start",
        "z_end",
        "length_2d",
        "status",
        "out_of_band",
    ]
    s_out: list[list[Any]] = []
    n_oob = 0
    log(f"\nSlope table (target band {s_min:.3f}..{s_max:.3f}):")
    for r in slope_rows:
        oob = not (s_min <= r["slope"] <= s_max)
        n_oob += int(oob)
        s_out.append(
            [
                r["trasse"],
                r["index"],
                round(r["station"], 2),
                round(r["theta"], 1),
                round(r["slope"], 4),
                round(r["z_start"], 2),
                round(r["z_end"], 2),
                round(r["length_2d"], 2),
                r["status"],
                "YES" if oob else "",
            ]
        )
        log(
            f"  [{r['trasse']:>6}] #{r['index']:>3} sta={r['station']:8.2f} "
            f"θ={r['theta']:4.0f}° slope={r['slope']:.4f} "
            f"Z {r['z_start']:.2f}->{r['z_end']:.2f} {r['status']:12s}"
            f"{'  <-- OUT OF BAND' if oob else ''}"
        )
    with open(SLOPE_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(s_header)
        writer.writerows(s_out)
    log(f"\n{len(slope_rows)} ditch(es) -> {SLOPE_CSV}  ({n_oob} out of band)")

log("=== DONE ===")
