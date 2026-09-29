"""Apply native slope hatching (бергштрихи) to corridors, Daylight → Channel_Bottom.

For each selected corridor:
  1. Get its first baseline feature-line map.
  2. Pair the FL1_CODE and FL2_CODE feature lines index-by-index.
  3. Clear existing slope patterns and recreate them with the 'Basic' style.

The style id is read once from the drawing's SlopePatternStyles.

SlopeHatchBuilder(query): empty query → all corridors; non-empty → the matching one.
"""

from __future__ import annotations

import datetime
import glob
import os
from typing import Any

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import OpenMode
from Autodesk.Civil.ApplicationServices import CivilApplication

from civil.utils import find_best_match, safe_iter, safe_resolve

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
_LOG_PREFIX = "draw_corridor_slope_hatches"

STYLE_NAME = "Basic"
FL1_CODE = "Daylight"  # top of slope (бровка)
FL2_CODE = "Channel_Bottom"  # bottom of slope (дно котлована)


def _trim_logs(log_dir: str, prefix: str, keep: int = 10) -> None:
    for f in sorted(glob.glob(os.path.join(log_dir, f"{prefix}_*.log")))[:-keep]:
        try:
            os.remove(f)
        except OSError:
            pass


class SlopeHatchBuilder:
    def __init__(self, query: str = "") -> None:
        self.query = (query or "").strip()
        os.makedirs(_LOG_DIR, exist_ok=True)
        _trim_logs(_LOG_DIR, _LOG_PREFIX)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self._log_path = os.path.join(_LOG_DIR, f"{_LOG_PREFIX}_{ts}.log")

    def _log(self, msg: str = "") -> None:
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(msg + "\n")

    def run(self) -> Any:
        log = self._log
        log("=== draw_corridor_slope_hatches ===")
        log(
            f"query={self.query!r}  style={STYLE_NAME!r}  codes: {FL1_CODE!r} / {FL2_CODE!r}"
        )

        doc = Application.DocumentManager.MdiActiveDocument
        db = doc.Database
        civil_db = CivilApplication.ActiveDocument

        results: list[str] = []
        lock = doc.LockDocument()
        try:
            tx = db.TransactionManager.StartTransaction()
            try:
                style_id = self._style_id(civil_db, STYLE_NAME)
                if style_id is None:
                    log(f"ERROR: slope pattern style '{STYLE_NAME}' not found")
                else:
                    cc = civil_db.CorridorCollection
                    corridors: list[Any] = []
                    names: list[str] = []
                    for raw in safe_iter(cc):
                        c = safe_resolve(raw, tx)
                        if c is None:
                            continue
                        corridors.append(c)
                        names.append(c.Name)

                    targets = self._select(corridors, names)
                    log(f"corridors: {len(names)}  selected: {len(targets)}\n")

                    for c in targets:
                        results.append(self._apply_one(c, style_id, tx))
                        log(results[-1])

                tx.Commit()
                log("\ntransaction committed")
            except Exception:
                tx.Abort()
                raise
            finally:
                tx.Dispose()
        finally:
            lock.Dispose()

        ok = sum(1 for r in results if " OK" in r)
        log(f"\n--- {ok}/{len(results)} corridors patched ---")
        log("=== DONE ===")
        return "\n".join(results)

    def _select(self, corridors: list[Any], names: list[str]) -> list[Any]:
        if not self.query:
            return corridors
        match = find_best_match(self.query, names)
        if match is None:
            return []
        return [corridors[match[0]]]

    def _style_id(self, civil_db: Any, style_name: str) -> Any:
        try:
            col = civil_db.Styles.SlopePatternStyles
            if col.Contains(style_name):
                return col.get_Item(style_name)
        except Exception:
            pass
        return None

    @staticmethod
    def _first_offset(fl: Any) -> float:
        for fp in fl.FeatureLinePoints:
            return float(fp.Offset)
        return 0.0

    def _lr(self, fls: list[Any]) -> tuple[Any, Any]:
        """Return (left, right) of the two longest feature lines by offset sign."""
        main = sorted(
            fls, key=lambda fl: len(list(fl.FeatureLinePoints)), reverse=True
        )[:2]
        a, b = main[0], main[1]
        if self._first_offset(a) <= self._first_offset(b):
            return a, b  # a = left (smaller/negative offset), b = right
        return b, a

    def _pairs(self, corr: Any) -> list[tuple]:
        """Pair FL1 (top) with FL2 (bottom) on the SAME side, so hachures don't cross.

        FL1 and FL2 collections can be returned in different left/right order, so they are
        matched by offset sign rather than by raw index.
        """
        bl = list(corr.Baselines)[0]
        fl_map = bl.MainBaselineFeatureLines.FeatureLineCollectionMap
        try:
            fls1 = list(fl_map[FL1_CODE])
            fls2 = list(fl_map[FL2_CODE])
        except Exception:
            return []
        if len(fls1) < 2 or len(fls2) < 2:
            return []
        d_l, d_r = self._lr(fls1)
        b_l, b_r = self._lr(fls2)
        return [(d_l, b_l), (d_r, b_r)]

    def _apply_one(self, corr: Any, style_id: Any, tx: Any) -> str:
        name = corr.Name
        try:
            pairs = self._pairs(corr)
            if not pairs:
                return f"  {name:30s} SKIP (no {FL1_CODE}/{FL2_CODE} feature lines)"
            corr_w = tx.GetObject(corr.ObjectId, OpenMode.ForWrite)
            sp = corr_w.SlopePatterns
            cleared = sp.Count
            while sp.Count > 0:
                sp.RemoveAt(0)
            added = 0
            for fl1, fl2 in pairs:
                sp.Add(fl1, fl2, style_id)
                added += 1
            note = f"  (replaced {cleared})" if cleared else ""
            return f"  {name:30s} OK ({added} patterns added{note})"
        except Exception as e:
            return f"  {name:30s} FAIL: {type(e).__name__}: {e}"
