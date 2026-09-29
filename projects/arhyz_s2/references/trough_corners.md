# Trough monolith at plan bends (ver_0.59+)

## Concept

At a plan PI (horizontal bend), factory troughs cannot span the corner.
The gap between the last trough of the incoming sub-segment and the first trough
of the outgoing sub-segment is filled with a **cast-in-place (monolith) piece**.

The monolith is modelled as two straight lofts through a **widened bisector section**
at the PI:

```
  sta_A                 pi_sta               sta_B
  (end of last          (bisector,           (start of first
   factory trough)       widened)             factory trough)
       |                    |                    |
       [== loft 1 (straight) ==][== loft 2 (straight) ==]
```

Layer: `lk_mono` (body), `pt_mono` (cover).

---

## Bisector section

The bisector section is a standard trough cross-section with **all horizontal
dimensions scaled by `1 / cos(φ/2)`**, where φ is the deflection angle at the PI.

### Why this scale factor

When a trough of half-width `hw` is cut perpendicular to the bisector direction,
the apparent width of the cut face in the bisector plane is `hw / cos(φ/2)`.
Scaling the section by this factor makes the loft faces flush with the trough ends
on both sides — no gap, no overlap at the join lines.

### Fields that scale (horizontal)

`outer_w`, `inner_top_w`, `inner_bot_w`, `chamfer`, `prep_overhang`

### Fields that do NOT scale (vertical)

`outer_h`, `bot_wall`, `cover_t`, `prep_t`

### Bisector direction

```python
ax_bis, ay_bis = compute_bisector(align, pi_sta, sta_end_align)
# forward direction = average of incoming and outgoing unit vectors
# lateral direction (perpendicular, used for section):
rx_bis, ry_bis = -ay_bis, ax_bis
```

---

## Slope tilt

Each section uses the 3D slope at its station to tilt the "up" vector perpendicular
to the 3D alignment axis. This keeps section end-faces square to the trough axis,
not to the global Z.

- `sta_A` section: slope at midpoint `(sta_A + pi_sta) / 2`
- bisector section: slope at `pi_sta`
- `sta_B` section: slope at midpoint `(pi_sta + sta_B) / 2`

---

## Code location

`loft_trough_seg()` — pass 3, `3d_model_ver_0.59.py`

```python
phi   = deflection_angle(align, pi_sta, sta_end_align)
scale = 1.0 / cos(phi / 2)

ax_bis, ay_bis = compute_bisector(align, pi_sta, sta_end_align)
rx_bis, ry_bis = -ay_bis, ax_bis

body_A,  cover_A  = sections_at(sta_A, rx_A, ry_A, slope=slope_left)
body_PI, cover_PI = sections_at_scaled(pi_sta, rx_bis, ry_bis, scale, slope=slope_mid)
body_B,  cover_B  = sections_at(sta_B, rx_B, ry_B, slope=slope_right)

build_solid(body_A,  body_PI, body_mono_layer)   # loft 1
build_solid(cover_A, cover_PI, cover_mono_layer)
build_solid(body_PI, body_B,  body_mono_layer)   # loft 2
build_solid(cover_PI, cover_B, cover_mono_layer)
```

---

## History

| ver | approach |
|-----|----------|
| ≤ 0.25 | SAT collision detection on oriented rectangles (deprecated) |
| 0.26–0.55 | `trough_section_pts_miter()` — per-point station shift onto bisector plane |
| 0.56–0.58 | two lofts per PI arm (A→PI_left, PI_right→B), different lateral dirs; broken by `LoftNormalsType` import |
| **0.59+** | **bisector section widened by `1/cos(φ/2)`, two straight lofts** |

---

## See also
- [trough_placement.md](trough_placement.md) — placement rules that drive corner geometry
- [trough_section_points.md](trough_section_points.md) — cross-section points used in miter calc
- [gabion_corners.md](gabion_corners.md) — analogous PI handling for gabions