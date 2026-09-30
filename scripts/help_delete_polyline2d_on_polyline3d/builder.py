from __future__ import annotations

import datetime
import glob
import json
import math
import os
import traceback
from typing import Any

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import OpenMode

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_LOG_DIR = os.path.join(_SCRIPT_DIR, "logs")
_LOG_PREFIX = "delete_flat_pl"

# Layer whitelists live in a UTF-8 sidecar (keeps Cyrillic layer names out of
# the .dyn, which PowerShell-based injection would otherwise corrupt).
_LAYERS_CONFIG = os.path.join(_SCRIPT_DIR, "layers_config.json")


def _load_config_layers() -> tuple[list[str], list[str]]:
    """Read default 2D/3D layer whitelists from the sidecar config, if present."""
    try:
        with open(_LAYERS_CONFIG, encoding="utf-8") as f:
            cfg = json.load(f)
        return list(cfg.get("layers_2d") or []), list(cfg.get("layers_3d") or [])
    except (OSError, ValueError):
        return [], []


# Vertex types that lie OFF the visible curve and must be ignored when
# collecting the plan path of a polyline.
_SKIP_2D_VTYPES = {"SplineControlVertex"}
_SKIP_3D_VTYPES = {"ControlVertex"}

# Type names. 3D reference paths vs flat 2D candidates to erase.
# "Polyline" is the lightweight AcDbPolyline (LWPolyline); "Polyline2d" the
# legacy heavy 2D polyline. Both are flat plan polylines.
_TYPE_3D = "Polyline3d"
_TYPES_2D = ("Polyline", "Polyline2d")

# Defaults (overridable from the launcher).
_DEFAULT_TOL = 0.001  # plan distance for "on the line" (~1 mm)
_DEFAULT_MIN_OVERLAP = 0.1  # min shared run length to count as "lies along" (m)

Path = list[tuple[float, float]]


def _trim_logs(log_dir: str, prefix: str, keep: int = 10) -> None:
    for f in sorted(glob.glob(os.path.join(log_dir, f"{prefix}_*.log")))[:-keep]:
        try:
            os.remove(f)
        except OSError:
            pass


def _seg_overlap_len_xy(
    a1: tuple[float, float],
    a2: tuple[float, float],
    b1: tuple[float, float],
    b2: tuple[float, float],
    tol: float,
) -> float:
    """Length of the collinear overlap of segment a (a1-a2) with segment b
    (b1-b2), measured along a. Returns 0 if b is not collinear with a within
    tol (so a plain crossing yields ~0)."""
    ax, ay = a1
    dx, dy = a2[0] - ax, a2[1] - ay
    seg_len = math.hypot(dx, dy)
    if seg_len <= 1e-12:
        return 0.0
    ux, uy = dx / seg_len, dy / seg_len
    # Both b endpoints must lie on the infinite line through a (perp dist <= tol).
    for px, py in (b1, b2):
        perp = abs((px - ax) * (-uy) + (py - ay) * ux)
        if perp > tol:
            return 0.0
    # Project b endpoints onto a's axis and intersect with a's [0, seg_len] span.
    t1 = (b1[0] - ax) * ux + (b1[1] - ay) * uy
    t2 = (b2[0] - ax) * ux + (b2[1] - ay) * uy
    lo = max(min(t1, t2), 0.0)
    hi = min(max(t1, t2), seg_len)
    return max(0.0, hi - lo)


def _bbox(path: Path) -> tuple[float, float, float, float]:
    xs = [p[0] for p in path]
    ys = [p[1] for p in path]
    return min(xs), min(ys), max(xs), max(ys)


def _bbox_disjoint(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
    tol: float,
) -> bool:
    return (
        a[2] < b[0] - tol or b[2] < a[0] - tol or a[3] < b[1] - tol or b[3] < a[1] - tol
    )


def _overlap_length(
    pts2d: Path, path3d: Path, tol: float, stop_at: float = 0.0
) -> float:
    """Total length of pts2d that runs collinearly along path3d (capped per
    2D segment so it never exceeds that segment's length).

    If ``stop_at`` > 0, returns early as soon as the running total reaches it
    (we only need to know it crossed the min_overlap threshold, not the exact
    length) — this keeps a pathological many-vertex polyline from grinding the
    full O(n_2d * n_3d) product."""
    total = 0.0
    for i in range(len(pts2d) - 1):
        a1, a2 = pts2d[i], pts2d[i + 1]
        seg_len = math.hypot(a2[0] - a1[0], a2[1] - a1[1])
        if seg_len <= 1e-12:
            continue
        seg_ov = 0.0
        for j in range(len(path3d) - 1):
            seg_ov += _seg_overlap_len_xy(a1, a2, path3d[j], path3d[j + 1], tol)
            if seg_ov >= seg_len:
                break
        total += min(seg_ov, seg_len)
        if stop_at > 0.0 and total >= stop_at:
            return total
    return total


class DeleteFlatPolylineBuilder:
    """Erase every Polyline2d whose plan (XY) geometry coincides with the plan
    geometry of some Polyline3d in model space."""

    def __init__(
        self,
        tol: float = _DEFAULT_TOL,
        min_overlap: float = _DEFAULT_MIN_OVERLAP,
        layers_2d: list[str] | None = None,
        layers_3d: list[str] | None = None,
    ) -> None:
        self.tol = float(tol) if tol else _DEFAULT_TOL
        self.min_overlap = float(min_overlap) if min_overlap else _DEFAULT_MIN_OVERLAP
        # Optional layer whitelists. None => fall back to the sidecar config;
        # an explicit (possibly empty) list => use it as-is (empty = no filter).
        cfg_2d, cfg_3d = _load_config_layers()
        if layers_2d is None:
            layers_2d = cfg_2d
        if layers_3d is None:
            layers_3d = cfg_3d
        self.layers_2d = {s.strip() for s in layers_2d if s and s.strip()}
        self.layers_3d = {s.strip() for s in layers_3d if s and s.strip()}
        os.makedirs(_LOG_DIR, exist_ok=True)
        _trim_logs(_LOG_DIR, _LOG_PREFIX)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self._log_path = os.path.join(_LOG_DIR, f"{_LOG_PREFIX}_{ts}.log")

    def _log(self, msg: str, level: str = "INFO") -> None:
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [{level}] {msg}\n")

    def _vertices_xy(
        self, tx: Any, poly: Any, skip_vtypes: set[str], errors: list[str]
    ) -> list[tuple[float, float]]:
        """Collect ordered XY vertex positions of a polyline in WCS plan.

        Handles the lightweight Polyline (AcDbPolyline) via GetPoint3dAt, and
        the complex Polyline2d / Polyline3d via embedded-vertex iteration."""
        pts: list[tuple[float, float]] = []
        # Lightweight polyline: not a complex entity, no embedded vertices.
        if poly.GetType().Name == "Polyline":
            try:
                for i in range(poly.NumberOfVertices):
                    p = poly.GetPoint3dAt(i)  # WCS
                    pts.append((p.X, p.Y))
            except Exception as e:  # noqa: BLE001
                errors.append(f"lwpoly {poly.Handle}: {e}")
            return pts
        # Complex polyline: iterate embedded vertex sub-entities.
        for vid in poly:
            try:
                v = tx.GetObject(vid, OpenMode.ForRead)
                vtype = getattr(v, "VertexType", None)
                if vtype is not None and str(vtype) in skip_vtypes:
                    continue
                pos = v.Position
                pts.append((pos.X, pos.Y))
            except Exception as e:  # noqa: BLE001
                errors.append(f"vertex {vid}: {e}")
        return pts

    def run(self) -> Any:
        log = self._log
        log(f"=== SCRIPT STARTED: tol={self.tol}, min_overlap={self.min_overlap} ===")

        deleted = 0
        errors: list[str] = []

        doc = Application.DocumentManager.MdiActiveDocument
        db = doc.Database

        try:
            lock = doc.LockDocument()
            try:
                tx = db.TransactionManager.StartTransaction()
                try:
                    ms = tx.GetObject(db.CurrentSpaceId, OpenMode.ForRead)

                    # Pass 1: collect XY plan paths (+ bbox) of every Polyline3d.
                    paths3d: list[tuple[Any, Path, tuple[float, ...]]] = []
                    for oid in ms:
                        try:
                            obj = tx.GetObject(oid, OpenMode.ForRead)
                            if obj.GetType().Name != _TYPE_3D:
                                continue
                            if self.layers_3d and obj.Layer not in self.layers_3d:
                                continue
                            path = self._vertices_xy(tx, obj, _SKIP_3D_VTYPES, errors)
                            if len(path) >= 2:
                                paths3d.append((obj.Handle, path, _bbox(path)))
                        except Exception as e:  # noqa: BLE001
                            errors.append(f"read3d {oid}: {e}")
                    log(f"collected {len(paths3d)} Polyline3d plan paths")

                    # Collect 2D polyline ids first so we have a denominator
                    # for the progress heartbeat below.
                    ids_2d = []
                    for oid in ms:
                        o = tx.GetObject(oid, OpenMode.ForRead)
                        if o.GetType().Name not in _TYPES_2D:
                            continue
                        if self.layers_2d and o.Layer not in self.layers_2d:
                            continue
                        ids_2d.append(oid)
                    lyr_msg = (
                        f" on layers {sorted(self.layers_2d)}" if self.layers_2d else ""
                    )
                    log(f"collected {len(ids_2d)} flat 2D polylines to scan{lyr_msg}")

                    # Pass 2: find every flat 2D polyline that runs along a 3D path.
                    ids_to_erase: list[Any] = []
                    n_2d = 0
                    for oid in ids_2d:
                        try:
                            n_2d += 1
                            if n_2d % 200 == 0:
                                log(
                                    f"...scanned {n_2d}/{len(ids_2d)}, "
                                    f"matched {len(ids_to_erase)} so far"
                                )
                            obj = tx.GetObject(oid, OpenMode.ForRead)
                            pts2d = self._vertices_xy(tx, obj, _SKIP_2D_VTYPES, errors)
                            if len(pts2d) < 2:
                                continue
                            box2d = _bbox(pts2d)
                            for h3d, path, box3d in paths3d:
                                if _bbox_disjoint(box2d, box3d, self.tol):
                                    continue
                                ov = _overlap_length(pts2d, path, self.tol)
                                if ov >= self.min_overlap:
                                    ids_to_erase.append(oid)
                                    log(
                                        f"MATCH: {obj.GetType().Name} {obj.Handle} "
                                        f"({len(pts2d)} verts) runs {ov:.3f} m "
                                        f"along Polyline3d {h3d}"
                                    )
                                    break
                        except Exception as e:  # noqa: BLE001
                            errors.append(f"read2d {oid}: {e}")
                    log(
                        f"scanned {n_2d} flat 2D polylines, "
                        f"matched {len(ids_to_erase)} for deletion"
                    )

                    # Pass 3: erase matched Polyline2d entities.
                    for oid in ids_to_erase:
                        try:
                            obj = tx.GetObject(oid, OpenMode.ForWrite)
                            obj.Erase()
                            deleted += 1
                        except Exception as e:  # noqa: BLE001
                            err = f"erase {oid}: {e}"
                            errors.append(err)
                            log(err, "ERROR")

                    tx.Commit()
                except Exception:
                    tx.Abort()
                    raise
                finally:
                    tx.Dispose()
            finally:
                lock.Dispose()

        except Exception as ex:  # noqa: BLE001
            errors.insert(0, f"ERROR: {ex}")
            log(f"ERROR: {ex}", "CRITICAL")
            log(traceback.format_exc(), "CRITICAL")

        log(f"=== DONE: deleted={deleted}, errors={len(errors)} ===")
        return f"deleted {deleted} polyline2d" if not errors else errors
