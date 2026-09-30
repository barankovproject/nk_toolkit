from __future__ import annotations

import clr

clr.AddReference("AecPropDataMgd")

from typing import Any

import Autodesk.Aec.PropertyData as _PD_ROOT
import Autodesk.Aec.PropertyData.DatabaseServices as _PD
from Autodesk.AutoCAD.DatabaseServices import OpenMode

_PS_DEF = "Arhyz_CrossDitch"
# Numbering + per-ditch diagnostics, so a ditch in the drawing can be traced
# back to its station / skew / grade while debugging.
_FIELDS: list[tuple[str, Any]] = [
    ("Canal", _PD_ROOT.DataType.Text),  # human canal label, e.g. "1а"
    ("Alignment", _PD_ROOT.DataType.Text),
    ("Index", _PD_ROOT.DataType.Integer),
    ("Station", _PD_ROOT.DataType.Real),
    ("ThetaDeg", _PD_ROOT.DataType.Real),
    ("Slope", _PD_ROOT.DataType.Real),
    ("Length2D", _PD_ROOT.DataType.Real),  # plan (XY) length of the ditch
    ("ZStart", _PD_ROOT.DataType.Real),  # elevation of the start (нагорный) end
    ("ZEnd", _PD_ROOT.DataType.Real),  # elevation of the end (низовой) end
    ("Status", _PD_ROOT.DataType.Text),
    # Quantities (written by ditch_04_build_cross only; 0 for ditch_core).
    ("VolExcavation", _PD_ROOT.DataType.Real),  # выемка грунта, m³
    ("VolStone", _PD_ROOT.DataType.Real),  # укрепление щебнем, m³
    ("VolGeotextile", _PD_ROOT.DataType.Real),  # геотекстиль (Дорнит 200), m²
    ("MoveTonnage", _PD_ROOT.DataType.Real),  # перемещение вынутого грунта, t
]


def _make_ps_def(dpsd: Any, tx: Any, name: str, fields: list[tuple[str, Any]]) -> Any:
    """Create a PropertySetDefinition (AppliesToAll=False) and return its ObjectId."""
    tx.GetObject(dpsd.DictionaryId, OpenMode.ForWrite)
    psd = dpsd.NewEntry()
    psd.AppliesToAll = False
    dpsd.AddNewRecord(name, psd)
    tx.AddNewlyCreatedDBObject(psd, True)
    for fname, ftype in fields:
        prop_def = _PD.PropertyDefinition()
        prop_def.Name = fname
        prop_def.DataType = ftype
        prop_def.DefaultData = "" if ftype == _PD_ROOT.DataType.Text else 0.0
        psd.Definitions.Add(prop_def)
    return dpsd.GetAt(name)


def _add_missing_fields(psd_id: Any, fields: list[tuple[str, Any]], tx: Any) -> None:
    """Add fields not yet present on an existing PSD (migration for older drawings)."""
    try:
        existing = {d.Name for d in tx.GetObject(psd_id, OpenMode.ForRead).Definitions}
    except Exception:
        return
    missing = [(n, t) for n, t in fields if n not in existing]
    if not missing:
        return
    try:
        psd_w = tx.GetObject(psd_id, OpenMode.ForWrite)
        for fname, ftype in missing:
            prop_def = _PD.PropertyDefinition()
            prop_def.Name = fname
            prop_def.DataType = ftype
            prop_def.DefaultData = "" if ftype == _PD_ROOT.DataType.Text else 0.0
            psd_w.Definitions.Add(prop_def)
    except Exception:
        pass


def ensure_cd_psd(db: Any, tx: Any) -> Any:
    """Ensure the Arhyz_CrossDitch PSD exists (with all fields); return its ObjectId.

    Must run inside a document lock (DictionaryPropertySetDefinitions needs it).
    """
    dpsd = _PD.DictionaryPropertySetDefinitions(db)
    if _PS_DEF in list(dpsd.NamesInUse):
        psd_id = dpsd.GetAt(_PS_DEF)
        _add_missing_fields(psd_id, _FIELDS, tx)
        return psd_id
    return _make_ps_def(dpsd, tx, _PS_DEF, _FIELDS)


def tag_ditch(
    ent: Any,
    psd_id: Any,
    tx: Any,
    *,
    canal: str = "",
    alignment: str,
    index: int,
    station: float,
    theta_deg: float,
    slope: float,
    length_2d: float,
    z_start: float,
    z_end: float,
    status: str,
    vol_excavation: float = 0.0,
    vol_stone: float = 0.0,
    vol_geotextile: float = 0.0,
    move_tonnage: float = 0.0,
) -> None:
    """Attach Arhyz_CrossDitch to a ditch entity and write its number + diagnostics.

    Volume args default to 0.0 so callers that do not compute quantities
    (ditch_core) are unaffected; ditch_04_build_cross passes the real
    per-ditch values.
    """
    _PD.PropertyDataServices.AddPropertySet(ent, psd_id)
    try:
        ps_id = _PD.PropertyDataServices.GetPropertySet(ent, psd_id)
    except Exception:
        return
    ps = tx.GetObject(ps_id, OpenMode.ForWrite)
    values = [
        ("Canal", canal),
        ("Alignment", alignment),
        ("Index", int(index)),
        ("Station", float(station)),
        ("ThetaDeg", float(theta_deg)),
        ("Slope", float(slope)),
        ("Length2D", float(length_2d)),
        ("ZStart", float(z_start)),
        ("ZEnd", float(z_end)),
        ("Status", status),
        ("VolExcavation", float(vol_excavation)),
        ("VolStone", float(vol_stone)),
        ("VolGeotextile", float(vol_geotextile)),
        ("MoveTonnage", float(move_tonnage)),
    ]
    for fname, val in values:
        try:
            ps.SetAt(ps.PropertyNameToId(fname), val)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Auxiliary parts (соединитель / гаситель) carry a SEPARATE identity-only PSD so a
# part can be traced back to its ditch and is not lost during the geometry-based
# volume refresh. Kept distinct from Arhyz_CrossDitch so the report never sums a
# part as a ditch (no double count). No volume fields — quantities stay on the run.
# ─────────────────────────────────────────────────────────────────────────────
_PART_PS_DEF = "Arhyz_CrossDitchPart"
_PART_FIELDS: list[tuple[str, Any]] = [
    ("Canal", _PD_ROOT.DataType.Text),  # human canal label, e.g. "1а"
    ("Alignment", _PD_ROOT.DataType.Text),
    (
        "DitchIndex",
        _PD_ROOT.DataType.Integer,
    ),  # Index of the ditch run this part serves
    ("PartType", _PD_ROOT.DataType.Text),  # "connector" | "killer"
]


def ensure_part_psd(db: Any, tx: Any) -> Any:
    """Ensure the Arhyz_CrossDitchPart PSD exists (with all fields); return its ObjectId.

    Must run inside a document lock (DictionaryPropertySetDefinitions needs it).
    """
    dpsd = _PD.DictionaryPropertySetDefinitions(db)
    if _PART_PS_DEF in list(dpsd.NamesInUse):
        psd_id = dpsd.GetAt(_PART_PS_DEF)
        _add_missing_fields(psd_id, _PART_FIELDS, tx)
        return psd_id
    return _make_ps_def(dpsd, tx, _PART_PS_DEF, _PART_FIELDS)


def tag_part(
    ent: Any,
    psd_id: Any,
    tx: Any,
    *,
    canal: str,
    alignment: str,
    ditch_index: int,
    part_type: str,
) -> None:
    """Attach Arhyz_CrossDitchPart to a connector/killer and write its identity.

    Idempotent: re-attaching on an entity that already has the set just overwrites
    the values (the refresh re-tags every run from the authoritative linkage).
    """
    if psd_id is None:
        return
    try:
        ps_id = _PD.PropertyDataServices.GetPropertySet(ent, psd_id)
    except Exception:
        # Open for write only if needed: a freshly built part is already write-
        # enabled (UpgradeOpen would throw eWasOpenForWrite); a refreshed part was
        # opened ForRead and must be upgraded.
        if not ent.IsWriteEnabled:
            ent.UpgradeOpen()
        _PD.PropertyDataServices.AddPropertySet(ent, psd_id)
        try:
            ps_id = _PD.PropertyDataServices.GetPropertySet(ent, psd_id)
        except Exception:
            return
    ps = tx.GetObject(ps_id, OpenMode.ForWrite)
    values = [
        ("Canal", canal),
        ("Alignment", alignment),
        ("DitchIndex", int(ditch_index)),
        ("PartType", part_type),
    ]
    for fname, val in values:
        try:
            ps.SetAt(ps.PropertyNameToId(fname), val)
        except Exception:
            pass
