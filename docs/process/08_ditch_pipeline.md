# Ditch pipeline (водоотводные канавы)

End-to-end workflow for the drainage ditches. Two structures: **продольная**
(longitudinal, along the cut-slope toe) and **поперечная** (cross / transverse,
one per marker circle). All ditch scripts share the `ditch_NN_<verb>_<type>`
naming so they sort by pipeline step and the type is explicit. Every script named
below lives under `automation/scripts/ditch/<name>/` (namespaced folder, same
convention as `automation/scripts/tube/`).

- `ditch_core` — shared geometry library (`ditch_solver`, `killer`, `geometry`,
  `cross_profile`, `property_sets`, `selection`) **+** the legacy uniform-step
  cross-ditch builder (still runnable via its own `.dyn`). Imported by the
  pipeline scripts; not part of the per-canal workflow below.
- **Single config** — `ditch_core/config.py` holds the settings for the whole set:
  `CONFIG` (alignment_name / surface_name + cross-ditch geometry params), `CUT_EPS`
  (step 1), `SOURCE_LAYER` + `DROP` (step 3). Every ditch script imports from it,
  so the alignment/surface is edited in **one** place. Per-type quantity rates stay
  in each builder's `volumes.py`.

## Steps

| # | Action | Script / tool | Layer | Property set |
|---|---|---|---|---|
| 1 | Find the cut-slope toe (подошва выемки) | `ditch_01_draw_cut_toe` | `inf_ct_toe` (blue) | — |
| 2 | Edit by hand → flatten to 2D → offset 1.5 m | manual (AutoCAD) | `inf_ct_toe` | — |
| 3 | Build the 3D longitudinal ditch (drape −0.46 m) + volumes | `ditch_03_build_long` | `inf_ct_toe` | `Arhyz_LongDitch` |
| 4 | Place cross ditches (marker circles → 3D ditches) + volumes | `ditch_04_build_cross` | `inf_md_*` | `Arhyz_CrossDitch` (run) + `Arhyz_CrossDitchPart` (соединитель/гаситель) |
| 5 | Edit longitudinal/cross by hand, then recompute | `ditch_05_build_long_volumes` (long) + `ditch_05_build_cross_volumes` (cross) | — | both |
| 6 | Output volumes (refresh + ведомости + Excel) | `update_ditch_volumes.ps1` | — | both |
| 7a | Place point-number blocks at characteristic points | `ditch_07_draw_point_blocks` | `inf_md_point` | — |
| 7b | Number the blocks' `#` attribute (1..N drawing-wide) | `ditch_08_number_points` | `inf_md_point` | — |

## Step 6 — one command

`automation/tools/update_ditch_volumes.ps1` runs the whole volume update in the
open Civil 3D session (via COM), then builds the Excel workbook:

```
powershell -File automation\tools\update_ditch_volumes.ps1
```

It chains, in order:
1. `ditch_05_build_cross_volumes` — recompute cross-ditch PS from current geometry
   (handles hand-drawn lines; connector linked by endpoint geometry, apron counted
   only when a connector is present). Besides volumes it refreshes the diagnostics:
   `Length2D` / `ZStart` / `ZEnd` are always rewritten from the drawn run; `Slope` /
   `Station` / `ThetaDeg` are reconstructed (station = run midpoint projected on the
   alignment, θ = skew off the alignment normal) but written only when still empty,
   so the solver's exact build-time values are kept; a blank `Status` becomes
   `manual`. Needs the config alignment loadable — otherwise Station/ThetaDeg are
   left at 0 and only volumes + geometry diagnostics refresh. It also (re)tags each
   linked **соединитель / гаситель** with the `Arhyz_CrossDitchPart` identity property
   set (`Canal` / `Alignment` / `DitchIndex` / `PartType`) so a part traces back to its
   ditch and is not lost; this is a separate PSD from `Arhyz_CrossDitch`, so the
   ведомость never sums a part as a ditch.
2. `ditch_06_report_cross` — cross ведомость → CSV, one row per trasse. Besides the
   quantities it reports `length_total_m`: the total built ditch length per trasse =
   3D length of every part (основа `inf_md_ditch` + соединитель `inf_md_connector` +
   гаситель `inf_md_killer`), measured straight from the drawn polylines and grouped
   by the layer suffix.
3. `ditch_05_build_long_volumes` — recompute longitudinal PS from current geometry.
   Like the cross refresh it only reads vertices and rewrites the PS — it does **not**
   re-drape, so manual Z edits survive. Longitudinal ditches share `inf_ct_toe` with
   the cut-toe lines, so it selects every `Polyline3d` on the layer **except** those
   tagged `ARHYZ_CT` (cut-toe). Run `ditch_03_build_long` instead when you want the
   geometry re-draped onto the surface (e.g. after a `DROP` change).
4. `ditch_06_report_long` — longitudinal ведомость → CSV, one row per trasse.
5. `automation/tools/ditch_volumes_to_excel.py` — both ведомости →
   the `arhyz_s2_data` repo's `data/reports/ditch_volumes.xlsx` (falls back to a
   timestamped copy if the file is open in Excel).

Both report CSVs lead with a `trasse` column: quantities are grouped by the `Canal`
property-set label (e.g. `1а`) that every ditch stores. The Excel workbook has **one
sheet per trasse** (no combined cross-trasse total); each sheet stacks the cross block
then the longitudinal block for that trasse.

### Trasse per canal — layer suffix

One drawing holds ditches for many canals, so a single global `CANAL` is not enough.
The trasse of each ditch is taken from the **layer suffix**: a ditch on the bare base
layer takes the default `CANAL`; a ditch moved onto `<base>_<trasse>` takes `<trasse>`.

| Type | Base layer | Per-trasse layer | Example → trasse |
|---|---|---|---|
| Longitudinal | `inf_ct_toe` | `inf_ct_toe_<trasse>` | `inf_ct_toe_1в` → `1в` |
| Cross (run) | `inf_md_ditch` | `inf_md_ditch_<trasse>` | `inf_md_ditch_2б` → `2б` |
| Cross (connector) | `inf_md_connector` | `inf_md_connector_<trasse>` | matched by geometry; suffix ignored |

`trasse_for_layer(layer, base)` in `ditch_core/config.py` is the single place this is
decoded. **Workflow:** build as usual (everything lands on the base layers and gets the
default `CANAL`), then move each canal's ditch lines onto its `<base>_<trasse>` layer,
then run step 6 — the **refresh** re-reads each ditch's layer and rewrites its `Canal`
field, so the ведомости split per canal. `Index` restarts from 1 within each trasse.

Caveat: `ditch_03_build_long` (re-drape) and `ditch_04_build_cross` (build) only act on
the **base** layers, so re-running a build after moving lines to suffixed layers will
skip them — use the step-5 refresh scripts for post-move updates, which is what the
step-6 pipeline already does.

Set the default `CANAL` in `ditch_core/config.py` for the base-layer canal.

Requires Civil 3D open with the ditch drawing. The Excel step needs the system
Python (has `openpyxl`); it cannot run inside Dynamo.

## Step 7 — point-number blocks

Two plan-view scripts annotate the ditches with the existing DWG block
**`Номер_точки_канавы`** (attribute tag `#`). The block must already exist in the
drawing — the scripts only insert references to it.

- `ditch_07_draw_point_blocks` places one block at every **characteristic point**:
  - **Cross-ditch** → both endpoints of each run (`inf_md_ditch*`, tagged `ARHYZ_MD`).
  - **Longitudinal** → start/end, every plan PI (XY deflection > 5°) and every profile
    grade break (adjacent-segment grade change > 0.02) of each run (`inf_ct_toe*`,
    tagged `ARHYZ_LD`; cut-toe `ARHYZ_CT` lines are skipped).
  - A cross-ditch endpoint that coincides with a longitudinal vertex (the junction)
    collapses to a single block (merge tolerance 0.5 m).
  - Blocks land on `inf_md_point` with `#` left blank, tagged XData `ARHYZ_PT`.
    Idempotent: a re-run erases the previous `ARHYZ_PT` blocks and re-places them.
- `ditch_08_number_points` fills the `#` attribute with a single running number
  `1..N` across the **whole drawing**, ordered by station (insertion point projected
  onto `CONFIG.alignment_name`), ties broken by Y then X. Falls back to (Y, X) order
  if the alignment can't be found. Re-running renumbers from 1.

Both run in the open Civil 3D session via their `.dyn` (the same COM
`RUNDYNAMOSCRIPT` pattern as the other ditch scripts).

## Rates / methodology

All consumption rates (расход материалов) live in one place: **`ditch_core/rates.json`**,
split into a `cross` and a `long` section. Geotextile keeps `geo_base` + `geo_coef`
(×1.2) as separate fields, so the m²/м.п. value (`geo_base × geo_coef`) is traceable.

- Cross ditches: section `cross` — per м.п. (`*_per_m`) + flat гаситель terms
  (`*_killer`); read by `ditch_04_build_cross/volumes.py`.
- Longitudinal ditches: section `long` — per м.п. only, plus Reno-mattress
  (`mat_*`) and anchor (`anchor_per_m`) counts; read by `ditch_03_build_long/volumes.py`.

Edit a rate in `rates.json`, then run step 6 — the refresh recomputes every ditch's
PS from geometry and the ведомости/Excel pick up the new numbers (no code edit).

## GSI ditch at culvert outlets (`build_gsi_ditch`)

A separate, self-contained script (package `automation/scripts/tube/outlet/build_gsi_ditch/`, pattern
of `build_gsi_well`) that builds the **3D Reno-mattress GSI ditch** with a lofted trapezoid
lining (the mattresses bend up the side slopes — нагорные канавы). For the flat **outlet
apron (крепление выходное)** — mats laid flat + block walls — use `build_gsi_apron` below
instead. Unlike the pipeline above it is not draped on a
surface — its bottom follows the **FG design profile**. Spec: `.agents/prompts/build-gsi-ditch.md`;
geometry evolved centerline → closed contour → **two lines** (final:
`.agents/prompts/build-gsi-ditch-two-lines.md`, supersedes `build-gsi-ditch-redesign.md`).

**Inputs**
- **Canal name** (typed) → fuzzy-matched alignment + its **FG (проектный) profile**. FG is
  chosen by `ProfileType.FG`, falling back to a name match / sole non-surface profile.
- **Two long edges P1 and P2** — TWO **open** polylines picked one after the other (`P1` = one
  long side of the flat ditch bottom, `P2` = the other). They fix the gabions **in plan** (XY
  only, drawn Z ignored). Neither is a centerline — the ditch WIDTH is the P1↔P2 distance.
- **Two JSON files**, stored exactly like the canal configs (see `paths.py`):
  - `automation/scripts/tube/data/config/gsi_ditch_types.json` — the shared type catalog
    `{"types": {type_id: {bottom_w, d, m, t}}}` (analogue of `canal_types.json`). NOTE: `bottom_w`
    here is IGNORED for geometry — width comes from the P1/P2 pair; only `d`/`m`/`t` are used.
  - `automation/scripts/tube/data/config/gsi_ditches/<canal>.json` — **one file per ditch**, keyed by the canal
    name: `{"segments": [{from, to, type, ribs?}], "sta_offset"?: <m>}`. `from`/`to` accept ПК
    strings (`"ПК0+30.00"`) or plain metres, given in the **culvert profile's** stationing.
    `sta_offset` (metres to ADD to a config ПК to reach the alignment station) corrects the shift
    between the culvert-profile ПК and the alignment station the lines project to; gate with
    `params_at(s − sta_offset)`. The optional per-segment `"ribs": true` flag adds transverse
    gabion ribs across that segment's bottom (see below). The ditch is built only over the segment span.

**Build (two-line station-slice, alignment-oriented)**
1. Each line's vertices are projected onto the alignment (`AlignmentWrapper.station_offset_at`
   → `Alignment.StationOffset`, seed-value out-params); the covered span is the P1∩P2 station
   overlap `[max(lo), min(hi)]`.
2. Straight reaches are stepped by `builder._chord_stations`: each next station is solved so the
   **worst longitudinal 3D edge** of the piece (`max_i dist3d(ring_a[i], ring_next[i])` over the
   `section_pts` rings — the quantity `check_edge_lengths` verifies) equals `LOFT_STEP` exactly —
   the *exact-2.00* fix. Plain `loft_substations` advanced along the alignment (`LOFT_STEP/mag`, `mag`
   sampled only at the step start), landing the CENTRE chord near 2.0 but leaving the outer mattress
   edge at ~2.004, because the ditch is sliced between two hand-drawn lines P1/P2 (variable width,
   not parallel to the axis) so the outer top corners drift more than the centre. Edge stepping puts
   the longest edge on 2.000 and every shorter edge/centre just under it. доборные tail
   merge/even-split is preserved (via `corner_piece_len` / `split_even`).
   At every **plan PI** in span an **always-on virtual-arc fan** (`arcs.py`, ported from
   `build_canal_model`'s `SHARP_PI` regime but with the `deg`/`wide_types` gating **dropped** — the
   ditch is always wide) replaces the single corner piece: `R = top_w·1.1`, `N = max(4, N_outer,
   N_angle)` even fan slices PC..PT, each anchor carrying its own arc `(x,y,ax,ay)` so the slice's
   centre/orientation come from the arc while `bottom_w` is still a fresh P1/P2 slice. This keeps
   corner mattresses ≤ `LOFT_STEP` along flow and stops inner-corner overlap. Section orientation is
   otherwise the alignment's (`cross_axis_at`, `angle_at`); a PI whose arc is unavailable
   (missing slice/params, `top_w ≤ 0`, degenerate turn) falls back to a single `bisector_at` corner.
3. At each station the cross-line cuts P1 and P2 once each (`_line_cross` / `_slice_pair`, nearest
   crossing to the previous sample's offset when a wavy edge is hit twice): the two offsets give
   the local **centre** and **`bottom_w` = |o1 − o2|**. Z = `profile.elevation_at(s)` (FG, **no
   drop**); `d`/`m`/`t`/`type` come from `params_at(s − sta_offset)`.
4. Stations where either line is not crossed, width ≈ 0, or the station is in **no** segment become
   run breaks. Each maximal in-channel run is then emitted as **individual per-sub-station pieces**
   (one Reno mattress each), mirroring `build_canal_model`'s per-span loft: every adjacent
   sub-station pair is lofted on its own (`geometry.section_pts`, slope-corrected
   `mag = sqrt(1+slope²)`) into a separate `Solid3d` on `inf_gsi_ditch_mat`, XData `ARHYZ_GSD` +
   `Canal`. So a run of `N` sub-stations yields `N−1` mattress solids (matching the `mat=шт` count).
5. Idempotent: a re-run erases this canal's previous `ARHYZ_GSD` solids first (matched by the
   XData Canal string) — this already covers the many-solids case — so other canals' ditches on the
   shared layer are untouched.

**Rings export**: after the mattress loop every run's 9-point `section_pts` rings (station, emit
mode `tangent`/`arc`/`bisector`, and all 9 vertex coordinates) are written to
`automation/scripts/tube/data/gsi_ditches/<canal>.json` (`_export_rings`, path `paths.GSI_DITCH_DATA_DIR`). This is
the draw_gabion_view save-sections pattern: the build script saves its computed sections so the
callout annotator (`tube/outlet/build_gsi_ditch_points`) reads the BUILT geometry instead of recomputing
or re-picking anything. Export failure is logged as an error but does not abort the build.

**Property set** `Arhyz_GsiDitch` (**per piece**): `Canal`, `SectionType`, `Index` (a global
1-based mattress counter across all runs), `Length3D` (the piece's 3D centre-to-centre span) +
the Reno quantities (откопка / щебень / геотекстиль / перемещение / матрацы / анкеры) computed for
that piece's length (`n_turns = 0`), reusing the `ditch_03_build_long/volumes.py` rate model via
`build_gsi_ditch/volumes.py`.

**Transverse ribs** (`ribs.py`, ported from `build_canal_model`'s `RibBuilder` `stagger=True`
regime). For every segment with `"ribs": true` a **staggered (шахматный) row** of small gabion
baskets is laid across the bottom every `RIB_STEP` (1.7 m) along slope. Alternating rows carry
`n_a` and `n_b = n_a-1` baskets offset by half a pitch, so a gap in one row is covered by a basket
in the next. `n_a = max(2, ⌊(bottom_w+gap)/(RIB_MAX_LEN+gap)⌋)`, basket length =
`clamp(RIB_MIN_LEN, RIB_MAX_LEN, (bottom_w−(n_a−1)·gap)/n_a)`, each `RIB_SIZE` (0.17 m) square in
section, `RIB_GAP` (1.0 m) between baskets. Unlike the canal (fixed config width) the ditch rib's
centre and `bottom_w` are **re-sliced from P1/P2 at each rib station**, so `n_a`/basket length and
both lateral-position lists are recomputed per station and the row narrows/widens with the drawn
plan уширение; a station whose `n_a` row cannot fit a `RIB_MIN_LEN` basket (`(bottom_w−(n_a−1)·gap)
/n_a < RIB_MIN_LEN`) is skipped. Rib bars use the same U-vector slope correction as `section_pts`,
sit on `inf_gsi_ditch_rib`, carry XData `ARHYZ_GSD` + `Canal` (so re-run purge erases them) and a
`Arhyz_GsiDitchRib` PS (`Canal`, `BasketDim`, `BasketCount`, `Volume`). All tunable parameters
(stepping `GABION`, fan `ARC`, rib `RIBS`) live in `build_gsi_ditch/config.py` as frozen
dataclasses; `GABION`/`RIBS` mirror `build_canal_model/config.py` (kept in sync), `ARC` diverges
deliberately (coarse fan). Specs: `.agents/prompts/build-gsi-ditch-ribs.md`,
`build-gsi-ditch-corners-ribs-length.md`.

## GSI outlet apron (`build_gsi_apron`)

A separate script (package `automation/scripts/tube/outlet/build_gsi_apron/`, spec
`.agents/prompts/build-gsi-apron.md`) for the **flat GSI apron at a culvert outlet
(крепление выходное)** — the case where the lofted `build_gsi_ditch` model is wrong: the
bottom is a field of flat Reno mats and the sides are block walls, like `build_gsi_well`.

**Inputs**: canal name (typed → fuzzy-matched alignment, used for ORIENTATION only — no
profile is read) + picked polylines: **P1**, **P2** (the long footprint edges, drawn in 3D —
**their elevation sets the mat top**), then two **optional** start/end limit lines (XY
only; Enter/Esc skips each). Without limits the station span is the **P1∩P2 projected
overlap** and the footprint closes with straight caps between the line ends; a picked limit
overrides the nearer span end with its mean projected station. All picked lines are sewn
into one closed footprint ring by greedy endpoint proximity.

**Build** (**vertex-pair boundaries** per user 2026-07-14, spec
`.agents/prompts/build-gsi-apron-vertex-boundaries.md`; **flat mats on shared grid
points** per user 2026-07-15, spec `.agents/prompts/build-gsi-apron-flat-mats.md` —
supersedes the lofted-slab slicing of `build-gsi-apron-loft.md` /
`build-gsi-apron-slice-mats.md`):
- **Boundaries = drawn corner pairs** (`_boundaries`): a leg boundary is the SEGMENT
  between two OPPOSITE P1/P2 vertices («углы друг напротив друга») — both plan corners
  and profile grade breaks are drawn as vertices, so there is NO alignment-station
  projection, no PI bisector, no break detection (all three had produced phantom 0.6–0.8 m
  sub-legs on В-5А-3, see `docs/process/testing/tube.md`). P2 is direction-normalized to P1;
  vertices pair by index (by projected station on unequal counts, WARN). An interior
  boundary is a LEG JOINT only where the midline kinks — plan deflection ≥ `miter_min_deg`
  or slope change > `break_slope_tol`; a collinear helper pair is not dropped but stays
  an INTERMEDIATE section of its leg (surface + footprint follow the drawn edges).
  A boundary pair disagreeing in Z more than `z_across_tol` is WARN-logged.
  Near-duplicate boundaries (double drawn vertex / pairing reuse on unequal vertex
  counts) are merged within `boundary_merge_tol` so neighbouring legs always share one
  boundary (the В-5А-3 slit).
- **Per-leg loft between tilted sections** (the build_gsi_ditch_walls pattern, spec
  `.agents/prompts/build-gsi-apron-perp-slicing.md`, supersedes the flat fitted-plane
  mats): each kept boundary becomes a planar quad Region — the drawn segment plus its
  copy translated `mat_h` along the DROP vector = negated mean of the adjacent legs'
  up normals (`boundary_region`; a translated copy is a parallelogram → planar).
  Shared boundaries use ONE section geometry, so legs join flush BY CONSTRUCTION; the
  loft is ruled (`loft_slab`, `LoftOptionsBuilder.Ruled`), intermediate collinear
  pairs ride as extra sections. Thickness is an honest 0.5 m along the normal; no
  plane fitting — mats inherit the ±cm ruled twist (gabions flex). `leg_surface` /
  `_ruled_patch` still describe the loft's top exactly (its top edges are the drawn
  segments) and drive the local slicing metric.
- **Slicing** (`slice_mats`): vertical column planes across the flow (cross tilt
  ≤ ~0.1 → within a few degrees of perpendicular), then per-strip row planes
  PERPENDICULAR to the strip's sloped flow direction (normal `(ax, ay, m)/smag`,
  anchored on the top surface) — mat end faces follow the slope instead of being
  vertical, neighbouring mats share every cut plane, and mats sum exactly to the slab;
  slivers below 1e-3 m³ are dropped.
- **Grid layout** (unchanged rules): 6 m strips across the flow first (доборные over
  the cross-metric extent), then rows per strip anchored at the STRIP's own far extent
  (corner mats cover skewed-joint corners without mini wedges; row stations differ
  between strips by design). Piece sizes obey the **доборные rule** (`dobornie_pieces`,
  `mat_min` = 0.5 m): a shorter tail merges with the neighbouring full piece and splits
  evenly (6.4 → 2+2+1.2+1.2), pitches divided by the strip's own slope metric (2 m
  along the slope). A NARROW strip is covered LENGTHWISE — the 6 m mat side runs along
  the flow (picture «Улучшение раскладки КВ ГСИ»); narrow = bounding width ≤
  `mat_along` (2 m) OR mean material width ≤ `mat_along` with bounding ≤ 2×`mat_along`
  (thin wedge strips on skewed legs, picture «Нет соединение КВ»).
- **Limit-line trim**: the first/last leg SLAB is BoolIntersect-ed with the
  sewn-footprint prism before slicing, and only when a limit line was picked.

Idempotent: every solid carries XData `ARHYZ_GSAP` + canal; a re-run purges only this
canal's apron solids. Layers grouped under the "GSI Apron" filter. Wall blocks / upper
tiers and property sets / quantities are TODO-frozen in v1.

## GSI bottom outlines (`draw_gsi_bottom`)

A drawing script (package `automation/scripts/tube/outlet/draw_gsi_bottom/`, spec
`.agents/prompts/draw-gsi-bottom.md`) tracing the BOTTOM faces of the КВ GSI solids
with closed 3D polylines and wrapping them into ONE block. Sources by layer
(`config.py::BOTTOM.source_layers`, v1 = `inf_gsi_apron_mat`; the wall layer joins
later). The bottom outline comes from the Brep API (`acdbmgdbrep`, verified in
`debug/dump_brep_bottom`; `loop.Vertices` is already in loop order). A lofted mat's
bottom is often SEVERAL Brep faces, so all of them are merged: horizontal-ish faces
(unit Newell |nz| ≥ 0.5) are bottom when no other horizontal face lies below at their
plan centroid (plane comparison — mean z lies on steep mats); their edges are pooled,
edges shared by two bottom faces (the creases, «линии перегиба») are dropped, and the
rest chain into the closed outer ring(s). Output polylines land
on `inf_gsi_apron_bottom` (color 8 grey, DASHED, ByLayer → "GSI Apron" filter), all
inside a new block (origin = the first polyline's first vertex, one BlockReference
inserted at the origin → renders in place). Block name typed in the command line
(default `GSI_KV`); an existing name gets a numeric suffix — each run makes a new
block, nothing is purged.

## GSI ribs (`build_gsi_ribs`)

A STANDALONE script (package `automation/scripts/tube/outlet/build_gsi_ribs/`, spec
`.agents/prompts/build-gsi-ribs.md`) placing the transverse gabion rib rows (рёбра,
шахматный порядок) across a GSI-ditch bottom from the two picked 3D edge lines P1/P2 —
it supersedes the rib placement embedded in `build_gsi_ditch` for re-runs, and fixes
its defect: basket length there was recomputed from the sliced width, so baskets
SHRANK proportionally to the ditch width.

**Inputs**: picked P1 then P2 (3D polylines, their Z = rib elevation), then which sides
carry a wall (both/p1/p2/none) — the row extent is inset by `wall_inset` (1 m, the
`build_gsi_ditch_walls` strip depth) on those sides so ribs stop at the wall face. No
alignment or profile. Vertex-pair boundaries (the apron convention; unequal counts pair
by chord projection, near-duplicates merge within `boundary_merge_tol`).

**Placement** (`config.py::RIBS`): rows walk the legs from the drawn downstream end
backwards every `step` = 1.7 m ALONG THE SLOPE (remainder carried across legs); at
each station the cross line is intersected with EACH 3D chain (`cross_hits`) — the hit
offsets give the row extent, the hit Zs make the bar FOLLOW THE CROSS-TILTED bottom
(horizontal bars at the midline z sank into the mats near the higher edge, В-5А-3). Baskets are
**FIXED `basket_len` = 3.0 m** — `n = int((w+gap)/(len+gap))` full baskets (шахматный:
n ≥ 2 → centered rows alternate n and n−1, offset by half a pitch; n == 1 — e.g. the
6 m КВ after insets — the A row is ONE standard basket centered and the B row is TWO
cut bars filling the extent edge-to-edge with the `gap` centered, 6 → 2.5+1+2.5, user
2026-07-15); the edge margins absorb the width variation. A row narrower than one basket
gets a single full-width cut bar (доборная); below `min_width` = 0.5 the station is
skipped. The bar solid is the donor slope-corrected loft (perpendicular to 3D flow,
cross-section `size` = 0.17). Layer `inf_gsi_ditch_rib` (the same the ditch script
used → "GSI Ditch" filter); a re-run purges that layer, so ribs from either script are
replaced. Property sets are TODO-frozen in v1.

## GSI ditch walls (`build_gsi_ditch_walls`)

A separate script (package `automation/scripts/tube/outlet/build_gsi_ditch_walls/`, spec
`.agents/prompts/build-gsi-ditch-walls.md`) that lays **single-tier GSI 2×1×1 block walls**
along the edges of a culvert-outlet GSI ditch — the build_gsi_well placement algorithm
(full box rows + boolean-intersect clip) unrolled onto open lines. No alignment or profile
is involved.

**Inputs**: the two picked ditch edge lines **P1** then **P2** (open `Polyline` /
`Polyline2d` / `Polyline3d`; **their own Z is the wall bottom**), then a typed choice of
which walls to build — `both` (Enter) / `p1` / `p2` (not every ditch gets two walls). Both
lines are always picked even for one wall: each wall's **INWARD** side is where the other
line lies (side of the other line's midpoint at the nearest wall segment).

**Build** (`geometry.py`): the wall strip is the picked chain + its 1.0 m inward offset,
mitre-joined at plan PIs (mitre spike capped at 4× depth), perpendicular at the open ends.
Per plan segment, the row spans the quad's FULL along-length extent — from the mitre's back
extent to its forward extent (on the outer side of a turn the mitre edge leans backwards
past the start perpendicular — the В-5А-1 corner-gap fix, see `docs/process/testing/tube.md`)
— split by the **доборные rule** (`_row_pieces`: full 2 m pieces measured ALONG THE SLOPE
(plan pitch `/mag`), a remainder < 0.5 m merges with the last piece and splits evenly,
2.27 → 1.135+1.135), so no block ever exceeds the 2 m basket max and no loose sliver
survives; a corner is always a terminal block **1 (inward) × 1 (high)** trimmed at the
mitre angle. The wall body is a **LOFT along the guide line** (user 2026-07-15 — «лофт
по направляющей, потом резать»; earlier per-segment tilted boxes left wedge HOLES at
plan-turn + grade-change vertices and fitted-plane prisms had vertical mitre edges, see
the В-5А walls row in `docs/process/testing/tube.md`): at every chain vertex a
cross-section region `[v, off, off+H·u, v+H·u]` (`_section_region`) with the up vector
`u` = mean of the adjacent segments' strip normals — height PERPENDICULAR to the line
everywhere, and adjacent segments loft from the SAME section, so joints are flush by
construction, no plane fitting at all. Each segment's loft is then sliced
(`_split_row`) by planes perpendicular to the sloped wall direction at доборные
stations — neighbouring blocks share each cut plane, slicing partitions the solid
(blocks sum exactly to the wall); degenerate slivers dropped by volume.

Solids land on `inf_gsi_ditch_wall` (color 4, joins the existing **"GSI Ditch"** layer
filter); a re-run purges all Solid3d on that layer first (idempotent, but per-drawing —
not per-canal). Flagged for the first visual check: the block-centre Z sampling rule
(vs seating on the lower end) and corner pieces at sharp PIs. Property sets / quantities
are TODO-frozen in v1.

## GSI-ditch point callouts (`tube/outlet/build_gsi_ditch_points`)

Annotation script (package `automation/scripts/tube/outlet/build_gsi_ditch_points/`) that dimensions a
built GSI ditch at the **corners of the built solids**: the user enters the canal name and the
script reads the rings JSON `build_gsi_ditch` exported to `automation/scripts/tube/data/gsi_ditches/<canal>.json`
(exact filename, else normalized-name match) — nothing is picked, and the points always coincide
with the lofted mattresses. Per run, ring indices **7/6** (**P6/P5** — the outer wall-base
corners, the same points draw_gabion_view dimensions on a canal) form the left/right callout
chains; a dynamic **`point_number`** callout goes to: both ends of each chain, every contour
**corner («излом»)** — plan direction change over `LAYOUT.corner_angle_deg` (1.0° default;
straight 2-m mattress joints are collinear and drop out, corner-fan anchors and width kinks
survive) — and every boundary of a **non-standard mattress** (доборный / corner piece / fan
slice: worst longitudinal edge deviating from the exported `loft_step` by more than 0.02 m), even
where the contour runs straight. Numbering is continuous
т.1..т.N in capsule-loop order (left chain forward, then right chain back), across runs,
restarting from т.1 every script run.

Placement is the closed-rail "паучок" scheme ported from
`draw_gabion_view/builder.py::_rail_placements` (the canal annotator that runs after
`build_canal_model`): each run's corner loop forms ONE closed capsule outline, offset **outward**
— the candidate whose area grows (`LAYOUT.rail_offset`, 4.0 m default) — and all callout red
points ride that single rail **in intrinsic loop order**: the four cap-adjacent corners anchor at
the start of the cap rounding («торцы в начало скруглений»), the unwrap seam is rotated onto the
largest same-side gap and one monotone isotonic spread keeps `LAYOUT.rail_gap` (2.5 m) between
neighbours, so leaders never invert or cross. Layout parameters live in the package's `config.py`
(plain `LayoutParams` class, `polka_len` 1.647 in sync with draw_gabion_view). The block is placed
by deep-cloning a manually-inserted `point_number` template (dynamic block: flip +
`Положение1 X/Y`, grip backed out by the polka length). Blocks land on `inf_gsi_ditch_pnt`
(grouped under the same "GSI Ditch" filter), carry XData `ARHYZ_GSDPT`, and a re-run purges only
its own clones (excavation `ARHYZ_EXC` and gabion-view blocks untouched). Spec:
`.agents/prompts/build-gsi-ditch-points.md` (original P1/P2-vertex version; superseded by the
rings-JSON input).
