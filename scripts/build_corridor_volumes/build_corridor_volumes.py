"""Create a TIN volume surface per corridor: base=existing ground, comp=corridor Top surface.

For each corridor:
  1. Get the first configured CorridorSurface (has LinkCodes) -> its SurfaceId.
  2. Create TinVolumeSurface(name, ground_id, corr_surf_id).
  3. Rebuild and read cut/fill/net volumes.
  4. Leave the volume surface in the drawing.

Idempotent: skips corridors that already have a volume surface named '<canal> - Volume'.
"""

from __future__ import annotations

import clr
import csv
import datetime
import os
import sys
import traceback
from typing import Any, Optional

clr.AddReference("AecBaseMgd")
clr.AddReference("AeccDbMgd")
clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import OpenMode
from Autodesk.Civil.ApplicationServices import CivilApplication
from Autodesk.Civil.DatabaseServices import TinVolumeSurface

_LIB_ROOT = r"C:\Arhyz\automation\scripts"
if _LIB_ROOT not in sys.path:
    sys.path.insert(0, _LIB_ROOT)

from civil.utils import safe_iter, safe_resolve  # noqa: E402

LOG_DIR = r"C:\Arhyz\automation\scripts\build_corridor_volumes\logs"
os.makedirs(LOG_DIR, exist_ok=True)
TIMESTAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILE = os.path.join(LOG_DIR, f"build_{TIMESTAMP}.log")
CSV_FILE = os.path.join(LOG_DIR, f"volumes_{TIMESTAMP}.csv")

GROUND_SURFACE = "Земля (новая)"
VOLUME_SUFFIX = " - Volume"


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def find_ground_surface_id(civil_db: Any, tx: Any) -> Any:
    for oid in civil_db.GetSurfaceIds():
        try:
            s = tx.GetObject(oid, OpenMode.ForRead)
            if s.Name == GROUND_SURFACE:
                return oid
        except Exception:
            pass
    return None


def get_existing_volume_surface_names(civil_db: Any, tx: Any) -> set:
    names: set = set()
    for oid in civil_db.GetSurfaceIds():
        try:
            s = tx.GetObject(oid, OpenMode.ForRead)
            if s.IsVolumeSurface:
                names.add(s.Name)
        except Exception:
            pass
    return names


def get_corridor_surface_id(corr: Any) -> Optional[Any]:
    """Return SurfaceId of the first CorridorSurface that has link codes."""
    try:
        cs_col = corr.CorridorSurfaces
        for cs in cs_col:
            try:
                if list(cs.LinkCodes()):
                    return cs.SurfaceId
            except Exception:
                pass
    except Exception:
        pass
    return None


def build_volume(
    name: str, ground_id: Any, corr_surf_id: Any, tx: Any
) -> tuple[Any, str]:
    """Create and rebuild a TIN volume surface. Returns (vol_id, status_str)."""
    try:
        vol_id = TinVolumeSurface.Create(name, ground_id, corr_surf_id)
    except Exception as e:
        return None, f"FAIL Create: {type(e).__name__}: {e}"

    try:
        vs = tx.GetObject(vol_id, OpenMode.ForWrite)
        vs.Rebuild()
    except Exception as e:
        return vol_id, f"PARTIAL: rebuild failed: {type(e).__name__}: {e}"

    try:
        vp = vs.GetVolumeProperties()
        cut = vp.AdjustedCutVolume
        fill = vp.AdjustedFillVolume
        net = vp.AdjustedNetVolume
        return vol_id, f"OK  cut={cut:.1f}  fill={fill:.1f}  net={net:.1f}"
    except Exception as e:
        return vol_id, f"PARTIAL: volumes unreadable: {type(e).__name__}: {e}"


log("=== build_corridor_volumes ===")
log(f"started: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
log(f"ground: {GROUND_SURFACE!r}\n")

doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
civil_db = CivilApplication.ActiveDocument

rows: list[dict] = []
results: list[str] = []
lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        ground_id = find_ground_surface_id(civil_db, tx)
        log(f"Ground surface id: {ground_id}")
        if ground_id is None:
            log(f"ERROR: '{GROUND_SURFACE}' not found")
        else:
            existing_vol_names = get_existing_volume_surface_names(civil_db, tx)
            log(f"Existing volume surfaces: {len(existing_vol_names)}")
            log(f"Corridors: {civil_db.CorridorCollection.Count}\n")

            for raw in safe_iter(civil_db.CorridorCollection):
                corr = safe_resolve(raw, tx)
                if corr is None:
                    continue
                name = corr.Name
                vol_name = name + VOLUME_SUFFIX

                if vol_name in existing_vol_names:
                    status = "SKIP (volume surface exists)"
                    line = f"  {name:30s} {status}"
                    log(line)
                    results.append(line)
                    continue

                corr_surf_id = get_corridor_surface_id(corr)
                if corr_surf_id is None:
                    status = "SKIP (no configured corridor surface)"
                    line = f"  {name:30s} {status}"
                    log(line)
                    results.append(line)
                    continue

                try:
                    _, status = build_volume(vol_name, ground_id, corr_surf_id, tx)
                except Exception as e:
                    status = f"FAIL: {type(e).__name__}: {e}"
                    log(traceback.format_exc())

                line = f"  {name:30s} {status}"
                log(line)
                results.append(line)

                if status.startswith("OK"):
                    parts = status.split()
                    rows.append(
                        {
                            "canal": name,
                            "cut_m3": parts[1].split("=")[1],
                            "fill_m3": parts[2].split("=")[1],
                            "net_m3": parts[3].split("=")[1],
                        }
                    )

        ok = sum(1 for r in results if "OK" in r)
        skip = sum(1 for r in results if "SKIP" in r)
        fail = len(results) - ok - skip
        log(f"\n--- {ok} OK, {skip} skipped, {fail} failed ---")

        tx.Commit()
        log("transaction committed")
    except Exception as e:
        log(f"\nERROR: {e}\n{traceback.format_exc()}")
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

# Write CSV
if rows:
    with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f, fieldnames=["canal", "cut_m3", "fill_m3", "net_m3"], delimiter=";"
        )
        writer.writeheader()
        writer.writerows(rows)
    log(f"\nCSV: {CSV_FILE}")

log("=== DONE ===")
OUT = "\n".join(results)
