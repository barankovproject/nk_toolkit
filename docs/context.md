# Project Context

## What this project does

Automates generation of 3D solid models for irrigation canal structures in Autodesk Civil 3D.
Input: JSON config per canal. Output: Solid3d geometry in the drawing.

## Data flow

```
Canal JSON config
    → load_canal_config()
    → alignment + profile from Civil 3D drawing
    → cross-section geometry at each station
    → lofted Solid3d solids (gabions, troughs, ribs)
    → saved back to drawing layers
    → exported JSON with segment/PI data
```

## Structures built

| Structure | Builder | Description |
|---|---|---|
| Gabion walls | `gabion_builder.py` | Stone-filled wire mesh walls, lofted along alignment |
| Troughs (ЛК) | `trough_builder.py` | Precast concrete channel elements, sliced at 2.99 m |
| Transverse ribs | `rib_builder.py` | Stiffener solids between gabion sections |

## Reference documents

### Civil 3D / AutoCAD platform (`common/docs/platform/`)

Lives in the `civil3d_common` submodule (project-agnostic, shared with `tube_toolkit`):

| File | What it covers |
|---|---|
| `api_dump/` | All public types, methods, properties from the 4 managed DLLs (Mono.Cecil dump) |
| `01_civil3d_errors.md` | Known bugs with root causes and fixes |
| `02_dynamo_com_run.md` | Running Dynamo scripts via AutoCAD COM |
| `03_property_sets_api.md` | AecPropDataMgd: creating definitions, attaching property sets |
| `04_corridor_workflow.md` | Civil 3D corridor build workflow |
| `05_block_insertion_with_fields.md` | Block insertion with field attributes |

Generic development process (`common/docs/process/`) — also in `civil3d_common`:
script naming, launcher pattern, README template, OOP conventions
(`01_api_exploration.md`, `02_development.md`, `07_drawing_scripts.md`).

### Arhyz project-specific (`projects/arhyz_s2/references/`)

| File | What it covers |
|---|---|
| `requirements.md` | Project requirements |
| `config_format.md` | Canal JSON config structure |
| `layers.md` | Drawing layer names |
| `section_points.md` | Gabion cross-section point layout |
| `gabion_corners.md` | PI miter geometry for gabions |
| `trough_types.md` | ЛК trough type catalog (marks, dims, pt_L) |
| `trough_section_points.md` | Trough cross-section point layout |
| `trough_placement.md` | Trough placement and slicing rules |
| `trough_corners.md` | PI miter geometry for troughs |
| `widening_assemblies.md` | Widening assembly naming convention |

### Tube pipeline — separate repository

Водопропуски (culvert water crossings, `В-*`) are NOT part of this repo — they live in
the sibling `tube_toolkit` repository, a separate, project-agnostic toolkit. This repo
(`nk_toolkit`) only handles `НК-*` canals/corridor.

## Tech stack

- Autodesk Civil 3D 2024 + Dynamo (CPython 3.x engine)
- Civil 3D objects: `AeccDbMgd`, `AecBaseMgd`, `acdbmgd`, `acmgd`
- Business logic: plain Python packages under `scripts/` (`scripts/build_canal_model/`,
  `scripts/ditch/`, `scripts/anchor/`, etc.) plus `civil3d_common` (submodule at `common/`)
- Entry point per script: thin `launcher.py` injected into `.dyn` node
