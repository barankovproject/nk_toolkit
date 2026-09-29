"""Dump the EG (surface) profile PVIs / grade-break points along an alignment.

Priority:
  1. If a Profile is in the current pickfirst selection, dump that one.
  2. Otherwise list every alignment, its profiles (name + type), and dump the
     PVIs of each EG/surface profile found.

For each PVI: station, elevation, grade in/out and the deflection (Δgrade), so
the surface break points (future cross-ditch boundaries) are readable.
"""

from __future__ import annotations

import datetime
import os
import traceback

import clr

clr.AddReference("AecBaseMgd")
clr.AddReference("AeccDbMgd")
clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import OpenMode
from Autodesk.Civil.DatabaseServices import Profile, ProfileType

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\dump_eg_profile\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"dump_eg_profile_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def dump_profile(tx, prof) -> None:
    """Log a profile's identity and all its PVIs with grades."""
    try:
        ptype = str(prof.ProfileType)
    except Exception as e:
        ptype = f"<type? {e}>"
    log(f"\nProfile '{prof.Name}'  type={ptype}")
    try:
        log(
            f"  station range: {float(prof.StartingStation):.3f} - "
            f"{float(prof.EndingStation):.3f}  length={float(prof.Length):.3f}"
        )
    except Exception as e:
        log(f"  station range: <error {e}>")

    try:
        pvis = prof.PVIs
        n = pvis.Count
    except Exception as e:
        log(f"  PVIs: <unavailable: {e}>")
        return

    log(f"  PVI count: {n}")
    rows = []
    for pvi in pvis:
        try:
            sta = float(pvi.Station)
            elev = float(pvi.Elevation)
        except Exception as e:
            log(f"    PVI <read error {e}>")
            continue
        gin = gout = None
        for attr in ("GradeIn", "GradeOut"):
            pass
        try:
            gin = float(pvi.GradeIn)
        except Exception:
            gin = None
        try:
            gout = float(pvi.GradeOut)
        except Exception:
            gout = None
        rows.append((sta, elev, gin, gout))

    for sta, elev, gin, gout in rows:
        gin_s = f"{gin * 100:+.2f}%" if gin is not None else "  --  "
        gout_s = f"{gout * 100:+.2f}%" if gout is not None else "  --  "
        d_s = ""
        if gin is not None and gout is not None:
            d = (gout - gin) * 100
            flag = " ***" if abs(d) > 1.0 else ""
            d_s = f"  Δ={d:+.2f}%{flag}"
        log(f"    sta {sta:9.3f}  elev {elev:9.3f}  in {gin_s}  out {gout_s}{d_s}")


doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
ed = doc.Editor

lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        # 1. pickfirst selection
        psr = ed.SelectImplied()
        picked_profiles = 0
        if psr.Status.ToString() == "OK" and psr.Value is not None:
            ids = list(psr.Value.GetObjectIds())
            log(f"pickfirst selection: {len(ids)} object(s)")
            for oid in ids:
                ent = tx.GetObject(oid, OpenMode.ForRead)
                log(f"  selected: {type(ent).__name__}")
                if isinstance(ent, Profile):
                    dump_profile(tx, ent)
                    picked_profiles += 1
        else:
            log("pickfirst selection: empty")

        # 2. fall back to scanning all alignments' profiles
        if picked_profiles == 0:
            log("\nNo profile in selection — scanning all alignments:")
            bt = tx.GetObject(db.BlockTableId, OpenMode.ForRead)
            from Autodesk.AutoCAD.DatabaseServices import SymbolUtilityServices
            from Autodesk.Civil.DatabaseServices import Alignment

            ms = tx.GetObject(
                SymbolUtilityServices.GetBlockModelSpaceId(db), OpenMode.ForRead
            )
            aligns = []
            for oid in ms:
                ent = tx.GetObject(oid, OpenMode.ForRead)
                if isinstance(ent, Alignment):
                    aligns.append(ent)
            log(f"alignments in model space: {len(aligns)}")
            for al in aligns:
                try:
                    pids = list(al.GetProfileIds())
                except Exception as e:
                    log(f"\nalignment '{al.Name}': profile ids error {e}")
                    continue
                log(f"\nalignment '{al.Name}': {len(pids)} profile(s)")
                for pid in pids:
                    prof = tx.GetObject(pid, OpenMode.ForRead)
                    is_eg = False
                    try:
                        is_eg = prof.ProfileType == ProfileType.EG
                    except Exception:
                        pass
                    tag = " [EG]" if is_eg else ""
                    log(f"  - '{prof.Name}' type={prof.ProfileType}{tag}")
                    if is_eg:
                        dump_profile(tx, prof)

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
