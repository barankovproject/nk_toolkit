"""Dump Daylight FL endpoints vs gabion P7/P4 at canal start/end for НК-1А-5."""

from __future__ import annotations

import clr, datetime, json, math, os, sys, traceback

clr.AddReference("AecBaseMgd")
clr.AddReference("AeccDbMgd")
clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import OpenMode
from Autodesk.Civil.ApplicationServices import CivilApplication

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\dump_daylight_pts\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"dump_daylight_pts_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def dist(a, b):
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


# --- load gabion section_points from JSON ---
JSON_PATH = r"C:\arhyz_s2_data\data\canals\НК-1A-5.json"
with open(JSON_PATH, encoding="utf-8") as f:
    canal_data = json.load(f)

sp = canal_data.get("section_points", {})
stations = sorted(sp.keys(), key=lambda k: float(k))
log(f"section_points stations: {len(stations)}")
log(f"  first: {stations[0]}   last: {stations[-1]}")

first_sta = stations[0]
last_sta = stations[-1]

P7_first = sp[first_sta][8][:2]  # index 8 = P7, left outer
P4_first = sp[first_sta][5][:2]  # index 5 = P4, right outer
P7_last = sp[last_sta][8][:2]
P4_last = sp[last_sta][5][:2]

log("\nGabion boundary points:")
log(f"  P7 at sta {first_sta} (left  start): {P7_first}")
log(f"  P4 at sta {first_sta} (right start): {P4_first}")
log(f"  P7 at sta {last_sta}  (left  end):   {P7_last}")
log(f"  P4 at sta {last_sta}  (right end):   {P4_last}")

# --- find corridor and Daylight FLs ---
doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
civil_db = CivilApplication.ActiveDocument

lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        cc = civil_db.CorridorCollection
        log(f"\nTotal corridors: {cc.Count}")

        target_corr = None
        for i in range(cc.Count):
            try:
                corr = tx.GetObject(cc[i], OpenMode.ForRead)
                log(f"  corridor[{i}]: '{corr.Name}'")
                n = corr.Name.lower().replace("-", "").replace(" ", "")
                if "1a5" in n or "1а5" in n:
                    target_corr = corr
            except Exception as e:
                log(f"  corridor[{i}]: ERROR {e}")

        if target_corr is None:
            log("\nNo matching corridor found for НК-1А-5")
        else:
            log(f"\nMatched corridor: '{target_corr.Name}'")
            bl = list(target_corr.Baselines)[0]
            fl_map = bl.MainBaselineFeatureLines.FeatureLineCollectionMap
            fls = list(fl_map["Daylight"])
            log(f"Daylight FLs found: {len(fls)}")

            for fi, fl in enumerate(fls):
                fps = list(fl.FeatureLinePoints)
                if not fps:
                    log(f"  FL[{fi}]: empty")
                    continue
                off0 = float(fps[0].Offset)
                first_xyz = fps[0].XYZ
                last_xyz = fps[-1].XYZ
                p_first = (float(first_xyz.X), float(first_xyz.Y))
                p_last = (float(last_xyz.X), float(last_xyz.Y))
                side = "RIGHT" if off0 >= 0 else "LEFT"
                log(f"\n  FL[{fi}] {side}  offset[0]={off0:.3f}  total_pts={len(fps)}")
                log(f"    first pt: {p_first}")
                log(f"    last  pt: {p_last}")

                # distances to gabion boundary points
                log(f"    dist(first → P7_start): {dist(p_first, P7_first):.4f}")
                log(f"    dist(first → P4_start): {dist(p_first, P4_first):.4f}")
                log(f"    dist(first → P7_end):   {dist(p_first, P7_last):.4f}")
                log(f"    dist(first → P4_end):   {dist(p_first, P4_last):.4f}")
                log(f"    dist(last  → P7_start): {dist(p_last, P7_first):.4f}")
                log(f"    dist(last  → P4_start): {dist(p_last, P4_first):.4f}")
                log(f"    dist(last  → P7_end):   {dist(p_last, P7_last):.4f}")
                log(f"    dist(last  → P4_end):   {dist(p_last, P4_last):.4f}")

        log("\n=== DONE ===")
        tx.Commit()
    except Exception as e:
        log(f"ERROR: {e}")
        log(traceback.format_exc())
        tx.Abort()
    finally:
        tx.Dispose()
finally:
    lock.Dispose()

OUT = LOG_FILE
