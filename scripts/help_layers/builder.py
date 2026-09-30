import datetime
import glob
import os
import traceback

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.Colors import Color, ColorMethod
from Autodesk.AutoCAD.DatabaseServices import LayerTableRecord, LineWeight, OpenMode

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
_LOG_PREFIX = "layers"

_LW3 = LineWeight.LineWeight030

LAYERS = [
    # existing layers
    {"name": "inf_model_canals", "lw": LineWeight.LineWeight050, "color": 86},
    {"name": "inf_model_canals_hatch", "lw": LineWeight.LineWeight009, "color": 86},
    {"name": "inf_model_canals_3d", "lw": LineWeight.LineWeight009, "color": 7},
    {"name": "inf_model_anti_erosion", "lw": LineWeight.LineWeight050, "color": 150},
    {
        "name": "inf_model_anti_erosion_hatch",
        "lw": LineWeight.LineWeight009,
        "color": 150,
    },
    {"name": "inf_model_heigh", "lw": LineWeight.LineWeight009, "color": 95},
    {"name": "inf_model_text", "lw": LineWeight.LineWeight009, "color": 142},
    {"name": "inf_model_thick", "lw": LineWeight.LineWeight050, "color": 222},
    {"name": "inf_model_thin", "lw": LineWeight.LineWeight009, "color": 222},
    {"name": "inf_model_dim", "lw": LineWeight.LineWeight009, "color": 234},
    {"name": "inf_model_hatch", "lw": LineWeight.LineWeight009, "color": 241},
    # gabion types 1-8 (green-blue gradient)
    {"name": "inf_model_canals_3d_t1", "lw": _LW3, "color": 36},
    {"name": "inf_model_canals_3d_t2", "lw": _LW3, "color": 56},
    {"name": "inf_model_canals_3d_t3", "lw": _LW3, "color": 66},
    {"name": "inf_model_canals_3d_t4", "lw": _LW3, "color": 76},
    {"name": "inf_model_canals_3d_t5", "lw": _LW3, "color": 86},
    {"name": "inf_model_canals_3d_t6", "lw": _LW3, "color": 96},
    {"name": "inf_model_canals_3d_t7", "lw": _LW3, "color": 106},
    {"name": "inf_model_canals_3d_t8", "lw": _LW3, "color": 116},
    # trough type 9 (LK 300.60.60) — yellow family
    {"name": "inf_model_canals_3d_t9_lk", "lw": _LW3, "color": 41},
    {"name": "inf_model_canals_3d_t9_pt", "lw": _LW3, "color": 44},
    {"name": "inf_model_canals_3d_t9_prep", "lw": _LW3, "color": 253},
    {"name": "inf_model_canals_3d_t9_mono", "lw": _LW3, "color": 22},
    # trough type 10 (LK 300.120.90) — blue family
    {"name": "inf_model_canals_3d_t10_lk", "lw": _LW3, "color": 150},
    {"name": "inf_model_canals_3d_t10_pt", "lw": _LW3, "color": 153},
    {"name": "inf_model_canals_3d_t10_prep", "lw": _LW3, "color": 253},
    {"name": "inf_model_canals_3d_t10_mono", "lw": _LW3, "color": 24},
    # trough type 11 (LK 300.180.60) — green family
    {"name": "inf_model_canals_3d_t11_lk", "lw": _LW3, "color": 80},
    {"name": "inf_model_canals_3d_t11_pt", "lw": _LW3, "color": 83},
    {"name": "inf_model_canals_3d_t11_prep", "lw": _LW3, "color": 253},
    {"name": "inf_model_canals_3d_t11_mono", "lw": _LW3, "color": 32},
    # trough type 12 (LK 300.300.150) — magenta family
    {"name": "inf_model_canals_3d_t12_lk", "lw": _LW3, "color": 200},
    {"name": "inf_model_canals_3d_t12_pt", "lw": _LW3, "color": 203},
    {"name": "inf_model_canals_3d_t12_prep", "lw": _LW3, "color": 253},
    {"name": "inf_model_canals_3d_t12_mono", "lw": _LW3, "color": 14},
]


def _trim_logs(log_dir, prefix, keep=10):
    for f in sorted(glob.glob(os.path.join(log_dir, f"{prefix}_*.log")))[:-keep]:
        try:
            os.remove(f)
        except OSError:
            pass


class LayerSetupBuilder:
    def __init__(self):
        os.makedirs(_LOG_DIR, exist_ok=True)
        _trim_logs(_LOG_DIR, _LOG_PREFIX)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self._log_path = os.path.join(_LOG_DIR, f"{_LOG_PREFIX}_{ts}.log")

    def _log(self, msg, level="INFO"):
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [{level}] {msg}\n")

    def run(self):
        log = self._log
        log("=== SCRIPT STARTED ===")

        created = []
        skipped = []
        errors = []

        doc = Application.DocumentManager.MdiActiveDocument
        db = doc.Database

        try:
            lock = doc.LockDocument()
            try:
                tx = db.TransactionManager.StartTransaction()
                try:
                    lt = tx.GetObject(db.LayerTableId, OpenMode.ForWrite)
                    ltt = tx.GetObject(db.LinetypeTableId, OpenMode.ForRead)

                    continuous_id = None
                    for lid in ltt:
                        try:
                            lt_rec = tx.GetObject(lid, OpenMode.ForRead)
                            if lt_rec.Name == "Continuous":
                                continuous_id = lid
                                break
                        except Exception:
                            continue
                    if continuous_id is None:
                        raise Exception("Continuous linetype not found")

                    for ld in LAYERS:
                        name = ld["name"]
                        if lt.Has(name):
                            skipped.append(name)
                            log(f"skip (exists): {name}")
                            continue
                        ltr = LayerTableRecord()
                        ltr.Name = name
                        ltr.LineWeight = ld["lw"]
                        ltr.Color = Color.FromColorIndex(ColorMethod.ByAci, ld["color"])
                        ltr.LinetypeObjectId = continuous_id
                        lt.Add(ltr)
                        tx.AddNewlyCreatedDBObject(ltr, True)
                        created.append(name)
                        log(f"created: {name}")

                    tx.Commit()
                    log(f"committed: created={len(created)}, skipped={len(skipped)}")
                except Exception:
                    tx.Abort()
                    raise
                finally:
                    tx.Dispose()

                # filters must be set inside the document lock but outside any transaction
                try:
                    n = self._ensure_filters(db)
                    log(f"layer filters ensured: {n}")
                except Exception as e:
                    log(f"layer filter warning: {e}", "WARN")
            finally:
                lock.Dispose()

        except Exception as ex:
            errors.append(str(ex))
            log(f"ERROR: {ex}", "CRITICAL")
            log(traceback.format_exc(), "CRITICAL")

        log(
            f"=== DONE: created={len(created)}, skipped={len(skipped)}, errors={len(errors)} ==="
        )
        return {"created": created, "skipped": skipped} if not errors else errors

    def _ensure_filters(self, db):
        """Create the 'Canal Model' property filter group (with a nested 3D-by-type filter).

        Must be called outside any transaction — db.LayerFilters is a struct; writing it
        back inside a tx raises eNotOpenForWrite, and outside the document lock eLockViolation.
        """
        from Autodesk.AutoCAD.LayerManager import LayerFilter

        tree = db.LayerFilters
        root = tree.Root
        existing = {root.NestedFilters[i].Name for i in range(root.NestedFilters.Count)}
        if "Canal Model" in existing:
            return 0
        parent = LayerFilter()
        parent.Name = "Canal Model"
        parent.FilterExpression = 'NAME == "inf_model_*"'
        child = LayerFilter()
        child.Name = "Canal 3D (by type)"
        child.FilterExpression = 'NAME == "inf_model_canals_3d_*"'
        parent.NestedFilters.Add(child)
        root.NestedFilters.Add(parent)
        db.LayerFilters = tree
        return 2
