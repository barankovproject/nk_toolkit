from __future__ import annotations

from typing import Any, Optional

from Autodesk.AutoCAD.DatabaseServices import OpenMode
from Autodesk.Civil.ApplicationServices import CivilApplication
from Autodesk.Civil.DatabaseServices import Alignment, TinSurface

from civil.utils import find_best_match


def find_alignment_and_surface(
    tx: Any, alignment_name: str, surface_name: str
) -> tuple[Any, Any]:
    """Return (alignment, surface) by fuzzy-matching names against the drawing.

    Names come from config (CONFIG.alignment_name / surface_name); a unique
    fragment is enough. Raises a clear error listing what is available if either
    name is blank or matches nothing.
    """
    if not alignment_name or not surface_name:
        raise Exception(
            "Set CONFIG.alignment_name and CONFIG.surface_name in config.py before running."
        )

    civil_db = CivilApplication.ActiveDocument

    aligns: list[Any] = []
    for oid in civil_db.GetAlignmentIds():
        try:
            ent = tx.GetObject(oid, OpenMode.ForRead)
            if isinstance(ent, Alignment):
                aligns.append(ent)
        except Exception:
            continue
    a_names = [a.Name for a in aligns]
    a_match = find_best_match(alignment_name, a_names)
    if a_match is None:
        raise Exception(
            f"No alignment matching '{alignment_name}'. Available: {a_names}"
        )

    surfaces: list[Any] = []
    for oid in civil_db.GetSurfaceIds():
        try:
            ent = tx.GetObject(oid, OpenMode.ForRead)
            if isinstance(ent, TinSurface):
                surfaces.append(ent)
        except Exception:
            continue
    s_names = [s.Name for s in surfaces]
    s_match = find_best_match(surface_name, s_names)
    if s_match is None:
        raise Exception(
            f"No TIN surface matching '{surface_name}'. Available: {s_names}"
        )

    return aligns[a_match[0]], surfaces[s_match[0]]


def selected_ditch_station(
    trigger: Any, tx: Any, psd_id: Any
) -> Optional[tuple[str, float]]:
    """Return (handle, station) of the ditch a Dynamo ObjectSelection node picked.

    `trigger` is IN[0] from the node — a Dynamo object wrapper; its
    InternalObjectId gives the AcDb entity. Reads the Arhyz_CrossDitch property
    set's Station. Returns None when nothing is selected or it carries no station
    (e.g. a connector/apron line, which has no property set).
    """
    if trigger is None or psd_id is None:
        return None
    try:
        oid = trigger.InternalObjectId
    except Exception:
        return None
    try:
        ent = tx.GetObject(oid, OpenMode.ForRead)
    except Exception:
        return None
    handle = str(ent.Handle)
    try:
        import Autodesk.Aec.PropertyData.DatabaseServices as _PD

        ps_id = _PD.PropertyDataServices.GetPropertySet(ent, psd_id)
        ps = tx.GetObject(ps_id, OpenMode.ForRead)
        sta = float(ps.GetAt(ps.PropertyNameToId("Station")))
    except Exception:
        return None
    return handle, sta
