"""Bootstrap script — creates the 13 widening Assembly variants in Civil 3D.

For every entry in WIDENING_VARIANTS:
  1. Skip if target Assembly already exists in the drawing
  2. DeepCloneObjects the base Assembly into the same owner
  3. Rename clone to the widening name
  4. Translate clone by (+600 + idx*100, 0, 0) — idx counts per-base-type variants
  5. Set ParamsDouble[0].Value (bw) to the widening b

Idempotent — re-running only creates the missing variants. To regenerate any
of them, erase that Assembly in the drawing first.

Naming follows existing assembly convention: <bw_mm>x<d_mm>_<t_mm>.
"""

from __future__ import annotations

import clr
import datetime
import os
import sys
import traceback

clr.AddReference("AecBaseMgd")
clr.AddReference("AeccDbMgd")
clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import IdMapping, ObjectIdCollection, OpenMode
from Autodesk.AutoCAD.Geometry import Matrix3d, Vector3d
from Autodesk.Civil.ApplicationServices import CivilApplication

_LIB_ROOT = r"C:\Arhyz\automation\scripts"
_AUTOMATION_ROOT = os.path.dirname(_LIB_ROOT)
for _p in (_LIB_ROOT, _AUTOMATION_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from civil.utils import safe_iter, safe_resolve  # noqa: E402

LOG_DIR = r"C:\Arhyz\automation\scripts\build_widening_assemblies\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, f"build_{datetime.datetime.now():%Y%m%d_%H%M%S}.log")

# Per-base offset rules (matches user spec)
X_OFFSET_FIRST = 600.0
X_OFFSET_STEP = 100.0

# (base_assembly_name, new_assembly_name, new_bw_metres)
# Order within each base group determines X offset (first → +600, then +100 each).
WIDENING_VARIANTS: list[tuple[str, str, float]] = [
    ("500x500_170", "2000x500_170", 2.0),
    ("500x500_170", "5000x500_170", 5.0),
    ("600x600_170", "3000x600_170", 3.0),
    ("600x600_170", "5000x600_170", 5.0),
    ("750x750_300", "3000x750_300", 3.0),
    ("750x750_300", "10000x750_300", 10.0),
    ("1500x750_170 (2)", "3000x750_170", 3.0),
    ("1500x750_170 (2)", "5000x750_170", 5.0),
    ("1500x750_500", "5000x750_500", 5.0),
    ("1500x750_500", "6000x750_500", 6.0),
    ("1500x750_500", "10000x750_500", 10.0),  # shared with type 6
    ("7000x1500_500", "15000x1500_500", 15.0),
    ("10000x2000_500", "25000x2000_500", 25.0),
]


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def find_assembly(ac, tx, name: str):
    """Return (ObjectId, Assembly) for the named assembly, or (None, None)."""
    for raw in safe_iter(ac):
        asm = safe_resolve(raw, tx)
        if asm is None:
            continue
        try:
            if asm.Name == name:
                return raw, asm
        except Exception:
            continue
    return None, None


def gabion_subassembly_id(asm, tx):
    """Return the ObjectId of the non-Daylight subassembly inside `asm`, or None."""
    for raw_g in safe_iter(asm.Groups):
        g = safe_resolve(raw_g, tx)
        if g is None:
            continue
        for sid in safe_iter(g.GetSubassemblyIds()):
            sub = safe_resolve(sid, tx)
            if sub is None:
                continue
            if not str(sub.Name).lower().startswith("daylight"):
                return sid
    return None


def build_one(
    ac, tx, db, base_name: str, new_name: str, new_bw: float, x_offset: float
) -> str:
    """Build one widening variant. Returns status string for the log."""
    # 1. Skip if target already exists
    existing_id, _ = find_assembly(ac, tx, new_name)
    if existing_id is not None:
        return "SKIP (already exists)"

    # 2. Find source base assembly
    src_id, src = find_assembly(ac, tx, base_name)
    if src is None:
        return f"FAIL: base '{base_name}' not found"

    # 3. DeepClone
    ids = ObjectIdCollection()
    ids.Add(src_id)
    mapping = IdMapping()
    try:
        db.DeepCloneObjects(ids, src.OwnerId, mapping, False)
    except Exception as e:
        return f"FAIL DeepClone: {type(e).__name__}: {e}"

    clone_id = None
    for record in mapping:
        if record.Key == src_id:
            clone_id = record.Value
            break
    if clone_id is None:
        return "FAIL: no IdMapping entry for source"

    # 4. Rename + translate
    clone_w = tx.GetObject(clone_id, OpenMode.ForWrite)
    try:
        clone_w.Name = new_name
    except Exception as e:
        return f"FAIL rename: {type(e).__name__}: {e}"
    try:
        clone_w.TransformBy(Matrix3d.Displacement(Vector3d(x_offset, 0.0, 0.0)))
    except Exception as e:
        return f"FAIL translate: {type(e).__name__}: {e}"

    # 5. Set bw on the gabion subassembly
    gabion_id = gabion_subassembly_id(clone_w, tx)
    if gabion_id is None:
        return "FAIL: gabion subassembly not found in clone"
    try:
        sub_w = tx.GetObject(gabion_id, OpenMode.ForWrite)
        sub_w.ParamsDouble.get_Item(0).Value = new_bw
    except Exception as e:
        return f"FAIL bw set: {type(e).__name__}: {e}"

    return f"OK  (clone_id={clone_id})"


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

log("=== build_widening_assemblies ===")
log(f"started: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
log(f"variants: {len(WIDENING_VARIANTS)}")

doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
civil_db = CivilApplication.ActiveDocument

results: list[str] = []
lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        ac = civil_db.AssemblyCollection
        log(f"AssemblyCollection.Count before: {ac.Count}\n")

        # Per-base-type counter for X offset
        per_base_idx: dict[str, int] = {}
        for base_name, new_name, new_bw in WIDENING_VARIANTS:
            idx = per_base_idx.get(base_name, 0)
            x_offset = X_OFFSET_FIRST + idx * X_OFFSET_STEP
            per_base_idx[base_name] = idx + 1

            status = build_one(ac, tx, db, base_name, new_name, new_bw, x_offset)
            line = f"  [{base_name} +{x_offset:.0f}]  -> {new_name}  bw={new_bw}  :  {status}"
            log(line)
            results.append(line)

        log(f"\nAssemblyCollection.Count after: {ac.Count}")
        tx.Commit()
        log("transaction committed")
    except Exception as e:
        log(f"\nERROR inside tx: {e}")
        log(traceback.format_exc())
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

log("\n=== DONE ===")
OUT = "\n".join(results)
