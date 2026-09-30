from __future__ import annotations

import clr

clr.AddReference("AecPropDataMgd")
clr.AddReference("acdbmgd")

import csv
import os
import traceback
from collections import defaultdict
from contextlib import contextmanager
from typing import Any

import Autodesk.Aec.PropertyData.DatabaseServices as _PD
from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import OpenMode, Solid3d

from paths import REPORTS_DIR

from .logger import Logger

_STONE_COEF = 1.05


@contextmanager
def _read_tx(db: Any):
    tx = db.TransactionManager.StartTransaction()
    try:
        yield tx
    finally:
        tx.Abort()
        tx.Dispose()


def _psd_id(dpsd: Any, name: str) -> Any:
    return dpsd.GetAt(name) if name in list(dpsd.NamesInUse) else None


def _ps_read(tx: Any, ent: Any, psd_id: Any) -> Any:
    try:
        ps_id = _PD.PropertyDataServices.GetPropertySet(ent, psd_id)
        return tx.GetObject(ps_id, OpenMode.ForRead)
    except Exception:
        return None


def _get(ps: Any, field: str, default: Any = None) -> Any:
    try:
        return ps.GetAt(ps.PropertyNameToId(field))
    except Exception:
        return default


class StoneSummarizer:
    """Scans all Solid3d in the active drawing and totals stone volumes per canal."""

    def __init__(self, log_keep: int = 10) -> None:
        self.log = Logger(keep=log_keep)

    def run(self) -> str:
        log = self.log
        log("=== STONE SUMMARY STARTED ===")

        try:
            doc = Application.DocumentManager.MdiActiveDocument
            db = doc.Database

            with _read_tx(db) as tx:
                dpsd = _PD.DictionaryPropertySetDefinitions(db)
                gabion_id = _psd_id(dpsd, "Arhyz_Gabion")
                rib_id = _psd_id(dpsd, "Arhyz_Rib")

                if gabion_id is None and rib_id is None:
                    raise Exception(
                        "No Arhyz property sets in drawing — run canal_model first"
                    )

                gabion_vol: dict[str, float] = defaultdict(float)
                rib_vol: dict[str, float] = defaultdict(float)
                anchors: dict[str, int] = defaultdict(int)
                geotextile: dict[str, float] = defaultdict(float)

                ms = tx.GetObject(db.CurrentSpaceId, OpenMode.ForRead)
                for eid in ms:
                    try:
                        ent = tx.GetObject(eid, OpenMode.ForRead)
                        if not isinstance(ent, Solid3d):
                            continue

                        if gabion_id is not None:
                            ps = _ps_read(tx, ent, gabion_id)
                            if ps is not None:
                                canal = str(_get(ps, "Canal", "") or "")
                                if canal:
                                    gabion_vol[canal] += float(
                                        _get(ps, "FillVolume", 0.0) or 0.0
                                    )
                                    anchors[canal] += int(
                                        _get(ps, "AnchorCount", 0) or 0
                                    )
                                    geotextile[canal] += float(
                                        _get(ps, "GeotextileArea", 0.0) or 0.0
                                    )

                        if rib_id is not None:
                            ps = _ps_read(tx, ent, rib_id)
                            if ps is not None:
                                canal = str(_get(ps, "Canal", "") or "")
                                vol = float(_get(ps, "Volume", 0.0) or 0.0)
                                if canal:
                                    rib_vol[canal] += vol

                    except Exception:
                        continue

            all_canals = sorted(set(gabion_vol) | set(rib_vol))
            log(f"canals found: {all_canals}")

            _GEOTEXTILE_COEF = 1.2
            rows: list[tuple[str, float, float, float, int, float]] = []
            for canal in all_canals:
                g = round(gabion_vol.get(canal, 0.0) * _STONE_COEF, 3)
                r = round(rib_vol.get(canal, 0.0) * _STONE_COEF, 3)
                a = anchors.get(canal, 0)
                gt = round(geotextile.get(canal, 0.0) * _GEOTEXTILE_COEF, 2)
                rows.append((canal, g, r, round(g + r, 3), a, gt))

            total_g = round(sum(r[1] for r in rows), 3)
            total_r = round(sum(r[2] for r in rows), 3)
            total = round(total_g + total_r, 3)
            total_a = sum(r[4] for r in rows)
            total_gt = round(sum(r[5] for r in rows), 2)

            out_path = self._write_csv(rows, total_g, total_r, total, total_a, total_gt)
            log(
                f"total gabion={total_g} rib={total_r} sum={total} anchors={total_a} geotextile={total_gt}"
            )
            log(f"report saved: {out_path}")

        except Exception as ex:
            log(f"ERROR: {ex}", "CRITICAL")
            log(traceback.format_exc(), "CRITICAL")
            return f"ERROR: {ex}"

        log("=== DONE ===")
        return out_path

    def _write_csv(
        self,
        rows: list[tuple[str, float, float, float, int, float]],
        total_g: float,
        total_r: float,
        total: float,
        total_a: int,
        total_gt: float,
    ) -> str:
        header = [
            "Канава",
            "Камень ГСИ 190мм * 1.05, м³",
            "Камень ребра 110мм * 1.05, м³",
            "Итого камень, м³",
            "Анкеры, шт.",
            "Геотекстиль * 1.2, м²",
        ]
        out_rows = [header]
        for canal, g, r, t, a, gt in rows:
            out_rows.append([canal, g, r, t, a, gt])
        out_rows.append(["ИТОГО", total_g, total_r, total, total_a, total_gt])

        os.makedirs(REPORTS_DIR, exist_ok=True)
        out_path = os.path.join(REPORTS_DIR, "stone_summary.csv")
        try:
            with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
                csv.writer(f, delimiter=";").writerows(out_rows)
        except PermissionError:
            import datetime

            ts = datetime.datetime.now().strftime("%H%M%S")
            out_path = os.path.join(REPORTS_DIR, f"stone_summary_{ts}.csv")
            with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
                csv.writer(f, delimiter=";").writerows(out_rows)
        return out_path
