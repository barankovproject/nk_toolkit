"""Dump every FeatureLinePointType a picked FeatureLine exposes via GetPoints, to see
what's really available beyond the PIPoint/AllPoints pair annotate_excavation_points
already tries.

Context: annotate_excavation_points' низ (bottom) callout placement switched from
PIPoint (plan-geometry vertices only) to AllPoints (superset, should also include
pure elevation/profile-break points), and thinned to keep every vertex with a
nonzero 3D turn angle (corner_deg_bot=0.0) -- yet the user still sees some visibly
marked points on the picked характерная линия with no т.N callout (dev/pictures/
"точки с отметками 1/2/3.png"): picture 1 shows it working; picture 2 shows two
points on a plan-straight run with NO callout at all; picture 3 shows a close pair
where one gets a callout and its neighbour doesn't. This dump enumerates every
FeatureLinePointType enum member (not just the two we've tried) and logs how many
points each kind returns and their full coordinates, so we can see whether some
point category is still missing from what AllPoints returns, or whether the
missing picture-2/3 points ARE present but exactly collinear (turn=0.0) / within
corner_min_spacing (1.0m) of a kept neighbour -- i.e. a real data gap vs. a
threshold/dedup question already explainable by the current code.

READ-ONLY: only reads the picked FeatureLine's points, no solids/entities touched.
"""

from __future__ import annotations

import clr, datetime, os, traceback

clr.AddReference("AecBaseMgd")
clr.AddReference("AeccDbMgd")
clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import OpenMode
from Autodesk.AutoCAD.EditorInput import PromptEntityOptions, PromptStatus

try:
    from Autodesk.Civil.DatabaseServices import FeatureLine
except Exception:
    FeatureLine = None
try:
    from Autodesk.Civil import FeatureLinePointType
except Exception:
    FeatureLinePointType = None

_STATUS_OK = int(PromptStatus.OK)

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\dump_featureline_points\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"dump_featureline_points_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(str(msg) + "\n")


doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        log(f"FeatureLine import ok: {FeatureLine is not None}")
        log(f"FeatureLinePointType import ok: {FeatureLinePointType is not None}")

        if FeatureLine is None:
            log("ERROR: FeatureLine class not available -- wrong namespace/reference")
        else:
            opts = PromptEntityOptions(
                "\nВыберите характерную линию низа (FeatureLine): "
            )
            opts.SetRejectMessage("\nНужна FeatureLine.")
            opts.AddAllowedClass(FeatureLine, False)
            per = doc.Editor.GetEntity(opts)
            if int(per.Status) != _STATUS_OK:
                log("no entity picked -- aborting")
            else:
                ent = tx.GetObject(per.ObjectId, OpenMode.ForRead)
                log(f"picked: '{getattr(ent, 'Name', '?')}' handle={ent.Handle}")
                log(f"Closed={getattr(ent, 'Closed', '?')}")

                if FeatureLinePointType is None:
                    log("ERROR: FeatureLinePointType enum not available")
                else:
                    kind_names = [
                        n for n in dir(FeatureLinePointType) if not n.startswith("_")
                    ]
                    log(
                        f"\nFeatureLinePointType members ({len(kind_names)}): {kind_names}"
                    )

                    for kind in kind_names:
                        try:
                            kind_val = getattr(FeatureLinePointType, kind)
                            pts = list(ent.GetPoints(kind_val))
                            log(f"\n=== {kind} -> {len(pts)} point(s) ===")
                            for i, p in enumerate(pts):
                                log(f"  [{i}] ({p.X:.3f}, {p.Y:.3f}, {p.Z:.3f})")
                        except Exception as e:
                            log(f"\n=== {kind} -> ERROR: {e} ===")

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
