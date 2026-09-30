"""Dump manually-placed gabion callout blocks "321" for the callout test-set canals.

For every "321" block belonging to each canal, writes one CSV per canal (out/<name>.csv)
with the full parameter set needed to compare against draw_gabion_view:
station, offset, nearest section point (key + idx + planar distance), insertion XYZ,
scale, rotation, Положение1 X/Y, flip (Отраженное состояние1), attribute texts, layer.

CSV chosen over .xlsx so the in-Civil CPython needs no extra libs; convert to .xlsx
afterwards. Section_points come from the canal data JSON (to tag idx 6/7 = top of wall).
"""

from __future__ import annotations

import clr, csv, datetime, math, os, sys, traceback

clr.AddReference("AecBaseMgd")
clr.AddReference("AeccDbMgd")
clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import (
    BlockReference,
    OpenMode,
    SymbolUtilityServices,
)
from Autodesk.Civil.ApplicationServices import CivilApplication

_LIB_ROOT = r"C:\Arhyz\automation\scripts"
if _LIB_ROOT not in sys.path:
    sys.path.insert(0, _LIB_ROOT)

import json  # noqa: E402

from civil.utils import find_best_match, normalize  # noqa: E402
from paths import CANALS_DATA_DIR  # noqa: E402

BASE = r"C:\Arhyz\automation\scripts\debug\dump_callout_blocks"
LOG_DIR = os.path.join(BASE, "logs")
OUT_DIR = os.path.join(BASE, "out")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(OUT_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"dump_callout_blocks_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)

# new offset-rail / "паучок" pattern reference set (manually placed)
QUERIES = [
    "НК-1A-5",
    "НК-1A-6",
    "НК-1A-7",
    "НК-2B-1",
    "НК-3С-1",
]
BLOCK_NAME = "point_number"

CSV_COLS = [
    "station",
    "offset",
    "sec_key",
    "sec_idx",
    "sec_dist",
    "ins_x",
    "ins_y",
    "ins_z",
    "scale",
    "rotation_deg",
    "pos1x",
    "pos1y",
    "flip",
    "label",
    "layer",
]


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def effective_name(br, tx):
    try:
        if br.IsDynamicBlock:
            return tx.GetObject(br.DynamicBlockTableRecord, OpenMode.ForRead).Name
    except Exception:
        pass
    return tx.GetObject(br.BlockTableRecord, OpenMode.ForRead).Name


def station_offset(align, x, y):
    try:
        res = align.StationOffset(x, y, 0.0, 0.0)
        if isinstance(res, tuple) and len(res) >= 2:
            return float(res[-2]), float(res[-1])
    except Exception:
        pass
    return None, None


def find_alignment(tx, civil_db, query):
    objs, names = [], []
    for oid in civil_db.GetAlignmentIds():
        try:
            a = tx.GetObject(oid, OpenMode.ForRead)
            objs.append(a)
            names.append(a.Name)
        except Exception:
            continue
    res = find_best_match(query, names)
    if res is None:
        return None, None
    return objs[res[0]], res[1]


def load_flat_sections(query):
    norm = normalize(query)
    path = None
    for fname in os.listdir(CANALS_DATA_DIR):
        if fname.endswith(".json") and normalize(fname[:-5]) == norm:
            path = os.path.join(CANALS_DATA_DIR, fname)
            break
    if path is None:
        return []
    with open(path, encoding="utf-8-sig") as f:
        sp = json.load(f).get("section_points", {})
    flat = []
    for key, pts in sp.items():
        for idx, p in enumerate(pts):
            flat.append((key, idx, float(p[0]), float(p[1])))
    return flat


def nearest(x, y, flat):
    best = None
    for key, idx, px, py in flat:
        d = math.hypot(px - x, py - y)
        if best is None or d < best[2]:
            best = (key, idx, d)
    return best


# A callout's insertion sits on the top-of-wall corner, ~1 m off its own alignment
# (up to ~2.7 m in a widening). A block on a neighbouring canal is many metres off,
# so assign each block to the alignment with the smallest |offset| within this cap.
MAX_OFFSET = 3.5


def block_params(obj, tx, sta, off, flat):
    pos = obj.Position
    near = nearest(pos.X, pos.Y, flat) if flat else None
    dyn = {}
    try:
        for prop in obj.DynamicBlockReferencePropertyCollection:
            dyn[prop.PropertyName] = prop.Value
    except Exception:
        pass
    attrs = {}
    try:
        for aoid in obj.AttributeCollection:
            att = tx.GetObject(aoid, OpenMode.ForRead)
            attrs[att.Tag] = att.TextString
    except Exception:
        pass
    sc = obj.ScaleFactors
    return {
        "station": round(sta, 3),
        "offset": round(off, 3),
        "sec_key": near[0] if near else "",
        "sec_idx": near[1] if near else "",
        "sec_dist": round(near[2], 4) if near else "",
        "ins_x": round(pos.X, 4),
        "ins_y": round(pos.Y, 4),
        "ins_z": round(pos.Z, 4),
        "scale": round(float(sc.X), 4),
        "rotation_deg": round(math.degrees(obj.Rotation), 3),
        "pos1x": dyn.get("Положение1 X", ""),
        "pos1y": dyn.get("Положение1 Y", ""),
        "flip": dyn.get("Отраженное состояние1", ""),
        "label": next(iter(attrs.values()), ""),  # т.N point-number text
        "layer": obj.Layer,
    }


def dump_all(tx, db, civil_db):
    canals = []  # (query, align, name, sta_end, flat)
    for q in QUERIES:
        align, name = find_alignment(tx, civil_db, q)
        if align is None:
            log(f"{q}: alignment not found, skipped")
            continue
        canals.append(
            (q, align, name, float(align.EndingStation), load_flat_sections(q))
        )

    buckets = {c[2]: [] for c in canals}
    unassigned = 0
    ms = tx.GetObject(SymbolUtilityServices.GetBlockModelSpaceId(db), OpenMode.ForRead)
    for oid in ms:
        try:
            obj = tx.GetObject(oid, OpenMode.ForRead)
        except Exception:
            continue
        if not isinstance(obj, BlockReference) or effective_name(obj, tx) != BLOCK_NAME:
            continue
        pos = obj.Position
        best = None  # (abs_off, name, sta, off, flat)
        for _q, align, name, sta_end, flat in canals:
            sta, off = station_offset(align, pos.X, pos.Y)
            if sta is None or not (-1.0 <= sta <= sta_end + 1.0):
                continue
            if abs(off) <= MAX_OFFSET and (best is None or abs(off) < best[0]):
                best = (abs(off), name, sta, off, flat)
        if best is None:
            unassigned += 1
            continue
        buckets[best[1]].append(block_params(obj, tx, best[2], best[3], best[4]))

    for _q, _align, name, _se, _flat in canals:
        rows = sorted(buckets[name], key=lambda r: r["station"])
        out_path = os.path.join(OUT_DIR, f"{name}.csv")
        with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CSV_COLS, delimiter=";")
            w.writeheader()
            w.writerows(rows)
        log(f"'{name}': {len(rows)} callout blocks -> {out_path}")
    log(f"unassigned 321 blocks (|offset|>{MAX_OFFSET} on all canals): {unassigned}")


doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
civil_db = CivilApplication.ActiveDocument
lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        log("=== CALLOUT PARAM DUMP ===")
        dump_all(tx, db, civil_db)
        log("=== DONE ===")
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
