"""Layer + property-filter setup for the GSI construction grid (see
docs/process/07_drawing_scripts.md). Two layers: blue corner diagonals and magenta
perpendiculars, grouped under a "GSI Grid" property filter.
"""

from __future__ import annotations

import json
import os
from typing import Any

from Autodesk.AutoCAD.Colors import Color, ColorMethod
from Autodesk.AutoCAD.DatabaseServices import LayerTableRecord, LineWeight, OpenMode
from Autodesk.AutoCAD.LayerManager import LayerFilter

_LAYERS_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "layers.json")


def _load_spec() -> dict[str, Any]:
    with open(_LAYERS_JSON, encoding="utf-8") as f:
        return json.load(f)


def _color(val: Any) -> Any:
    if isinstance(val, (tuple, list)):
        return Color.FromRgb(int(val[0]), int(val[1]), int(val[2]))
    return Color.FromColorIndex(ColorMethod.ByAci, int(val))


def _lineweight(val: Any) -> Any:
    if val == "default":
        return LineWeight.ByLineWeightDefault
    return getattr(LineWeight, f"LineWeight{int(round(float(val) * 100)):03d}")


def _linetype_id(db: Any, tx: Any, name: str) -> Any:
    ltt = tx.GetObject(db.LinetypeTableId, OpenMode.ForRead)
    for lid in ltt:
        if tx.GetObject(lid, OpenMode.ForRead).Name.upper() == name.upper():
            return lid
    for lin_file in ("acadiso.lin", "acad.lin"):
        try:
            db.LoadLineTypeFile(name, lin_file)
            break
        except Exception:
            continue
    ltt = tx.GetObject(db.LinetypeTableId, OpenMode.ForRead)
    for lid in ltt:
        if tx.GetObject(lid, OpenMode.ForRead).Name.upper() == name.upper():
            return lid
    return None


def diag_layer_name() -> str:
    """Blue corner-diagonal layer (first entry in layers.json)."""
    return next(iter(_load_spec().get("layers", {})), "inf_gsi_grid_diag")


def perp_layer_name() -> str:
    """Magenta perpendicular layer (second entry in layers.json)."""
    names = list(_load_spec().get("layers", {}))
    return names[1] if len(names) > 1 else "inf_gsi_grid_perp"


def region_layer_name() -> str:
    """White straight-layout region layer (third entry in layers.json)."""
    names = list(_load_spec().get("layers", {}))
    return names[2] if len(names) > 2 else "inf_gsi_grid_region"


def block_layer_name() -> str:
    """GSI block layer (fourth entry in layers.json)."""
    names = list(_load_spec().get("layers", {}))
    return names[3] if len(names) > 3 else "inf_gsi_grid_block"


def wedge_layer_name() -> str:
    """Corner-wedge filler layer (fifth entry in layers.json)."""
    names = list(_load_spec().get("layers", {}))
    return names[4] if len(names) > 4 else "inf_gsi_grid_wedge"


def ensure_layers(db: Any, tx: Any) -> None:
    layers = _load_spec().get("layers", {})
    lt = tx.GetObject(db.LayerTableId, OpenMode.ForRead)
    existing: dict[str, Any] = {}
    for layer_id in lt:
        existing[tx.GetObject(layer_id, OpenMode.ForRead).Name] = layer_id
    for name, props in layers.items():
        color = _color(props["color"])
        lw = _lineweight(props.get("lineweight", "default"))
        ltype_id = _linetype_id(db, tx, props.get("linetype", "Continuous"))
        if name in existing:
            ltr = tx.GetObject(existing[name], OpenMode.ForWrite)
        else:
            lt.UpgradeOpen()
            ltr = LayerTableRecord()
            ltr.Name = name
            lt.Add(ltr)
            tx.AddNewlyCreatedDBObject(ltr, True)
        ltr.Color = color
        ltr.LineWeight = lw
        if ltype_id is not None:
            ltr.LinetypeObjectId = ltype_id


def ensure_filter(db: Any) -> str:
    """Create the "GSI Grid" property filter; call OUTSIDE any transaction."""
    f = _load_spec().get("filter", {})
    filter_name = f.get("name", "")
    filter_expr = f.get("expr", "")
    if not filter_name or not filter_expr:
        return ""
    tree = db.LayerFilters
    root = tree.Root
    for i in range(root.NestedFilters.Count):
        if root.NestedFilters[i].Name == filter_name:
            return filter_name
    pf = LayerFilter()
    pf.Name = filter_name
    pf.FilterExpression = filter_expr
    root.NestedFilters.Add(pf)
    db.LayerFilters = tree
    return filter_name
