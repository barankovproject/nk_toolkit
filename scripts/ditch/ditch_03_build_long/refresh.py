from __future__ import annotations

import math
from typing import Any, Callable

import Autodesk.Aec.PropertyData.DatabaseServices as _PD
from Autodesk.AutoCAD.DatabaseServices import OpenMode, Polyline3d

from ditch_core.config import SOURCE_LAYER, trasse_for_layer

from .volumes import ld_volumes

# Longitudinal ditches and ditch_01's cut-toe lines BOTH live on the SOURCE_LAYER
# family (inf_ct_toe and its per-trasse layers inf_ct_toe_<trasse>). The build tags
# ditches ARHYZ_LD and cut-toe lines ARHYZ_CT, so a Polyline3d on the layer is a
# ditch unless it carries the cut-toe tag — that is the only reliable discriminator
# (a hand-redrawn ditch may carry neither tag). The trasse comes from the layer
# suffix (see trasse_for_layer); cut-toe lines only ever sit on the bare base layer.
_TAG_LD = "ARHYZ_LD"
_TAG_CT = "ARHYZ_CT"

Point = tuple[float, float, float]


def _verts(pl: Any, tx: Any) -> list[Point]:
    """World (x, y, z) of every vertex of a Polyline3d, in order."""
    pts: list[Point] = []
    for vid in pl:
        try:
            p = tx.GetObject(vid, OpenMode.ForRead).Position
            pts.append((float(p.X), float(p.Y), float(p.Z)))
        except Exception:
            continue
    return pts


def _length3d(pts: list[Point]) -> float:
    """Total 3D length over consecutive vertices."""
    return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def _plan_turns(pts: list[Point], closed: bool, eps_deg: float = 5.0) -> int:
    """Count plan bends — interior vertices whose XY deflection exceeds eps_deg.

    Mirrors LongitudinalDitchBuilder._plan_turns so a refresh reproduces the
    build-time turn count exactly: a near-collinear vertex is not a turn, and for
    a closed polyline the wrap-around vertex is also checked.
    """
    n = len(pts)
    if n < 3:
        return 0
    eps = math.radians(eps_deg)

    def ang(a: Point, b: Point) -> float:
        return math.atan2(b[1] - a[1], b[0] - a[0])

    def deflect(i: int) -> float:
        d = ang(pts[i], pts[i + 1]) - ang(pts[i - 1], pts[i])
        while d > math.pi:
            d -= 2 * math.pi
        while d < -math.pi:
            d += 2 * math.pi
        return abs(d)

    turns = sum(1 for i in range(1, n - 1) if deflect(i) > eps)
    if closed and deflect(0) > eps:  # wrap-around at the closing vertex
        turns += 1
    return turns


def _is_tagged(ent: Any, app: str) -> bool:
    """True if the entity carries the given XData application tag."""
    try:
        return ent.GetXDataForApplication(app) is not None
    except Exception:
        return False


def _get_or_add_ps(ent: Any, psd_id: Any) -> Any:
    """Return the entity's Arhyz_LongDitch PS id, attaching the set if missing."""
    try:
        return _PD.PropertyDataServices.GetPropertySet(ent, psd_id)
    except Exception:
        ent.UpgradeOpen()
        _PD.PropertyDataServices.AddPropertySet(ent, psd_id)
        return _PD.PropertyDataServices.GetPropertySet(ent, psd_id)


def refresh_long_volumes(
    ms: Any, tx: Any, psd_id: Any, log: Callable[..., None]
) -> int:
    """Recompute the volume PS of every longitudinal ditch from current geometry.

    Run after manually editing 3D ditch polylines on inf_ct_toe: each Polyline3d
    on SOURCE_LAYER that is NOT a cut-toe line (ARHYZ_CT) is a ditch. Its 3D
    length and plan-turn count are read live and fed to ld_volumes, then the
    Arhyz_LongDitch fields (Canal, Index, Length3D + quantities) are rewritten; a
    missing property set is attached first. Geometry is never modified — re-draping
    is the builder's job. Returns how many ditches were updated.
    """
    if psd_id is None:
        return 0

    # (ent, verts, closed, trasse)
    ditches: list[tuple[Any, list[Point], bool, str]] = []
    for oid in ms:
        try:
            ent = tx.GetObject(oid, OpenMode.ForRead)
        except Exception:
            continue
        if not isinstance(ent, Polyline3d):
            continue
        trasse = trasse_for_layer(ent.Layer, SOURCE_LAYER)
        if trasse is None:  # not a longitudinal-ditch layer
            continue
        if _is_tagged(ent, _TAG_CT):  # cut-toe line on the shared layer — skip
            continue
        pts = _verts(ent, tx)
        if len(pts) >= 2:
            ditches.append((ent, pts, bool(getattr(ent, "Closed", False)), trasse))

    updated = 0
    per_trasse: dict[str, int] = {}  # 1-based ditch index within each trasse
    for ent, pts, closed, trasse in ditches:
        index = per_trasse[trasse] = per_trasse.get(trasse, 0) + 1
        length_3d = _length3d(pts)
        n_turns = _plan_turns(pts, closed)
        vols = ld_volumes(length_3d, n_turns)
        try:
            ps_id = _get_or_add_ps(ent, psd_id)
            ps = tx.GetObject(ps_id, OpenMode.ForWrite)
            ps.SetAt(ps.PropertyNameToId("Canal"), trasse)
            ps.SetAt(ps.PropertyNameToId("Index"), int(index))
            ps.SetAt(ps.PropertyNameToId("Length3D"), float(length_3d))
            for name, val in vols.items():
                ps.SetAt(ps.PropertyNameToId(name), float(val))
            updated += 1
            log(
                f"  [{trasse}] #{index:>2} L3D={length_3d:.2f} turns={n_turns} "
                f"exc={vols['VolExcavation']:.2f} stone={vols['VolStone']:.2f} "
                f"geo={vols['VolGeotextile']:.2f} move={vols['MoveTonnage']:.2f} "
                f"mat={vols['MatCount']:.1f}шт/{vols['MatArea']:.1f}m2 "
                f"anch={vols['AnchorCount']:.1f}"
            )
        except Exception as e:
            log(f"  #{index}: PS update failed: {e}", "WARN")

    log(f"refresh: {len(ditches)} longitudinal ditch(es)")
    return updated
