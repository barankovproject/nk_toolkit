"""Reflect Grading via clr.GetClrType; find all Grading* types across loaded assemblies."""

from __future__ import annotations

import clr, datetime, os, traceback

import System

clr.AddReference("acmgd")
clr.AddReference("acdbmgd")
clr.AddReference("AecBaseMgd")
clr.AddReference("AeccDbMgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import OpenMode, SymbolUtilityServices
from Autodesk.Civil.DatabaseServices import Grading

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\dump_excavation_grading\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"reflect2_grading_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def sig(m) -> str:
    ps = ", ".join(f"{p.ParameterType.Name} {p.Name}" for p in m.GetParameters())
    kind = "static" if m.IsStatic else "inst "
    return f"  [{kind}] {m.ReturnType.Name} {m.Name}({ps})"


doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        log("=== all loaded types containing 'Grading' ===")
        for asm in System.AppDomain.CurrentDomain.GetAssemblies():
            try:
                for t in asm.GetTypes():
                    if "Grading" in t.Name:
                        log(f"  {t.FullName}   [{asm.GetName().Name}]")
            except Exception:
                continue

        ct = clr.GetClrType(Grading)
        log("\n=== Grading :: declared methods (clr type) ===")
        for m in ct.GetMethods():
            if m.DeclaringType is None or m.DeclaringType.Name != "Grading":
                continue
            if m.Name.startswith(("get_", "set_", "add_", "remove_")):
                continue
            log(sig(m))
        log("  -- declared properties --")
        for p in ct.GetProperties():
            if p.DeclaringType is not None and p.DeclaringType.Name == "Grading":
                log(f"    {p.PropertyType.Name} {p.Name}")

        # existing Grading instance: all no-arg public instance methods + values
        ms = tx.GetObject(
            SymbolUtilityServices.GetBlockModelSpaceId(db), OpenMode.ForRead
        )
        g = None
        for oid in ms:
            try:
                ent = tx.GetObject(oid, OpenMode.ForRead)
            except Exception:
                continue
            if type(ent).__name__ == "Grading":
                g = ent
                break
        if g is not None:
            log("\n=== existing Grading: ALL no-arg instance method results ===")
            for m in g.GetType().GetMethods():
                if m.GetParameters().Length != 0 or m.IsStatic:
                    continue
                if m.Name.startswith(("get_", "set_", "add_", "remove_", "Get_")):
                    pass
                rt = m.ReturnType.Name
                if rt in ("Void",):
                    continue
                nm = m.Name
                if nm in (
                    "ToString",
                    "GetHashCode",
                    "Clone",
                    "GetType",
                    "MemberwiseClone",
                    "GetRXClass",
                ):
                    continue
                try:
                    log(f"  {rt} {nm}() = {m.Invoke(g, None)}")
                except Exception as e:
                    log(f"  {rt} {nm}(): <err {str(e)[:80]}>")
        else:
            log("\nno Grading instance found")

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
