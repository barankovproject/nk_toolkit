# Config File Formats

## canal_types.json

**Path:** `config/canal_types.json`  
**Purpose:** Cross-section geometry for each gabion canal type (1–8).

```json
{
  "types": {
    "1": { "bottom_w": 0.3, "d": 0.5, "m": 1.0, "t": 0.1 },
    ...
  }
}
```

| Field      | Description                                      |
|------------|--------------------------------------------------|
| `bottom_w` | Bottom width (m) — distance P1 to P2            |
| `d`        | Vertical depth (m) — P1/P2 up to P0/P3         |
| `m`        | Slope coefficient (horizontal : vertical)        |
| `t`        | Wall thickness (m) — perpendicular to wall face |

Used by both `project_xy` and `3d_model` scripts at runtime via `import json`.  
Scripts raise a clear error if any param is zero (type not yet filled in).

---

## trough_types.json

**Path:** `config/trough_types.json`  
**Purpose:** Cross-section geometry for each trough type (9–12).  
See `trough_types.md` for full dimension table.

```json
{
  "types": {
    "10": {
      "outer_w": 1.18, "outer_h": 0.88,
      "inner_top_w": 1.06, "inner_bot_w": 0.76,
      "bot_wall": 0.10, "cover_t": 0.12, "chamfer": 0.05,
      "prep_overhang": 0.10, "prep_t": 0.10
    },
    ...
  }
}
```

---

## canals/\<name\>.json

**Path:** `config/canals/<alignment_name>.json`  
**Purpose:** Per-canal configuration — type segments by station, optional widening at end.  
One file per alignment. Filename = alignment name (Cyrillic OK, matches Civil 3D).

```json
{
  "segments": [
    { "from": "ПК0+00.00", "to": "ПК0+50.00", "type": 3, "ribs": false },
    { "from": "ПК0+50.00", "to": "ПК1+00.00", "type": 5, "ribs": true },
    { "from": "ПК1+00.00", "to": "ПК1+50.00", "type": 10, "ribs": false }
  ],
  "widening": { "b": 6.0, "length": 10.0, "ribs": true }
}
```

`"widening": null` or absent — if no widening.

### segments

Ordered list covering the full alignment length.  
Station format: `ПКX+YY.YY` → `X * 100 + YY.YY` metres (standard Russian surveying notation).

| Field   | Description                                                                 |
|---------|-----------------------------------------------------------------------------|
| `from`  | Start station in ПК notation                                                |
| `to`    | End station in ПК notation                                                  |
| `type`  | Canal type key: 1–8 = gabion (canal_types.json), 9–12 = trough (trough_types.json) |
| `ribs`  | `true` = place ribs (ГСИ) on gabion segments only; ignored for trough types |

### type_table

Optional, top-level (sibling of `segments`/`widening`): selects an ALTERNATE
gabion type catalog instead of the default `canal_types.json`. Absent (all
Stage 2 `НК-*` canals today) = `canal_types.json`, unchanged.

```json
{ "type_table": "stage1", "segments": [ ... ] }
```

Needed because Stage 1 (Этап 1) canals use their own type numbers (e.g. "10",
"11") that collide with Stage 2's existing trough-type numbers in
`trough_types.json` (9-12) — a separate table keeps the two numbering schemes
independent instead of merging them into one ambiguous dict. Known tables
(`build_canal_model/config.py::_TYPE_TABLES`, a fixed, hardcoded set — an
unknown name raises immediately):

| Name | File |
|------|------|
| `default` | `config/canal_types.json` |
| `stage1` | `config/canal_types_stage1.json` |

Same `{"types": {...}}` schema as `canal_types.json` in either table. See
`.agents/prompts/canal-model-stage1-type-table.md` for the full rationale.
Only `canal_builder.py` (the build script) resolves this field so far — other
consumers of the default type table (`draw_gabion_view`, `build_corridors`,
`draw_location_plan`, `report_canal`) still always read `canal_types.json`
regardless of a canal's own `type_table`; they need the same fix before they
can be used on a Stage 1 canal.

### widening

Widening at the **end** of the canal only. Always a gabion cross-section, regardless
of what the last segment type is.

`d`, `m`, `t` taken from the last **gabion** type in segments (trough types are skipped).

#### Geometry

```
sta_end - length  ←  transition starts here
    ↓
sta_end - length + 2m  ←  flat zone starts (bottom_w = b)
    ↓
sta_end  ←  canal end
```

- **`length`** = total widening zone (m), measured from `sta_end`.  
  This includes both the transition zone and the flat zone.
- Transition zone = first `WIDENING_TRANS = 2.0 m` of the widening:  
  `bottom_w` interpolates linearly from the last gabion type's `bottom_w` → `b`.
- Flat zone = remaining `length - 2.0 m`:  
  `bottom_w = b` (constant).

#### Interaction with trough segments

If the last segment is a trough type, the trough is clipped at `sta_end - length`.
From that station to `sta_end` the script draws gabion widening, not trough.

| Field    | Description                                                        |
|----------|--------------------------------------------------------------------|
| `b`      | Bottom width (m) at the fully widened section                      |
| `length` | Total widening zone length (m) from canal end, including 2m transition |
| `ribs`   | `true` = place staggered ribs (шахматный порядок) in the flat zone |

---

---

## kv_canals/\<name\>.json — КВ canal config (separate pipeline)

КВ canals (one-off water-crossing structures, e.g. В-4А-2) are NOT built by
`build_canal_model` at all — that package stays НК-only, untouched. КВ canals have
their own standalone scripts under `automation/scripts/kv/`:

- `kv/build_gsi_kv_trapezoid/` — config-driven (no interactive picks). Reads
  `config/kv_canals/<canal_name>.json`: `{"spans": [{"from", "to", "bottom_w", "d",
  "m", "t", "gsi_pieces": [...]}]}` (path derived from `paths.CANALS_DIR`'s sibling,
  same `DATA_ROOT` convention as everything else). One continuous loft per along-slope
  span, same `section_pts` math family as `GabionBuilder` but re-implemented standalone
  — plan PIs inside a span get a bisector-miter corner piece, or (when that corner
  window is empty, e.g. a near-90° turn) a virtual-arc fan of thin radial slices;
  profile PVIs are also hard station breaks so a step's slope is never sampled across a
  grade change. Only stations inside the given span(s) are built — a КВ canal's GSI may
  cover only part of the alignment (В-4А-2: ПК0+00–0+71.60 is a труба, out of scope).
  `gsi_pieces` (optional) is cutting-list metadata — which physical GSI mattresses a
  cross-section is assembled from (e.g. `["4x2x0.5", "4x2x0.5"]`); when there are
  exactly 2, the loft solid is actually SPLIT into two solids at the canal axis, each
  tagged with its own `Arhyz_Gabion_Baskets` entry.
- `kv/build_gsi_kv_boxed/` — interactive, mirrors `build_gsi_apron`'s UX: canal name
  typed, then P1/P2 lines picked in the drawing (opposite drawn corners = leg joints),
  lofted and sliced into fixed-size mats via the shared `kv/gsi_mat_geometry.py`.

Both tag solids via `kv/gsi_kv_propset.py` (`Arhyz_Gabion`/`Arhyz_Gabion_Baskets`,
`Canal=<canal name>`) — the SAME PropertySetDefinition names `build_canal_model` uses,
so a future cross-canal quantity report can query `Arhyz_Gabion` by `Canal` and get both
НК and КВ solids in one place, without either pipeline importing the other's code.

## See also
- [section_points.md](section_points.md) — gabion cross-section geometry driven by these params
- [trough_types.md](trough_types.md) — trough_types.json fields and dimensions
- [widening_assemblies.md](widening_assemblies.md) — assembly naming derived from widening config