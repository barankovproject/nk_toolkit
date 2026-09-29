from __future__ import annotations

import clr

clr.AddReference("AecPropDataMgd")

from typing import Any

import Autodesk.Aec.PropertyData as _PD_ROOT
import Autodesk.Aec.PropertyData.DatabaseServices as _PD
from Autodesk.AutoCAD.DatabaseServices import OpenMode

_PS_DEF = "Arhyz_LongDitch"
_FIELDS: list[tuple[str, Any]] = [
    ("Canal", _PD_ROOT.DataType.Text),  # human canal label, e.g. "1а"
    ("Index", _PD_ROOT.DataType.Integer),
    ("Length3D", _PD_ROOT.DataType.Real),  # 3D ditch length, m
    ("VolExcavation", _PD_ROOT.DataType.Real),  # откопка, m³
    ("VolStone", _PD_ROOT.DataType.Real),  # щебень (заполнение матрацев), m³
    ("VolGeotextile", _PD_ROOT.DataType.Real),  # геотекстиль, m²
    ("MoveTonnage", _PD_ROOT.DataType.Real),  # перемещение, t
    ("MatCount", _PD_ROOT.DataType.Real),  # матрацы «Рено», шт
    ("MatArea", _PD_ROOT.DataType.Real),  # матрацы «Рено», m²
    ("AnchorCount", _PD_ROOT.DataType.Real),  # забивные анкеры Ø8мм, шт
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


def ensure_ld_psd(db: Any, tx: Any) -> Any:
    """Ensure the Arhyz_LongDitch PSD exists (with all fields); return its ObjectId."""
    dpsd = _PD.DictionaryPropertySetDefinitions(db)
    if _PS_DEF in list(dpsd.NamesInUse):
        psd_id = dpsd.GetAt(_PS_DEF)
        _add_missing_fields(psd_id, _FIELDS, tx)
        return psd_id
    return _make_ps_def(dpsd, tx, _PS_DEF, _FIELDS)


def write_ld_ps(
    ent: Any,
    psd_id: Any,
    tx: Any,
    *,
    canal: str = "",
    index: int,
    length_3d: float,
    vols: dict[str, float],
) -> None:
    """Attach Arhyz_LongDitch to a ditch polyline and write its length + quantities."""
    _PD.PropertyDataServices.AddPropertySet(ent, psd_id)
    try:
        ps_id = _PD.PropertyDataServices.GetPropertySet(ent, psd_id)
    except Exception:
        return
    ps = tx.GetObject(ps_id, OpenMode.ForWrite)
    values = [
        ("Canal", canal),
        ("Index", int(index)),
        ("Length3D", float(length_3d)),
        ("VolExcavation", float(vols["VolExcavation"])),
        ("VolStone", float(vols["VolStone"])),
        ("VolGeotextile", float(vols["VolGeotextile"])),
        ("MoveTonnage", float(vols["MoveTonnage"])),
        ("MatCount", float(vols["MatCount"])),
        ("MatArea", float(vols["MatArea"])),
        ("AnchorCount", float(vols["AnchorCount"])),
    ]
    for fname, val in values:
        try:
            ps.SetAt(ps.PropertyNameToId(fname), val)
        except Exception:
            pass
