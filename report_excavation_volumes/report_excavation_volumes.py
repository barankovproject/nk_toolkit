"""Read existing TIN volume surfaces and export cut/fill/net volumes to CSV."""

from __future__ import annotations

import clr
import csv
import datetime
import os
import sys
import traceback
from typing import Any

clr.AddReference("AecBaseMgd")
clr.AddReference("AeccDbMgd")
clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import OpenMode
from Autodesk.Civil.ApplicationServices import CivilApplication

LOG_DIR = r"C:\Arhyz\automation\scripts\report_excavation_volumes\logs"
os.makedirs(LOG_DIR, exist_ok=True)
TIMESTAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILE = os.path.join(LOG_DIR, f"report_{TIMESTAMP}.log")
CSV_FILE = os.path.join(LOG_DIR, f"excavation_volumes_{TIMESTAMP}.csv")

VOLUME_SUFFIX = " - Volume"


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


log("=== report_excavation_volumes ===")
log(f"started: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n")

doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
civil_db = CivilApplication.ActiveDocument

rows: list[dict] = []
lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        for oid in civil_db.GetSurfaceIds():
            try:
                s = tx.GetObject(oid, OpenMode.ForRead)
                if not s.IsVolumeSurface:
                    continue
                name = s.Name
                if not name.endswith(VOLUME_SUFFIX):
                    continue
                canal = name[: -len(VOLUME_SUFFIX)]
                try:
                    vp = s.GetVolumeProperties()
                    cut = round(vp.AdjustedCutVolume, 2)
                    fill = round(vp.AdjustedFillVolume, 2)
                    net = round(vp.AdjustedNetVolume, 2)
                    log(f"  {canal:30s} cut={cut:.1f}  fill={fill:.1f}  net={net:.1f}")
                    rows.append(
                        {"canal": canal, "cut_m3": cut, "fill_m3": fill, "net_m3": net}
                    )
                except Exception as e:
                    log(f"  {canal:30s} ERR: {e}")
            except Exception:
                pass

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

rows.sort(key=lambda r: r["canal"])

if rows:
    with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f, fieldnames=["canal", "cut_m3", "fill_m3", "net_m3"], delimiter=";"
        )
        writer.writeheader()
        writer.writerows(rows)
    log(f"\n{len(rows)} corridors exported -> {CSV_FILE}")
else:
    log("No volume surfaces found (name must end with ' - Volume')")

log("=== DONE ===")
OUT = CSV_FILE
