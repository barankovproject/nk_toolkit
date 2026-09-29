# AutoCAD Layers

All layers are created by `scripts/layers/layers.dyn`.  
Full machine-readable list with colors: `config/layers.json`.  
All layers: linetype = **Continuous**.

## General layers (prefix `inf_model_`)

| Suffix              | Lineweight | Color (ACI) | Purpose                          |
|---------------------|-----------|-------------|----------------------------------|
| `canals`            | 0.50 mm   | 86          | Canal plan outlines (2D)         |
| `canals_hatch`      | 0.09 mm   | 86          | Canal plan hatching              |
| `canals_3d`         | 0.09 mm   | 7 (white)   | Canal 3D — generic (legacy)      |
| `anti_erosion`      | 0.50 mm   | 150         | Anti-erosion structures          |
| `anti_erosion_hatch`| 0.09 mm   | 150         | Anti-erosion hatching            |
| `heigh`             | 0.09 mm   | 95          | Elevation marks                  |
| `text`              | 0.09 mm   | 142         | Annotation text                  |
| `thick`             | 0.50 mm   | 222         | Thick lines (general)            |
| `thin`              | 0.09 mm   | 222         | Thin lines (general)             |
| `dim`               | 0.09 mm   | 234         | Dimensions                       |
| `hatch`             | 0.09 mm   | 241         | Hatching (general)               |

## 3D model layers — gabion types (t1–t8)

Name: `inf_model_canals_3d_t{N}` — all 0.30 mm, Continuous.

| Type | Color (ACI) |
|------|-------------|
| t1   | 36          |
| t2   | 56          |
| t3   | 66          |
| t4   | 76          |
| t5   | 86          |
| t6   | 96          |
| t7   | 106         |
| t8   | 116         |

## 3D model layers — trough types (t9–t12)

Each trough type has 4 sub-layers. All 0.30 mm, Continuous.

| Type | `_lk` (лоток) | `_pt` (крышка) | `_prep` (подготовка) | `_mono` (монолит) |
|------|--------------|---------------|---------------------|------------------|
| t9   | 41           | 44            | 253                 | 22               |
| t10  | 150          | 153           | 253                 | 24               |
| t11  | 80           | 83            | 253                 | 32               |
| t12  | 200          | 203           | 253                 | 14               |

- **`_lk`** — standard 2.99 m trough body elements
- **`_pt`** — standard 2.99 m cover elements  
- **`_prep`** — sandy preparation (continuous, not cut)
- **`_mono`** — monolith remainder after 2.99 m cutting (body and cover)

---

## Location plan layers (prefix `inf_lp_`)

Created by `draw_location_plan`. Layer colours / lineweights / linetypes and the
"Location Plan" property filter (`NAME == "inf_lp_*"`) are defined in
`automation/scripts/draw_location_plan/layers.json` — that JSON is the single source
of truth and is enforced on every run. See [docs/process/07_drawing_scripts.md](../../docs/process/07_drawing_scripts.md)
for the layer-spec convention shared by all `draw_*` scripts.

## Excavation layers (prefix `inf_exc_`)

Created by `draw_excavation` (top edge = Daylight FL, bottom = Hinge FL, slope hatch
between). Layers and the "Excavation" filter (`NAME == "inf_exc_*"`) are defined in
`automation/scripts/draw_excavation/layers.json`.

## Cross-ditch layers (prefix `inf_cd_`)

Created by `build_cross_ditches` (skewed 3D cross-ditches placed every `step` along
the alignment). Layers and the "Cross Ditches" filter (`NAME == "inf_cd_*"`) are
defined in `automation/scripts/build_cross_ditches/layers.json`:
`inf_cd_ditch` (6), `inf_cd_connector` (4), `inf_cd_killer` (5) — all 0.50 mm.

## Marked-ditch layers (prefix `inf_md_`)

Created by `build_marked_ditches` — same cross-ditch geometry, but each ditch is
placed where the user drew a marker circle. Layers and the "Marked Ditches" filter
(`NAME == "inf_md_*"`) are defined in `automation/scripts/build_marked_ditches/layers.json`:

| Layer              | Color (ACI) | Role                                         |
|--------------------|-------------|----------------------------------------------|
| `inf_md_marker`    | 2 (yellow)  | **User input** — draw a circle here to mark a ditch. Consumed (erased) once its ditch is built. |
| `inf_md_ditch`     | 6           | Ditch polyline + start marker (output)       |
| `inf_md_connector` | 4           | Connector down the откос насыпи (output)     |
| `inf_md_killer`    | 5           | Гаситель (stilling apron) (output)           |

All 0.50 mm. Output entities carry XData `ARHYZ_MD = <alignment>`. The script is
**additive and idempotent**: a re-run keeps every existing ditch and only adds one
where a marker has no ditch within ~1 m (station dedup via the Arhyz_CrossDitch
property set). Each marker that projects onto the alignment is **consumed** (erased)
once its ditch is built, so the marker layer ends up clean; markers that can't be
projected are left in place. Deleting a ditch is manual — erase it by hand.

## See also
- [section_points.md](section_points.md) — which gabion solids go on t1-t8 layers
- [trough_section_points.md](trough_section_points.md) — which trough solids go on t9-t12 sub-layers