# Trough Types Reference

Source: cross-section drawing with Types 9–12, dumped via `dump_trough_labels.dyn`.
All dimensions in **mm**. Drawing units are mm (1:1). 3D model uses **meters**.

## Catalog designations

| Type | ЛК (trough) | ПТ (cover) | L_element |
|------|-------------|------------|-----------|
| 9  | ЛК 300.60.60-4   | ПТ75.60.8-15      | 840  |
| 10 | ЛК 300.120.90-4  | ПТ 300.120.12-15  | 2990 |
| 11 | ЛК 300.180.60-5  | ПТ 300.180.20-15  | 2990 |
| 12 | ЛК 300.300.150-5 | ПТ 300.300.25-15  | 2990 |

Note: Тип 9 uses a shorter element (L=840 mm) and a special narrow cover (ПТ75).

## Cross-section dimensions (mm)

All measured from drawing geometry (layer `!габион` = trough + cover, `!рельеф` = preparation).

| Parameter        | Тип 9 | Тип 10 | Тип 11 | Тип 12 |
|-----------------|------:|-------:|-------:|-------:|
| outer_width      |   580 |   1180 |   1780 |   2980 |
| outer_height     |   580 |    880 |    580 |   1480 |
| wall_top_thick   |    50 |     60 |     80 |    100 |
| inner_top_width  |   480 |   1060 |   1620 |   2780 |
| inner_bot_width  |   300 |    760 |   1340 |   2280 |
| inner_depth      |   510 |    780 |    460 |   1280 |
| bottom_wall_thick|    70 |    100 |    120 |    200 |
| cover_thickness  |    80 |    120 |    200 |    250 |

## Sand preparation (constant for all types)

- thickness: 100 mm
- overhang each side: 100 mm
- prep_total_width = outer_width + 200 mm

## Inner profile shape

The inner cavity is trapezoidal with sloped walls (no exact taper angle stored —
derive from inner_top_width vs inner_bot_width and inner_depth if needed).

Bottom corners have a small chamfer/fillet visible in the drawing
(approx 50–150 mm horizontal × 50–150 mm vertical depending on type).

## Alignment circle (трасса point)

Each cross-section has a CIRCLE on layer `0` (r≈90 mm in drawing coords)
marking the alignment trace point. Position relative to section origin:
- Тип 9:  center_x ≈ mid of outer_width, at inner bottom level
- Тип 10: same
- Тип 11: same
- Тип 12: same

---

## See also
- [trough_section_points.md](trough_section_points.md) — cross-section point layout using these dimensions
- [trough_placement.md](trough_placement.md) — placement and 2.99 m cutting rules
- [config_format.md](config_format.md) — trough_types.json format and segment type field