"""Dump inf_exc_* layer styles after manual restyling, to bake into layers.json."""

from __future__ import annotations

import clr, datetime, os, traceback

clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import OpenMode

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\dump_exc_styles\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"dump_exc_styles_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)

REGAPP = "ARHYZ_EXC"


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def fmt_color(c) -> str:
    try:
        if c.IsByLayer:
            return "ByLayer"
    except Exception:
        pass
    parts = []
    try:
        parts.append(f"ACI={c.ColorIndex}")
    except Exception:
        pass
    try:
        parts.append(f"RGB=({c.Red},{c.Green},{c.Blue})")
    except Exception:
        pass
    return " ".join(parts) if parts else "?"


doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        lt = tx.GetObject(db.LayerTableId, OpenMode.ForRead)

        def ltype_name(oid):
            try:
                return tx.GetObject(oid, OpenMode.ForRead).Name
            except Exception:
                return "?"

        log("=== LAYERS (inf_exc_*) ===")
        for lid in lt:
            ltr = tx.GetObject(lid, OpenMode.ForRead)
            if not ltr.Name.startswith("inf_exc_"):
                continue
            log(f"\n[{ltr.Name}]")
            log(f"  color      : {fmt_color(ltr.Color)}")
            log(f"  linetype   : {ltype_name(ltr.LinetypeObjectId)}")
            log(f"  lineweight : {ltr.LineWeight}")
            log(
                f"  off={ltr.IsOff}  frozen={ltr.IsFrozen}  plottable={ltr.IsPlottable}"
            )

        # entity-level overrides per layer (sample distinct combos)
        ms = tx.GetObject(db.CurrentSpaceId, OpenMode.ForRead)
        combos: dict = {}
        for oid in ms:
            ent = tx.GetObject(oid, OpenMode.ForRead)
            lay = ent.Layer
            if not lay.startswith("inf_exc_"):
                continue
            try:
                lw = str(ent.LineWeight)
            except Exception:
                lw = "?"
            try:
                lts = round(float(ent.LinetypeScale), 3)
            except Exception:
                lts = "?"
            combo = f"{type(ent).__name__} | color={fmt_color(ent.Color)} | ltype={ent.Linetype} | lw={lw} | ltscale={lts}"
            combos.setdefault(lay, set()).add(combo)

        log("\n\n=== ENTITY STYLES (inf_exc_*) ===")
        for lay in sorted(combos.keys()):
            log(f"\n[{lay}]")
            for c in sorted(combos[lay]):
                log(f"  {c}")

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
