from __future__ import annotations

import clr

clr.AddReference("AecPropDataMgd")

from contextlib import contextmanager
from typing import Any, Callable, Optional

import Autodesk.Aec.PropertyData as _PD_ROOT
import Autodesk.Aec.PropertyData.DatabaseServices as _PD
from Autodesk.AutoCAD.DatabaseServices import (
    DBObjectCollection,
    LayerTableRecord,
    Line,
    OpenMode,
    Region,
    Solid3d,
)

_GABION_PS_DEF = "Arhyz_Gabion"
_TROUGH_PS_DEF = "Arhyz_Trough"
_GABION_BASKET_PS_DEF = "Arhyz_Gabion_Baskets"

_GABION_PS_FIELDS: list[tuple[str, Any]] = [
    ("Canal", _PD_ROOT.DataType.Text),
    ("Type", _PD_ROOT.DataType.Text),
    ("GeotextileArea", _PD_ROOT.DataType.Real),
    ("FillVolume", _PD_ROOT.DataType.Real),
    ("AnchorCount", _PD_ROOT.DataType.Integer),
]
_TROUGH_PS_FIELDS: list[tuple[str, Any]] = [
    ("Canal", _PD_ROOT.DataType.Text),
    ("Mark", _PD_ROOT.DataType.Text),
    ("Volume", _PD_ROOT.DataType.Real),
]
_GABION_BASKET_PS_FIELDS: list[tuple[str, Any]] = [
    ("BasketDim", _PD_ROOT.DataType.Text),
    ("BasketCount", _PD_ROOT.DataType.Integer),
]
_RIB_PS_DEF = "Arhyz_Rib"
_RIB_PS_FIELDS: list[tuple[str, Any]] = [
    ("Canal", _PD_ROOT.DataType.Text),
    ("BasketDim", _PD_ROOT.DataType.Text),
    ("BasketCount", _PD_ROOT.DataType.Integer),
    ("Volume", _PD_ROOT.DataType.Real),
]


@contextmanager
def civil_transaction(doc, db):
    """Lock document, start transaction, commit on success or abort on exception."""
    lock = doc.LockDocument()
    try:
        tx = db.TransactionManager.StartTransaction()
        try:
            yield tx
            tx.Commit()
        except Exception:
            tx.Abort()
            raise
        finally:
            tx.Dispose()
    finally:
        lock.Dispose()


def make_region(pts, ms, tx):
    """Create a closed Region from a list of Point3d and add it to modelspace."""
    n = len(pts)
    lines = []
    for i in range(n):
        ln = Line(pts[i], pts[(i + 1) % n])
        ms.AppendEntity(ln)
        tx.AddNewlyCreatedDBObject(ln, True)
        lines.append(ln)
    curve_col = DBObjectCollection()
    for ln in lines:
        curve_col.Add(ln)
    region_col = Region.CreateFromCurves(curve_col)
    region = region_col[0]
    ms.AppendEntity(region)
    tx.AddNewlyCreatedDBObject(region, True)
    for ln in lines:
        ln.Erase()
    return region


def ensure_layer(db, tx, name):
    """Create layer `name` in the drawing if it doesn't exist yet."""
    lt = tx.GetObject(db.LayerTableId, OpenMode.ForRead)
    if not lt.Has(name):
        lt.UpgradeOpen()
        ltr = LayerTableRecord()
        ltr.Name = name
        lt.Add(ltr)
        tx.AddNewlyCreatedDBObject(ltr, True)


def loft_solid(pts_A, pts_B, ctx):
    """Loft two point-lists into a Solid3d; regions erased on exit. Raises on failure."""
    r0 = r1 = None
    try:
        r0 = make_region(pts_A, ctx.ms, ctx.tx)
        r1 = make_region(pts_B, ctx.ms, ctx.tx)
        solid = Solid3d()
        solid.CreateLoftedSolid([r0, r1], [], None, ctx.opts)
        return solid
    finally:
        for r in (r0, r1):
            if r is not None:
                try:
                    r.Erase()
                except Exception:
                    pass


def add_solid(solid, layer, ctx):
    """Set layer, register solid in the current modelspace transaction, and return the solid."""
    solid.Layer = layer
    ctx.ms.AppendEntity(solid)
    ctx.tx.AddNewlyCreatedDBObject(solid, True)
    return solid


_LEGACY_PS_DEFS = ("CanalElement", "Arhyz_Element")


def _make_ps_def(dpsd: Any, tx: Any, name: str, fields: list[tuple[str, Any]]) -> Any:
    """Create a new PropertySetDefinition (AppliesToAll=False) and return its ObjectId."""
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
    """Add any fields from `fields` not yet in the PropertySetDefinition (migration helper).

    Opens ForRead to inspect, then ForWrite to modify — avoids UpgradeOpen() issues.
    """
    try:
        existing = {
            pd_def.Name for pd_def in tx.GetObject(psd_id, OpenMode.ForRead).Definitions
        }
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


def ensure_ps_defs(db: Any, tx: Any) -> tuple[Any, Any, Any, Any]:
    """Ensure all four PSDs exist; return (gabion_id, trough_id, basket_id, rib_id)."""
    dpsd = _PD.DictionaryPropertySetDefinitions(db)
    for _old in _LEGACY_PS_DEFS:
        if _old in list(dpsd.NamesInUse):
            try:
                tx.GetObject(dpsd.DictionaryId, OpenMode.ForWrite)
                old_id = dpsd.GetAt(_old)
                old_obj = tx.GetObject(old_id, OpenMode.ForWrite)
                old_obj.Erase()
            except Exception:
                pass
    names = list(dpsd.NamesInUse)
    if _GABION_PS_DEF in names:
        gabion_id = dpsd.GetAt(_GABION_PS_DEF)
        _add_missing_fields(gabion_id, _GABION_PS_FIELDS, tx)
    else:
        gabion_id = _make_ps_def(dpsd, tx, _GABION_PS_DEF, _GABION_PS_FIELDS)
    trough_id = (
        dpsd.GetAt(_TROUGH_PS_DEF)
        if _TROUGH_PS_DEF in names
        else _make_ps_def(dpsd, tx, _TROUGH_PS_DEF, _TROUGH_PS_FIELDS)
    )
    if _GABION_BASKET_PS_DEF in names:
        basket_id = dpsd.GetAt(_GABION_BASKET_PS_DEF)
        _add_missing_fields(basket_id, _GABION_BASKET_PS_FIELDS, tx)
    else:
        basket_id = _make_ps_def(
            dpsd, tx, _GABION_BASKET_PS_DEF, _GABION_BASKET_PS_FIELDS
        )
    if _RIB_PS_DEF in names:
        rib_id = dpsd.GetAt(_RIB_PS_DEF)
        _add_missing_fields(rib_id, _RIB_PS_FIELDS, tx)
    else:
        rib_id = _make_ps_def(dpsd, tx, _RIB_PS_DEF, _RIB_PS_FIELDS)
    return gabion_id, trough_id, basket_id, rib_id


def _attach_and_write(
    solid: Any, psd_id: Any, tx: Any, values: list[tuple[str, Any]]
) -> None:
    _PD.PropertyDataServices.AddPropertySet(solid, psd_id)
    try:
        ps_id = _PD.PropertyDataServices.GetPropertySet(solid, psd_id)
    except Exception:
        return
    ps = tx.GetObject(ps_id, OpenMode.ForWrite)
    for fname, val in values:
        try:
            ps.SetAt(ps.PropertyNameToId(fname), val)
        except Exception:
            pass


def tag_gabion(
    solid: Any,
    psd_id: Any,
    tx: Any,
    *,
    canal: str = "",
    type_no: str = "",
    geotextile_area: float = 0.0,
    fill_volume: float = 0.0,
    anchor_count: int = 0,
) -> None:
    """Attach Arhyz_Gabion property set and write Canal/Type/GeotextileArea/FillVolume/AnchorCount."""
    _attach_and_write(
        solid,
        psd_id,
        tx,
        [
            ("Canal", canal),
            ("Type", type_no),
            ("GeotextileArea", geotextile_area),
            ("FillVolume", fill_volume),
            ("AnchorCount", anchor_count),
        ],
    )


def tag_trough(
    solid: Any,
    psd_id: Any,
    tx: Any,
    *,
    canal: str = "",
    mark: str = "",
    volume: float = 0.0,
) -> None:
    """Attach Arhyz_Trough property set and write Canal/Mark/Volume."""
    _attach_and_write(
        solid, psd_id, tx, [("Canal", canal), ("Mark", mark), ("Volume", volume)]
    )


def tag_gabion_baskets(
    solid: Any,
    psd_id: Any,
    tx: Any,
    *,
    basket_dim: str = "",
    basket_count: int = 0,
) -> None:
    """Attach Arhyz_Gabion_Baskets property set and write BasketDim/BasketCount."""
    _attach_and_write(
        solid, psd_id, tx, [("BasketDim", basket_dim), ("BasketCount", basket_count)]
    )


def tag_rib(
    solid: Any,
    psd_id: Any,
    tx: Any,
    *,
    canal: str = "",
    basket_dim: str = "",
    basket_count: int = 0,
    volume: float = 0.0,
) -> None:
    """Attach Arhyz_Rib property set and write Canal/BasketDim/BasketCount/Volume."""
    _attach_and_write(
        solid,
        psd_id,
        tx,
        [
            ("Canal", canal),
            ("BasketDim", basket_dim),
            ("BasketCount", basket_count),
            ("Volume", volume),
        ],
    )


def purge_canal_solids(
    canal_name: str,
    gabion_psd_id: Any,
    trough_psd_id: Any,
    rib_psd_id: Any,
    ms: Any,
    tx: Any,
    log: Optional[Callable[..., None]] = None,
) -> int:
    """Erase all Solid3d entities tagged with Canal == canal_name from modelspace.

    Pass the already-opened BlockTableRecord as `ms` to avoid double-open in the
    same transaction.  Returns the number of erased solids.
    """
    ids_to_erase = []
    for eid in ms:
        try:
            ent = tx.GetObject(eid, OpenMode.ForRead)
            if not isinstance(ent, Solid3d):
                continue
            for psd_id in (gabion_psd_id, trough_psd_id, rib_psd_id):
                if psd_id is None:
                    continue
                try:
                    ps_id = _PD.PropertyDataServices.GetPropertySet(ent, psd_id)
                    ps = tx.GetObject(ps_id, OpenMode.ForRead)
                    if str(ps.GetAt(ps.PropertyNameToId("Canal"))) == canal_name:
                        ids_to_erase.append(eid)
                        break
                except Exception:
                    continue
        except Exception:
            continue
    for eid in ids_to_erase:
        try:
            tx.GetObject(eid, OpenMode.ForWrite).Erase()
        except Exception:
            pass
    if log:
        log(f"purged {len(ids_to_erase)} existing solids for '{canal_name}'")
    return len(ids_to_erase)


def gabion_layer(tp_key):
    """Return layer name for a gabion solid of the given type key."""
    return f"inf_model_canals_3d_t{tp_key}"


def trough_layer(tp_key, part):
    """Return layer name for a trough solid part (lk, pt, lk_cut, pt_cut, lk_mono, pt_mono)."""
    return f"inf_model_canals_3d_t{tp_key}_{part}"
