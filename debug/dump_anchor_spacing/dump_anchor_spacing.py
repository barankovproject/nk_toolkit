"""Find anchor circles that stand too close to a neighbour (spacing audit)."""

from __future__ import annotations

import clr
import datetime
import math
import os
import traceback

clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import Circle, OpenMode

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\dump_anchor_spacing\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"dump_anchor_spacing_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)
PTS_LAYER = "inf_md_anchor_pts"
CLOSE = 3.0


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        ms = tx.GetObject(db.CurrentSpaceId, OpenMode.ForRead)
        circ = []
        for oid in ms:
            ent = tx.GetObject(oid, OpenMode.ForRead)
            if isinstance(ent, Circle) and ent.Layer == PTS_LAYER:
                c = ent.Center
                circ.append((c.X, c.Y, round(c.Z, 2), ent.Color.ColorIndex))
        log(f"=== {len(circ)} anchors on {PTS_LAYER} ===")

        # nearest-neighbour distance for each
        nn = []
        for i, a in enumerate(circ):
            best = None
            bj = -1
            for j, b in enumerate(circ):
                if i == j:
                    continue
                dd = math.dist((a[0], a[1]), (b[0], b[1]))
                if best is None or dd < best:
                    best = dd
                    bj = j
            nn.append((best, i, bj))

        dists = sorted(d for d, _, _ in nn)
        log(
            f"nearest-neighbour: min={dists[0]:.2f} "
            f"median={dists[len(dists) // 2]:.2f} max={dists[-1]:.2f}"
        )

        log(f"\n=== pairs closer than {CLOSE} m ===")
        seen = set()
        cnt = 0
        for d, i, j in sorted(nn):
            if d >= CLOSE:
                break
            key = tuple(sorted((i, j)))
            if key in seen:
                continue
            seen.add(key)
            cnt += 1
            a, b = circ[i], circ[j]
            log(
                f"  d={d:.2f}  A(col{a[3]} z{a[2]} {a[0]:.1f},{a[1]:.1f})  "
                f"B(col{b[3]} z{b[2]} {b[0]:.1f},{b[1]:.1f})"
            )
        log(f"\ntotal close pairs: {cnt}")

        log("\n=== all centres (sorted by z, then x) ===")
        for x, y, z, col in sorted(circ, key=lambda c: (c[2], c[0])):
            log(f"  z{z} col{col}  ({x:.2f}, {y:.2f})")

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
