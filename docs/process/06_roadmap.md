# Automation Roadmap

## Goal

Produce a complete drawing set per canal, matching the reference deliverable (Псехако Участок 21А):
- Plan view
- Longitudinal profile with structure annotations
- Cross-section sheets
- Specification table
- Layout sheets ready for plotting

## Already built

| Script | Output |
|---|---|
| `build_canal_model` | 3D solids: gabions, troughs, ribs |
| `build_corridors` | Civil 3D corridor |
| `build_corridor_surfaces` | TIN surfaces |
| `draw_corridor_outlines` | Corridor outline polylines |
| `draw_corridor_slope_hatches` | Slope hatching |
| `draw_gabion_view` | 2D gabion plan view with hatches and element numbering |
| `build_widening_assemblies` | Widening corridor assemblies |
| `report_stone` | Stone volume schedule |
| `report_canal` | Canal geometry report |
| `report_alignment` | Alignment data |
| `report_excavation_volumes` | Excavation volumes |
| `build_corridor_volumes` | Corridor volumes |
| `draw_location_plan` | 2D location scheme: canal outline, slope hatch, gabion section rects, station markers (`inf_lp_*` layers) |
| `draw_excavation` | 2D excavation pit (котлован): top edge (Daylight) + bottom (Hinge) polylines + slope hatch per corridor (`inf_exc_*` layers) |
| `ditch_core` | Transverse cross-ditches (поперечные канавы) across a selected alignment at a configurable step (default 20 m), each spanning a selected TIN surface along the alignment normal. 2D polylines on `inf_cd_*`; 3D solids TODO. |
| `ditch_04_build_cross` | Cross-ditch per user-drawn marker circle (`inf_md_*`), reusing the ditch_core geometry. Writes per-ditch quantities (выемка / перемещение / щебень / геотекстиль) into the `Arhyz_CrossDitch` property set — rates in `ditch_04_build_cross/volumes.py`. |
| `ditch_05_build_cross_volumes` | Recompute cross-ditch volume property sets from the current drawn geometry (run after manual edits). Links each connector to its ditch by the index stamped in the connector XData. |
| `ditch_06_report_cross` | Quantity ведомость (CSV) summing the cross-ditch property-set quantities per alignment + grand total. `RECOMPUTE` flag refreshes from geometry first. |
| `ditch_01_draw_cut_toe` | Continuous blue 3D polyline along the cut-slope toe (подошва откоса выемки) of an alignment, broken where there is no выемка. Visualisation only (`inf_ct_toe`). |
| `ditch_03_build_long` | Drape the user's 2D longitudinal-ditch polylines on `inf_ct_toe` onto the trasse surface (Z = surface − 0.46 m at each vertex) and replace each with the 3D polyline; re-runs also re-drape its own `ARHYZ_LD`-tagged 3D lines so a depth/XY change propagates. Writes per-ditch quantities (откопка/щебень/геотекстиль per м.п., перемещение = откопка×2.01, матрацы «Рено» = L/2 + повороты, анкеры = 2/м.п.) into the `Arhyz_LongDitch` property set — rates in `ditch_03_build_long/volumes.py`. |
| `ditch_06_report_long` | Quantity ведомость (CSV) summing the longitudinal-ditch `Arhyz_LongDitch` quantities per ditch + grand total. |

> Ditch workflow (which script per step) + the one-command volume update: [08_ditch_pipeline.md](08_ditch_pipeline.md).

## To build

### Group A — Profile annotations

**`build_profile_annotations`**

Place structure markers on the Civil 3D Profile View for a given canal:
- Rib elevation markers at each rib station
- Gabion section boundaries
- Structure level lines (top of gabion per section)

Input: exported JSON from `build_canal_model` + canal alignment name
Output: blocks/text entities inserted on the Profile View in model space

---

### Group B — Specification

**`report_specification`**

Generate an AutoCAD TABLE entity with the full element schedule:
- Gabions by type and size
- Troughs (ЛК marks)
- Ribs
- Totals per canal and across all canals

Input: JSON from `build_canal_model` + `report_stone` data
Output: AutoCAD TABLE inserted in the drawing; optional Excel export

---

### Group C — Layout sheets

**`build_sheet`**

Create or update a named Layout for a given canal:
1. Insert title block (rамка-штамп) block with attributes
2. Create viewport → plan view at auto-scale
3. Create viewport → profile view at auto-scale
4. Fill block attributes: canal name, scale, sheet number, date

Input: canal name; requires existing Profile View in model space
Note: complex alignments (tight curves) may need manual scale adjustment

**`build_sheet_sections`**

Generate a layout sheet with cross-section views:
- User creates one section view template manually
- Script replicates it across stations and places on sheet

Input: canal name + user-defined section view template
Note: develop after user has created the template section

## Development order

1. `build_profile_annotations` — adds value to the already-working profile
2. `report_specification` — needed for complete drawing set, TABLE API is known
3. `build_sheet` — after plan and profile both have content
4. `build_sheet_sections` — after user creates the section template
