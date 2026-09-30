from __future__ import annotations

import json
import os
from typing import Any

from Autodesk.AutoCAD.Colors import Color, ColorMethod
from Autodesk.AutoCAD.DatabaseServices import LayerTableRecord, LineWeight, OpenMode
from Autodesk.AutoCAD.LayerManager import LayerFilter

# Layer + filter spec lives in layers.json next to this module (see
# docs/process/07_drawing_scripts.md). One layer: the anchor horizontal lines.
_LAYERS_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "layers.json")


def _load_spec() -> dict[str, Any]:
    with open(_LAYERS_JSON, encoding="utf-8") as f:
        return json.load(f)


def _color(val: Any) -> Any:
    """Build a Color from an ACI index (int) or an (r, g, b) tuple."""
    if isinstance(val, (tuple, list)):
        return Color.FromRgb(int(val[0]), int(val[1]), int(val[2]))
    return Color.FromColorIndex(ColorMethod.ByAci, int(val))


def _lineweight(val: Any) -> Any:
    """Map an mm value (e.g. 0.50) to a LineWeight enum; 'default' → ByLineWeightDefault."""
    if val == "default":
        return LineWeight.ByLineWeightDefault
    return getattr(LineWeight, f"LineWeight{int(round(float(val) * 100)):03d}")


def _linetype_id(db: Any, tx: Any, name: str) -> Any:
    """Return the ObjectId of a linetype, loading it from a .lin file if not present."""
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


def anchor_layer_name() -> str:
    """Name of the (single) layer the anchor horizontal lines are drawn on."""
    return next(iter(_load_spec().get("layers", {})), "inf_md_anchor")


def ensure_anchor_layers(db: Any, tx: Any) -> None:
    """Create missing layers from layers.json and enforce color/lineweight/linetype every run."""
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


def ensure_anchor_filter(db: Any) -> str:
    """Create the property filter from layers.json that groups the anchor layer.

    Returns the filter name. Must be called outside any transaction — db.LayerFilters
    is a struct and writing it back inside a tx causes eNotOpenForWrite.
    """
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
