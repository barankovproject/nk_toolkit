"""CorridorBuilder: build a Civil 3D Corridor for one canal from its JSON config."""

from __future__ import annotations

import clr
import datetime
import json
import os
import sys
import traceback
from typing import Any, Optional

clr.AddReference("AecBaseMgd")
clr.AddReference("AeccDbMgd")
clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import ObjectIdCollection, OpenMode
from Autodesk.Civil.ApplicationServices import CivilApplication
from Autodesk.Civil.DatabaseServices import Profile

_LIB_ROOT = r"C:\Arhyz\automation\scripts"
_AUTOMATION_ROOT = os.path.dirname(_LIB_ROOT)
for _p in (_LIB_ROOT, _AUTOMATION_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from civil.utils import find_best_match, pk_to_sta, safe_iter, safe_resolve  # noqa: E402
from paths import CANALS_DIR as CONFIG_DIR  # noqa: E402
from paths import TYPES_FILE  # noqa: E402

LOG_DIR = r"C:\Arhyz\automation\scripts\build_corridors\logs"

SURFACE_QUERY = "Земля (новая)"
_SURFACE_KW = ("поверхность", "земля", "коридор")

TYPE_TO_ASSEMBLY: dict[str, str] = {
    "1": "500x500_170",
    "2": "600x600_170",
    "3": "750x750_300",
    "4": "1500x750_170 (2)",
    "5": "1500x750_500",
    "6": "4000x750_500",
    "7": "7000x1500_500",
    "8": "10000x2000_500",
}
GABION_TYPES: set[str] = set(TYPE_TO_ASSEMBLY.keys())
TROUGH_TYPES: set[str] = {"9", "10", "11", "12"}

CODE_SET_STYLE_NAME = "All Codes"


class CorridorBuilder:
    """Build (or skip) a Civil 3D Corridor for *canal_name* from its JSON config."""

    def __init__(self, canal_name: str) -> None:
        self.canal_name = str(canal_name).strip()
        os.makedirs(LOG_DIR, exist_ok=True)
        log_file = os.path.join(
            LOG_DIR, f"corridor_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
        )
        self._log_file = log_file

    def log(self, msg: str = "") -> None:
        with open(self._log_file, "a", encoding="utf-8") as f:
            f.write(msg + "\n")

    # ------------------------------------------------------------------
    # public entry point
    # ------------------------------------------------------------------

    def run(self) -> str:
        """Build corridor for self.canal_name. Returns one-line status string."""
        self.log(f"=== CorridorBuilder: {self.canal_name} ===")
        self.log(f"started: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")

        cfg_path = os.path.join(CONFIG_DIR, f"{self.canal_name}.json")
        if not os.path.exists(cfg_path):
            return f"FAIL: config not found: {cfg_path}"
        with open(cfg_path, encoding="utf-8-sig") as f:
            cfg = json.load(f)

        with open(TYPES_FILE, encoding="utf-8-sig") as f:
            cfg_types = json.load(f)["types"]

        doc = Application.DocumentManager.MdiActiveDocument
        db = doc.Database
        civil_db = CivilApplication.ActiveDocument

        status = "FAIL: unknown"
        lock = doc.LockDocument()
        try:
            tx = db.TransactionManager.StartTransaction()
            try:
                surf_id, surf = self._find_surface(civil_db, tx, SURFACE_QUERY)
                self.log(
                    f"surface: '{surf.Name}' id={surf_id}"
                    if surf
                    else "surface: NOT FOUND (daylight slopes won't build)"
                )
                status = self._build(cfg, civil_db, tx, db, cfg_types, surf_id)
                tx.Commit()
                self.log("transaction committed")
            except Exception as e:
                self.log(f"\nERROR: {e}\n{traceback.format_exc()}")
                status = f"FAIL: {type(e).__name__}: {e}"
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

        self.log(f"\nresult: {status}")
        self.log("=== DONE ===")
        return status

    # ------------------------------------------------------------------
    # corridor construction
    # ------------------------------------------------------------------

    def _build(
        self,
        cfg: dict[str, Any],
        civil_db: Any,
        tx: Any,
        db: Any,
        cfg_types: dict[str, Any],
        surf_id: Any,
    ) -> str:
        segments = cfg.get("segments", [])
        seg_types = [str(s["type"]) for s in segments]
        unknown = [
            t for t in seg_types if t not in GABION_TYPES and t not in TROUGH_TYPES
        ]
        if unknown:
            return f"SKIP (unknown types {sorted(set(unknown))})"

        effective_types: list[str] = []
        last_gabion: Optional[str] = None
        for st in seg_types:
            if st in GABION_TYPES:
                last_gabion = st
                effective_types.append(st)
            else:
                if last_gabion is None:
                    return f"SKIP (starts with trough type {st}, no prior gabion)"
                effective_types.append(last_gabion)

        align_id, align = self._find_alignment(civil_db, tx, self.canal_name)
        if align is None:
            return f"FAIL: alignment for '{self.canal_name}' not found"
        profile_id, profile = self._find_design_profile(tx, align)
        if profile is None:
            return "FAIL: design profile not found"

        sta_start = float(align.StartingStation)
        sta_end = float(align.EndingStation)
        corridor_name = align.Name

        cc = civil_db.CorridorCollection
        if self._find_corridor_by_name(cc, tx, corridor_name) is not None:
            return f"SKIP (corridor '{corridor_name}' exists)"

        ac = civil_db.AssemblyCollection
        n_segs = len(segments)
        has_widening = cfg.get("widening") is not None
        trans_start = (
            sta_end - float(cfg["widening"]["length"]) if has_widening else sta_end
        )

        def seg_effective_end(idx: int) -> float:
            if idx == n_segs - 1 and has_widening:
                return trans_start
            raw = pk_to_sta(segments[idx]["to"])
            return min(raw, sta_end)

        first_asm_name = TYPE_TO_ASSEMBLY[effective_types[0]]
        first_asm_id = self._find_assembly_id(ac, tx, first_asm_name)
        if first_asm_id is None:
            return f"FAIL: assembly '{first_asm_name}' not found"

        baseline_name = f"BL - {self.canal_name}"
        first_region_name = f"RG - {first_asm_name} [1]"

        new_corr_id = cc.Add(
            corridor_name,
            baseline_name,
            align_id,
            profile_id,
            first_region_name,
            first_asm_id,
        )
        try:
            corr = tx.GetObject(new_corr_id, OpenMode.ForWrite)

            # set code set style
            self._apply_code_set_style(corr, db, tx, cc)

            bl = None
            for raw_b in safe_iter(corr.Baselines):
                bl = safe_resolve(raw_b, tx)
                break
            if bl is None:
                raise RuntimeError("no baseline created")
            regions = bl.BaselineRegions

            first_region = None
            for raw_r in safe_iter(regions):
                first_region = safe_resolve(raw_r, tx)
                break

            if n_segs > 1 or has_widening:
                end0 = seg_effective_end(0)
                if end0 <= sta_start + 1e-6:
                    raise RuntimeError(
                        f"first segment effective end {end0:.3f} <= sta_start"
                    )
                first_region.EndStation = end0
                seg_prev_end = end0
            else:
                seg_prev_end = sta_end

            for i in range(1, n_segs):
                asm_name = TYPE_TO_ASSEMBLY[effective_types[i]]
                asm_id = self._find_assembly_id(ac, tx, asm_name)
                if asm_id is None:
                    raise RuntimeError(f"assembly '{asm_name}' not found mid-build")
                seg_end = seg_effective_end(i)
                if seg_end <= seg_prev_end + 1e-6:
                    raise RuntimeError(
                        f"segment[{i}] end {seg_end:.3f} <= prev {seg_prev_end:.3f}"
                    )
                rname = f"RG - {asm_name} [{i + 1}]"
                regions.Add(rname, asm_id, seg_prev_end, seg_end)
                seg_prev_end = seg_end

            if has_widening:
                w = cfg["widening"]
                w_b = float(w["b"])
                w_asm = self._widening_asm_name(last_gabion, w_b, cfg_types)
                w_asm_id = self._find_assembly_id(ac, tx, w_asm)
                if w_asm_id is None:
                    raise RuntimeError(f"widening assembly '{w_asm}' not found")
                if sta_end <= seg_prev_end + 1e-6:
                    raise RuntimeError(
                        f"widening start {seg_prev_end:.3f} >= sta_end {sta_end:.3f}"
                    )
                w_rname = f"RG - {w_asm} [widening]"
                regions.Add(w_rname, w_asm_id, seg_prev_end, sta_end)

        except Exception as e:
            try:
                w = tx.GetObject(new_corr_id, OpenMode.ForWrite)
                w.Erase()
            except Exception:
                pass
            return f"FAIL ({type(e).__name__}: {e})"

        for raw_r in safe_iter(bl.BaselineRegions):
            rg = safe_resolve(raw_r, tx)
            if rg is None:
                continue
            try:
                self._apply_frequency_settings(rg)
            except Exception as e:
                return f"PARTIAL: freq err: {e}"
            if surf_id is not None:
                try:
                    self._apply_surface_target(rg, surf_id)
                except Exception as e:
                    return f"PARTIAL: surface target err: {e}"

        try:
            corr.Rebuild()
        except Exception as e:
            return f"PARTIAL: rebuild err: {e}"

        return (
            f"OK  ({n_segs} segments + {'widening' if has_widening else 'no widening'})"
        )

    # ------------------------------------------------------------------
    # style helpers
    # ------------------------------------------------------------------

    def _apply_code_set_style(self, corr: Any, db: Any, tx: Any, cc: Any) -> None:
        css_id = self._find_code_set_style_id(db, tx, CODE_SET_STYLE_NAME)
        if css_id is None:
            ref_id = self._find_corridor_by_name(cc, tx, "НК-2D-1_")
            if ref_id is not None:
                try:
                    css_id = tx.GetObject(ref_id, OpenMode.ForRead).CodeSetStyleId
                except Exception:
                    pass
        if css_id is not None:
            try:
                corr.CodeSetStyleId = css_id
            except Exception as e:
                self.log(f"  warn: CodeSetStyleId set failed: {e}")
        else:
            self.log(f"  warn: code set style '{CODE_SET_STYLE_NAME}' not found")

    def _find_code_set_style_id(self, db: Any, tx: Any, name: str) -> Any:
        try:
            from Autodesk.Civil.ApplicationServices import CivilApplication

            css_col = CivilApplication.ActiveDocument.Styles.CodeSetStyles
            if css_col.Contains(name):
                return css_col.get_Item(name)
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # Civil 3D lookup helpers
    # ------------------------------------------------------------------

    def _find_assembly_id(self, ac: Any, tx: Any, name: str) -> Any:
        for raw in safe_iter(ac):
            asm = safe_resolve(raw, tx)
            if asm is None:
                continue
            try:
                if asm.Name == name:
                    return raw
            except Exception:
                continue
        return None

    def _find_alignment(self, civil_db: Any, tx: Any, query: str) -> tuple[Any, Any]:
        objs = []
        for oid in civil_db.GetAlignmentIds():
            try:
                objs.append((oid, tx.GetObject(oid, OpenMode.ForRead)))
            except Exception:
                continue
        names = [a.Name for _, a in objs]
        result = find_best_match(query, names)
        if result is None:
            return None, None
        idx, _ = result
        return objs[idx][0], objs[idx][1]

    def _find_design_profile(self, tx: Any, align: Any) -> tuple[Any, Any]:
        pids = []
        for pid in align.GetProfileIds():
            try:
                p = tx.GetObject(pid, OpenMode.ForRead)
                if isinstance(p, Profile) and not any(
                    kw in p.Name.lower() for kw in _SURFACE_KW
                ):
                    pids.append((pid, p))
            except Exception:
                continue
        if not pids:
            return None, None
        return pids[0]

    def _find_surface(self, civil_db: Any, tx: Any, query: str) -> tuple[Any, Any]:
        surfs = []
        for oid in civil_db.GetSurfaceIds():
            try:
                s = tx.GetObject(oid, OpenMode.ForRead)
                surfs.append((oid, s, s.Name))
            except Exception:
                continue
        if not surfs:
            return None, None
        if not query:
            return surfs[0][0], surfs[0][1]
        names = [n for _, _, n in surfs]
        result = find_best_match(query, names)
        if result is None:
            return None, None
        idx, _ = result
        return surfs[idx][0], surfs[idx][1]

    def _find_corridor_by_name(self, cc: Any, tx: Any, name: str) -> Any:
        for raw in safe_iter(cc):
            c = safe_resolve(raw, tx)
            if c is None:
                continue
            try:
                if c.Name == name:
                    return raw
            except Exception:
                continue
        return None

    def _widening_asm_name(
        self, last_gabion_type: str, b: float, cfg_types: dict[str, Any]
    ) -> str:
        tp = cfg_types[last_gabion_type]
        d_mm = int(round(float(tp["d"]) * 1000))
        t_mm = int(round(float(tp["t"]) * 1000))
        bw_mm = int(round(b * 1000))
        return f"{bw_mm}x{d_mm}_{t_mm}"

    # ------------------------------------------------------------------
    # region settings helpers
    # ------------------------------------------------------------------

    def _apply_frequency_settings(self, region: Any) -> None:
        aas = region.AppliedAssemblySetting
        aas.FrequencyAlongTangents = 2.0
        aas.FrequencyAlongCurves = 2.0
        aas.FrequencyAlongSpirals = 2.0
        aas.FrequencyAlongProfileCurves = 2.0
        aas.FrequencyAlongTargetCurves = 25.0
        aas.CorridorAlongCurvesOption = 2  # CurveByCurvature
        aas.MODAlongCurves = 0.1
        aas.MODAlongTargetCurves = 0.1
        aas.AppliedAtHorizontalGeometryPoints = True
        aas.AppliedAtProfileGeometryPoints = True
        aas.AppliedAtProfileHighLowPoints = True
        aas.AppliedAtSuperelevationCriticalPoints = True
        aas.AppliedAtOffsetTargetGeometryPoints = True
        aas.AppliedAdjacentToOffsetTargetStartEnd = True

    def _apply_surface_target(self, region: Any, surface_id: Any) -> int:
        targets = region.GetTargets()
        set_count = 0
        for tinfo in safe_iter(targets):
            if tinfo is None:
                continue
            try:
                ttype = str(tinfo.TargetType)
            except Exception:
                continue
            if ttype == "1":
                try:
                    new_ids = ObjectIdCollection()
                    new_ids.Add(surface_id)
                    tinfo.TargetIds = new_ids
                    set_count += 1
                except Exception:
                    pass
        if set_count > 0:
            region.SetTargets(targets)
        return set_count
