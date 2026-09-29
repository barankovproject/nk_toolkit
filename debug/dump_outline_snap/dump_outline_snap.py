"""Dump gabion outline (inf_lp_outline) start-cap vertices after manual fix for НК-1А-5.

Reads the inf_lp_outline and inf_lp_corridor polylines tagged ARHYZ_LP=НК-1А-5,
logs their first/last vertices, and compares against JSON P7/P4 and corridor ends
so we can derive the correct snap target for the gabion outline.
"""

from __future__ import annotations

import clr, datetime, json, math, os, traceback

clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import OpenMode

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\dump_outline_snap\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"dump_outline_snap_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)

REGAPP = "ARHYZ_LP"
CANAL = "НК-1А-5"  # НК-1А-5
JSON_PATH = r"C:\arhyz_s2_data\data\canals\НК-1A-5.json"


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def dist(a, b):
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


with open(JSON_PATH, encoding="utf-8") as f:
    data = json.load(f)
sp = data.get("section_points", {})
stations = sorted(sp.keys(), key=lambda k: float(k))
sta0, sta_last = stations[0], stations[-1]
P7_start = sp[sta0][8][:2]
P4_start = sp[sta0][5][:2]
P7_end = sp[sta_last][8][:2]
P4_end = sp[sta_last][5][:2]

log(f"JSON stations: {len(stations)}  first={sta0} last={sta_last}")
log(f"  P7_start (idx8 @ sta0): {P7_start}")
log(f"  P4_start (idx5 @ sta0): {P4_start}")
log(f"  P7_end   (idx8 @ last): {P7_end}")
log(f"  P4_end   (idx5 @ last): {P4_end}")

doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        ms = tx.GetObject(db.CurrentSpaceId, OpenMode.ForRead)

        def matches(ent):
            try:
                rb = ent.GetXDataForApplication(REGAPP)
            except Exception:
                return False
            if rb is None:
                return False
            name = next((str(tv.Value) for tv in rb if tv.TypeCode == 1000), None)
            return name == CANAL

        outline_pl = None
        corridor_pl = None
        for oid in ms:
            ent = tx.GetObject(oid, OpenMode.ForRead)
            lay = ent.Layer
            if lay == "inf_lp_outline" and matches(ent):
                outline_pl = ent
            elif lay == "inf_lp_corridor" and matches(ent):
                corridor_pl = ent

        def pl_xy(pl, i):
            p = pl.GetPoint2dAt(i)
            return (float(p.X), float(p.Y))

        if outline_pl is not None:
            n = outline_pl.NumberOfVertices
            log(f"\nGABION outline (inf_lp_outline): {n} vertices")
            for label, i in (
                ("v0", 0),
                ("v1", 1),
                ("v[n-2]", n - 2),
                ("v[n-1]", n - 1),
            ):
                xy = pl_xy(outline_pl, i)
                log(f"  {label} @ idx {i}: {xy}")
                log(
                    f"      dist->P7_start={dist(xy, P7_start):.4f}  dist->P4_start={dist(xy, P4_start):.4f}"
                )
        else:
            log("\nGABION outline NOT found")

        if corridor_pl is not None:
            n = corridor_pl.NumberOfVertices
            log(f"\nCORRIDOR outline (inf_lp_corridor): {n} vertices")
            for label, i in (("v0", 0), ("v[n-1]", n - 1)):
                xy = pl_xy(corridor_pl, i)
                log(f"  {label} @ idx {i}: {xy}")
                log(
                    f"      dist->P7_start={dist(xy, P7_start):.4f}  dist->P4_start={dist(xy, P4_start):.4f}"
                )
        else:
            log("\nCORRIDOR outline NOT found")

        if outline_pl is not None and corridor_pl is not None:
            no = outline_pl.NumberOfVertices
            nc = corridor_pl.NumberOfVertices
            g_v0 = pl_xy(outline_pl, 0)
            g_vl = pl_xy(outline_pl, no - 1)
            c_v0 = pl_xy(corridor_pl, 0)
            c_vl = pl_xy(corridor_pl, nc - 1)
            log("\nGabion endpoint -> nearest corridor endpoint:")
            log(f"  gabion v0   {g_v0}")
            log(
                f"     ->corr v0   {dist(g_v0, c_v0):.4f}    ->corr v[n-1] {dist(g_v0, c_vl):.4f}"
            )
            log(f"  gabion v[n-1] {g_vl}")
            log(
                f"     ->corr v0   {dist(g_vl, c_v0):.4f}    ->corr v[n-1] {dist(g_vl, c_vl):.4f}"
            )

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
