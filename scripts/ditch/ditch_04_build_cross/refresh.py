from __future__ import annotations

import math
from typing import Any, Callable, Optional

import Autodesk.Aec.PropertyData.DatabaseServices as _PD
from Autodesk.AutoCAD.DatabaseServices import OpenMode, Polyline3d

from ditch_core.config import CONFIG, CROSS_DITCH_LAYER, trasse_for_layer
from ditch_core.property_sets import tag_part

from .volumes import dist3d, volumes_from_length

_LAYER = CROSS_DITCH_LAYER  # "inf_md_ditch" base; per-trasse layers are inf_md_ditch_<trasse>
_LAYER_CONN = "inf_md_connector"
_LAYER_KILLER = "inf_md_killer"
# A connector whose nearest endpoint is within this distance (m) of a ditch end is
# that ditch's apron transition. Ditches sit far apart, so a generous tol is safe
# and tolerates hand-drawn lines that don't snap exactly.
_MATCH_TOL = 1.5

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


def _length(pts: list[Point]) -> float:
    return sum(dist3d(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def _plan_length(pts: list[Point]) -> float:
    """Plan (XY) length over consecutive vertices — the Length2D of the ditch run."""
    return sum(
        math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
        for i in range(len(pts) - 1)
    )


def _load_alignment(tx: Any, log: Callable[..., None]) -> tuple[Any, Any, Any]:
    """Load the config alignment + a station-projector, for Station/ThetaDeg.

    Imported lazily so a drawing without the alignment (or without `civil` on the
    path) still refreshes volumes and the geometry diagnostics — only Station and
    ThetaDeg are skipped. Returns (align, AlignmentWrapper, project_station_fn) or
    (None, None, None) when the alignment can't be resolved.
    """
    try:
        from civil.alignment import AlignmentWrapper
        from ditch_core.selection import find_alignment_and_surface

        from .selection import _project_station

        align, _surface = find_alignment_and_surface(
            tx, CONFIG.alignment_name, CONFIG.surface_name
        )
        align_w = AlignmentWrapper(align, float(align.EndingStation))
        return align, align_w, _project_station
    except Exception as e:
        log(f"alignment unavailable — Station/ThetaDeg left as-is: {e}", "WARN")
        return None, None, None


def _geom_diagnostics(
    pts: list[Point], align: Any, align_w: Any, project: Any
) -> dict[str, float]:
    """Per-ditch diagnostics reconstructed from the drawn 3D polyline.

    Length2D, ZStart (first vertex), ZEnd (last vertex) are exact from the drawn run
    and report it honestly — including a ditch the solver oriented wrong (start below
    end). Slope is the longitudinal grade |ΔZ| / Length2D. Station is the projection
    of the run's plan midpoint onto the alignment; ThetaDeg is the skew of the run off
    the alignment normal (0 = a pure perpendicular cross-ditch). Station/ThetaDeg are
    0.0 when the alignment is unavailable.
    """
    z_start, z_end = pts[0][2], pts[-1][2]
    length_2d = _plan_length(pts)
    slope = abs(z_start - z_end) / length_2d if length_2d > 1e-9 else 0.0

    station = 0.0
    theta_deg = 0.0
    if align_w is not None and project is not None:
        mx = 0.5 * (pts[0][0] + pts[-1][0])
        my = 0.5 * (pts[0][1] + pts[-1][1])
        st = project(align, mx, my)
        if st is not None:
            station = float(st)
            ang = align_w.angle_at(station)
            nx, ny = -math.sin(ang), math.cos(ang)  # alignment normal (cross-axis)
            dx, dy = pts[-1][0] - pts[0][0], pts[-1][1] - pts[0][1]
            dmag = math.hypot(dx, dy)
            if dmag > 1e-9:
                dot = max(0.0, min(1.0, abs((dx * nx + dy * ny) / dmag)))
                theta_deg = math.degrees(math.acos(dot))
    return {
        "Length2D": length_2d,
        "ZStart": z_start,
        "ZEnd": z_end,
        "Slope": slope,
        "Station": station,
        "ThetaDeg": theta_deg,
    }


def _fill_if_zero(ps: Any, name: str, val: float) -> None:
    """Write `val` only when the field is still at its default 0 — so an exact
    build-time value (station/skew/grade from the solver) is never clobbered by a
    geometric reconstruction, but a freshly attached / hand-drawn ditch gets one."""
    if abs(val) <= 1e-12:
        return
    try:
        cur = float(ps.GetAt(ps.PropertyNameToId(name)))
    except Exception:
        cur = 0.0
    if abs(cur) < 1e-9:
        ps.SetAt(ps.PropertyNameToId(name), float(val))


def refresh_volumes(
    ms: Any, tx: Any, psd_id: Any, log: Callable[..., None], part_psd_id: Any = None
) -> int:
    """Recompute the volume PS + diagnostics of every cross-ditch from geometry.

    Works on hand-drawn ditches too (the user redraws lines on inf_md_ditch that
    carry no property set): each Polyline3d on the ditch layer family is a ditch;
    its 3D length is the main run, plus the 3D length of the connector
    (inf_md_connector) whose nearest endpoint is within _MATCH_TOL of a ditch end.
    An apron is counted present only when such a connector is found. A missing
    property set is attached. The trasse (from the layer suffix), Index, Alignment
    and volume fields are always written; Length2D / ZStart / ZEnd are refreshed
    from geometry; Slope / Station / ThetaDeg are filled only when still empty
    (preserving the solver's exact values on built ditches); Status is set to
    "manual" only when blank. Returns how many ditches were updated.

    This is read-geometry / write-PS only — it never moves or reorders geometry.
    A ditch whose start is below its end (apron on the high side) is a build-time
    orientation problem and must be fixed in the solver + rebuilt, not here.
    """
    if psd_id is None:
        return 0

    align, align_w, project = _load_alignment(tx, log)
    align_label = align.Name if align is not None else CONFIG.alignment_name

    # (ent, start, end, length) — ent kept so the part PSD can be written on it
    connectors: list[tuple[Any, Point, Point, float]] = []
    killers: list[tuple[Any, list[Point]]] = []  # (ent, verts)
    ditches: list[
        tuple[Any, list[Point], float, str]
    ] = []  # (ent, verts, L_main, trasse)

    for oid in ms:
        try:
            ent = tx.GetObject(oid, OpenMode.ForRead)
        except Exception:
            continue
        if not isinstance(ent, Polyline3d):
            continue
        layer = ent.Layer
        if layer == _LAYER_CONN or layer.startswith(_LAYER_CONN + "_"):
            pts = _verts(ent, tx)
            if len(pts) >= 2:
                connectors.append((ent, pts[0], pts[-1], _length(pts)))
            continue
        if layer == _LAYER_KILLER or layer.startswith(_LAYER_KILLER + "_"):
            pts = _verts(ent, tx)
            if len(pts) >= 2:
                killers.append((ent, pts))
            continue
        trasse = trasse_for_layer(layer, _LAYER)
        if trasse is None:  # not a cross-ditch layer
            continue
        pts = _verts(ent, tx)
        if len(pts) >= 2:
            ditches.append((ent, pts, _length(pts), trasse))

    updated = 0
    per_trasse: dict[str, int] = {}  # 1-based ditch index within each trasse
    for ent, pts, l_main, trasse in ditches:
        index = per_trasse[trasse] = per_trasse.get(trasse, 0) + 1
        d_start, d_end = pts[0], pts[-1]
        conn_match: Optional[tuple[Any, Point, Point, float]] = None
        best = _MATCH_TOL
        for c in connectors:
            _ent_c, c_start, c_end, _c_len = c
            d = min(
                dist3d(c_start, d_start),
                dist3d(c_start, d_end),
                dist3d(c_end, d_start),
                dist3d(c_end, d_end),
            )
            if d <= best:
                best = d
                conn_match = c
        has_killer = conn_match is not None
        match_len = conn_match[3] if conn_match is not None else 0.0
        total_l = l_main + match_len
        vols = volumes_from_length(total_l, has_killer)
        _tag_parts(
            part_psd_id,
            tx,
            trasse,
            align_label,
            index,
            d_start,
            d_end,
            conn_match,
            killers,
        )
        diag = _geom_diagnostics(pts, align, align_w, project)
        try:
            self_ps_id = _get_or_add_ps(ent, psd_id)
            ps = tx.GetObject(self_ps_id, OpenMode.ForWrite)
            ps.SetAt(ps.PropertyNameToId("Canal"), trasse)
            ps.SetAt(ps.PropertyNameToId("Index"), int(index))
            ps.SetAt(ps.PropertyNameToId("Alignment"), align_label)
            # exact-from-geometry diagnostics — always refresh
            for name in ("Length2D", "ZStart", "ZEnd"):
                ps.SetAt(ps.PropertyNameToId(name), float(diag[name]))
            # reconstructed diagnostics — fill only when still missing
            for name in ("Slope", "Station", "ThetaDeg"):
                _fill_if_zero(ps, name, diag[name])
            try:
                if not str(ps.GetAt(ps.PropertyNameToId("Status"))).strip():
                    ps.SetAt(ps.PropertyNameToId("Status"), "manual")
            except Exception:
                pass
            for name, val in vols.items():
                ps.SetAt(ps.PropertyNameToId(name), float(val))
            updated += 1
            log(
                f"  [{trasse}] #{index:>2} L3D={total_l:.2f}{' +apron' if has_killer else ''} "
                f"L2D={diag['Length2D']:.2f} sta={diag['Station']:.2f} "
                f"θ={diag['ThetaDeg']:.0f}° slope={diag['Slope']:.3f} "
                f"exc={vols['VolExcavation']:.2f} stone={vols['VolStone']:.2f} "
                f"geo={vols['VolGeotextile']:.2f} move={vols['MoveTonnage']:.2f}"
            )
        except Exception as e:
            log(f"  #{index}: PS update failed: {e}", "WARN")

    log(f"refresh: {len(ditches)} ditch(es), {len(connectors)} connector(s)")
    return updated


def _tag_parts(
    part_psd_id: Any,
    tx: Any,
    trasse: str,
    align_label: str,
    index: int,
    d_start: Point,
    d_end: Point,
    conn_match: Optional[tuple[Any, Point, Point, float]],
    killers: list[tuple[Any, list[Point]]],
) -> None:
    """Write the Arhyz_CrossDitchPart identity PSD on this ditch's connector + killer.

    Authoritative re-tag: the part inherits the run's per-trasse trasse + index. The
    killer is found by walking run_end → [connector] → killer (nearest endpoint ≤
    _MATCH_TOL), so it is linked even when it sits on the base layer or was hand-drawn.
    """
    if part_psd_id is None:
        return

    def _tag(ent: Any, part_type: str) -> None:
        try:
            tag_part(
                ent,
                part_psd_id,
                tx,
                canal=trasse,
                alignment=align_label,
                ditch_index=index,
                part_type=part_type,
            )
        except Exception:
            pass

    anchors: list[Point] = [d_start, d_end]
    if conn_match is not None:
        ent_c, c_start, c_end, _ = conn_match
        _tag(ent_c, "connector")
        # advance the killer-search anchor to the connector end away from the ditch
        near_start = min(dist3d(c_start, d_start), dist3d(c_start, d_end))
        near_end = min(dist3d(c_end, d_start), dist3d(c_end, d_end))
        anchors.append(c_end if near_start <= near_end else c_start)

    best = _MATCH_TOL
    kill_match: Optional[Any] = None
    for ent_k, kverts in killers:
        for a in anchors:
            dmin = min(dist3d(p, a) for p in kverts)
            if dmin <= best:
                best = dmin
                kill_match = ent_k
    if kill_match is not None:
        _tag(kill_match, "killer")


def _get_or_add_ps(ent: Any, psd_id: Any) -> Any:
    """Return the entity's Arhyz_CrossDitch PS id, attaching the set if missing."""
    try:
        return _PD.PropertyDataServices.GetPropertySet(ent, psd_id)
    except Exception:
        ent.UpgradeOpen()
        _PD.PropertyDataServices.AddPropertySet(ent, psd_id)
        return _PD.PropertyDataServices.GetPropertySet(ent, psd_id)
