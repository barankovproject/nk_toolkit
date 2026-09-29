"""Dump layer + entity styles for the НК-1А-5 location plan after manual restyling.

Reports, for every inf_lp_* layer: color / linetype / lineweight / transparency / on-off.
Then, for entities tagged ARHYZ_LP=НК-1А-5, lists distinct per-entity style combos
(type, color override, linetype, lineweight, ltscale) and hatch pattern/scale/angle,
so the script defaults can be updated to match.
"""

from __future__ import annotations

import clr, datetime, os, traceback

clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import OpenMode

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\dump_lp_styles\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"dump_lp_styles_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)

REGAPP = "ARHYZ_LP"
CANAL = "НК-1А-5"  # canal name in XData


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def fmt_color(c) -> str:
    parts = []
    try:
        if c.IsByLayer:
            return "ByLayer"
        if c.IsByBlock:
            return "ByBlock"
    except Exception:
        pass
    try:
        parts.append(f"ACI={c.ColorIndex}")
    except Exception:
        pass
    try:
        parts.append(f"RGB=({c.Red},{c.Green},{c.Blue})")
    except Exception:
        pass
    return " ".join(parts) if parts else "?"


def fmt_transparency(t) -> str:
    try:
        a = t.Alpha  # 255 = opaque
        pct = round((1.0 - a / 255.0) * 100.0)
        return f"{pct}% (alpha={a})"
    except Exception:
        return "?"


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

        log("=== LAYERS (inf_lp_*) ===")
        for layer_id in lt:
            ltr = tx.GetObject(layer_id, OpenMode.ForRead)
            if not ltr.Name.startswith("inf_lp_"):
                continue
            log(f"\n[{ltr.Name}]")
            log(f"  color      : {fmt_color(ltr.Color)}")
            log(f"  linetype   : {ltype_name(ltr.LinetypeObjectId)}")
            log(f"  lineweight : {ltr.LineWeight}")
            log(f"  transparency: {fmt_transparency(ltr.Transparency)}")
            log(
                f"  off={ltr.IsOff}  frozen={ltr.IsFrozen}  plottable={ltr.IsPlottable}"
            )

        # --- entities tagged with this canal ---
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

        # layer -> set of combo strings
        combos: dict = {}
        counts: dict = {}
        for oid in ms:
            ent = tx.GetObject(oid, OpenMode.ForRead)
            lay = ent.Layer
            if not lay.startswith("inf_lp_"):
                continue
            if not matches(ent):
                continue
            etype = type(ent).__name__
            try:
                lw = str(ent.LineWeight)
            except Exception:
                lw = "?"
            try:
                lts = round(float(ent.LinetypeScale), 3)
            except Exception:
                lts = "?"
            try:
                lt_name = ent.Linetype
            except Exception:
                lt_name = "?"
            combo = f"{etype} | color={fmt_color(ent.Color)} | ltype={lt_name} | lw={lw} | ltscale={lts}"
            if etype == "Hatch":
                try:
                    combo += (
                        f" | pattern={ent.PatternName} scale={round(float(ent.PatternScale), 3)}"
                        f" angle={round(float(ent.PatternAngle), 4)} solid={ent.IsSolidFill}"
                    )
                except Exception as e:
                    combo += f" | hatch?({e})"
            combos.setdefault(lay, set()).add(combo)
            counts[lay] = counts.get(lay, 0) + 1

        log("\n\n=== ENTITY STYLES (tagged НК-1А-5) ===")
        for lay in sorted(combos.keys()):
            log(f"\n[{lay}]  ({counts[lay]} entities)")
            for combo in sorted(combos[lay]):
                log(f"  {combo}")

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
