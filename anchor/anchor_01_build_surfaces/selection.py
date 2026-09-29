"""Resolve the two Dynamo "Select Object" inputs into ground + boundary oids.

The graph feeds two AutoCAD ObjectSelection nodes into IN[0]/IN[1]. Their output
is a Dynamo wrapper object, not an ObjectId, so we unwrap it first. Order is not
assumed: the picks are classified by type (TinSurface -> ground, Polyline ->
boundary), so the user may select them in either order.
"""

from __future__ import annotations

from typing import Any

from Autodesk.AutoCAD.DatabaseServices import Handle, OpenMode, Polyline
from Autodesk.Civil.DatabaseServices import TinSurface


def resolve_object_id(db: Any, dyn_obj: Any) -> Any:
    """Unwrap a Dynamo AutoCAD object (or handle) into an AutoCAD ObjectId.

    Tries the common wrapper accessors in turn, then falls back to resolving a
    handle string. Raises a clear error if nothing yields an ObjectId.
    """
    if dyn_obj is None:
        raise Exception("A selection input is empty — pick an object for it.")

    # Already an ObjectId.
    if hasattr(dyn_obj, "IsNull") and hasattr(dyn_obj, "Handle"):
        return dyn_obj

    # Dynamo AutoCAD Object wrapper.
    for attr in ("InternalObjectId", "Id"):
        oid = getattr(dyn_obj, attr, None)
        if oid is not None and hasattr(oid, "IsNull"):
            return oid

    inner = getattr(dyn_obj, "InternalDBObject", None)
    if inner is not None:
        oid = getattr(inner, "ObjectId", None) or getattr(inner, "Id", None)
        if oid is not None and hasattr(oid, "IsNull"):
            return oid

    # Handle string fallback (e.g. "1A4F").
    h = getattr(dyn_obj, "Handle", None)
    if h is None and isinstance(dyn_obj, str):
        h = dyn_obj
    if h is not None:
        try:
            return db.GetObjectId(False, Handle(int(str(h), 16)), 0)
        except Exception:
            pass

    raise Exception(f"Cannot resolve a selected object to an ObjectId: {dyn_obj!r}")


def classify_inputs(db: Any, tx: Any, dyn_objs: list[Any]) -> tuple[Any, Any]:
    """Return (ground_surface_oid, boundary_polyline_oid) from the two picks.

    Classifies by entity type so selection order does not matter. Raises if a
    surface or a polyline is missing among the inputs.
    """
    ground_oid: Any = None
    pl_oid: Any = None
    for dyn_obj in dyn_objs:
        oid = resolve_object_id(db, dyn_obj)
        ent = tx.GetObject(oid, OpenMode.ForRead)
        if isinstance(ent, TinSurface):
            ground_oid = oid
        elif isinstance(ent, Polyline):
            pl_oid = oid

    if ground_oid is None:
        raise Exception("No TIN surface among the selected objects.")
    if pl_oid is None:
        raise Exception("No polyline among the selected objects.")
    return ground_oid, pl_oid
