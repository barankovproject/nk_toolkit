from __future__ import annotations

import json
import os
from typing import Any

from Autodesk.AutoCAD.Colors import Color, ColorMethod
from Autodesk.AutoCAD.DatabaseServices import LayerTableRecord, LineWeight, OpenMode
from Autodesk.AutoCAD.LayerManager import LayerFilter

# Layer + filter spec in layers.json next to this module (see docs/process/07_drawing_scripts.md).
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


def ensure_rl_layers(db: Any, tx: Any) -> None:
    """Create missing inf_rl_* layers and enforce color + lineweight + linetype every run."""
    layers = _load_spec().get("layers", {})
    lt = tx.GetObject(db.LayerTableId, OpenMode.ForRead)
    existing: dict[str, Any] = {}
    for lid in lt:
        existing[tx.GetObject(lid, OpenMode.ForRead).Name] = lid
    for name, props in layers.items():
        color = _color(props["color"])
        lw = _lineweight(props.get("lineweight", "default"))
        ltid = _linetype_id(db, tx, props.get("linetype", "Continuous"))
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
        if ltid is not None:
            ltr.LinetypeObjectId = ltid


def ensure_rl_filter(db: Any) -> str:
    """Create the 'Rib Layout' property filter grouping inf_rl_* layers. Returns its name."""
    f = _load_spec().get("filter", {})
    fname = f.get("name", "")
    fexpr = f.get("expr", "")
    if not fname or not fexpr:
        return ""
    tree = db.LayerFilters
    root = tree.Root
    for i in range(root.NestedFilters.Count):
        if root.NestedFilters[i].Name == fname:
            return fname
    pf = LayerFilter()
    pf.Name = fname
    pf.FilterExpression = fexpr
    root.NestedFilters.Add(pf)
    db.LayerFilters = tree
    return fname
