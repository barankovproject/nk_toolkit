"""Number the anchor circles and tag each with a property set (Number, Elevation).

Continuous numbering across all anchors: rows bottom-to-top (by elevation), and
within a row left-to-right. No interactive pick. Re-run safe (re-tags in place).
"""

from __future__ import annotations

import datetime
import os
import traceback
from typing import Any

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import Circle, OpenMode

from anchor_core.config import CONFIG
from anchor_core.property_sets import ensure_anchor_psd, tag_anchor

_HERE = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(_HERE, "logs")

PTS_LAYER = CONFIG.pts_layer  # circles drawn by anchor_04


class AnchorNumberBuilder:
    def __init__(self) -> None:
        os.makedirs(LOG_DIR, exist_ok=True)
        self.log_file = os.path.join(
            LOG_DIR, f"number_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
        )

    def log(self, msg: str = "", level: str = "INFO") -> None:
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(f"{level}: {msg}\n" if level != "INFO" else f"{msg}\n")

    def _collect(self, tx: Any, db: Any) -> list[tuple[Any, float, float, float]]:
        """Return (oid, z, x, y) for every circle on the points layer."""
        out = []
        ms = tx.GetObject(db.CurrentSpaceId, OpenMode.ForRead)
        for oid in ms:
            ent = tx.GetObject(oid, OpenMode.ForRead)
            if isinstance(ent, Circle) and ent.Layer == PTS_LAYER:
                c = ent.Center
                out.append((oid, round(float(c.Z), 3), float(c.X), float(c.Y)))
        return out

    def run(self) -> str:
        self.log("=== anchor_05_number_anchors ===")
        self.log(f"started: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
        self.log(f"points layer: {PTS_LAYER}  PS: Arhyz_Anchor")

        doc = Application.DocumentManager.MdiActiveDocument
        db = doc.Database

        lock = doc.LockDocument()
        try:
            tx = db.TransactionManager.StartTransaction()
            try:
                circles = self._collect(tx, db)
                tx.Commit()
            finally:
                tx.Dispose()

            # Continuous order: by elevation (rows bottom-up), then west-to-east.
            circles.sort(key=lambda c: (c[1], c[2], c[3]))
            self.log(f"anchors: {len(circles)}")

            tx = db.TransactionManager.StartTransaction()
            try:
                psd_id = ensure_anchor_psd(db, tx)
                for i, (oid, z, _x, _y) in enumerate(circles, start=1):
                    ent = tx.GetObject(oid, OpenMode.ForWrite)
                    tag_anchor(ent, psd_id, tx, i, z)
                tx.Commit()
            except Exception:
                tx.Abort()
                raise
            finally:
                tx.Dispose()

            if circles:
                zs = sorted({c[1] for c in circles})
                self.log(f"numbered 1..{len(circles)} across elevations {zs}")
        finally:
            try:
                lock.Dispose()
            except Exception:
                pass

        self.log("=== DONE ===")
        return self.log_file
