"""Property set for anchor circles: continuous number + elevation."""

from __future__ import annotations

import clr

clr.AddReference("AecPropDataMgd")

from typing import Any

import Autodesk.Aec.PropertyData as _PD_ROOT
import Autodesk.Aec.PropertyData.DatabaseServices as _PD
from Autodesk.AutoCAD.DatabaseServices import OpenMode

PS_DEF = "Arhyz_Anchor"
_FIELDS: list[tuple[str, Any]] = [
    ("Number", _PD_ROOT.DataType.Integer),  # continuous anchor number
    ("Elevation", _PD_ROOT.DataType.Real),  # row elevation (z)
]


def _make_ps_def(dpsd: Any, tx: Any, name: str, fields: list[tuple[str, Any]]) -> Any:
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


def ensure_anchor_psd(db: Any, tx: Any) -> Any:
    """Ensure the Arhyz_Anchor PSD exists; return its ObjectId (needs a doc lock)."""
    dpsd = _PD.DictionaryPropertySetDefinitions(db)
    if PS_DEF in list(dpsd.NamesInUse):
        return dpsd.GetAt(PS_DEF)
    return _make_ps_def(dpsd, tx, PS_DEF, _FIELDS)


def tag_anchor(ent: Any, psd_id: Any, tx: Any, number: int, elevation: float) -> None:
    """Attach Arhyz_Anchor to a circle and write its number + elevation."""
    _PD.PropertyDataServices.AddPropertySet(ent, psd_id)
    try:
        ps_id = _PD.PropertyDataServices.GetPropertySet(ent, psd_id)
    except Exception:
        return
    ps = tx.GetObject(ps_id, OpenMode.ForWrite)
    for fname, val in (("Number", int(number)), ("Elevation", float(elevation))):
        try:
            ps.SetAt(ps.PropertyNameToId(fname), val)
        except Exception:
            pass
