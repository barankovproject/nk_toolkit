# Trough placement logic (3d_model.dyn, ver_0.50+)

## Architecture overview

Troughs are placed **element-by-element** (not loft-whole-then-slice).
Each trough is a two-region loft: start cross-section → end cross-section.

```
loft_trough_seg(tp, tp_key, seg_s, seg_e, plan_pi_stas, pvi_stas, ...)
```

The function runs three passes:

```
Pass 1 → compute zone data (n, trim, PIECE_eff, …) for every sub-segment
Pass 2 → place factory troughs (standard + trimmed)
Pass 3 → loft monolith fills at plan PI gaps
```

---

## Sub-segmentation at plan PIs

Plan PI stations inside `[seg_s, seg_e]` split the trough range into sub-segments:

```
seg_s  [PI_1]  [PI_2]  seg_e
  sub0    sub1    sub2
```

Sub `k=0` (first): troughs start flush at `seg_s` — no setback on the left.  
Sub `k>0` (after a PI): left setback `d_left = (outer_w/2) × tan(phi/2)` where `phi` is the plan deflection angle at the PI. Same formula for `d_right` when the sub ends at an internal PI.

---

## Pass 1 — zone data per sub-segment

For each sub-segment `[sub_s, sub_e]`:

### Slope-corrected sizing

```python
sta_zone_m  = (sub_s + sub_e) / 2.0
slope_zone  = get_slope(profile, sta_zone_m)          # dZ/dX at midpoint
mag_zone    = sqrt(1 + slope_zone²)
LEN_eff     = TROUGH_STD_LEN / mag_zone               # horizontal body span → 3D = 2.99 m
PIECE_eff   = LEN_eff + TROUGH_GAP                    # horizontal pitch (gap stays 0.01 m)
```

`TROUGH_STD_LEN = 2.99 m`, `TROUGH_GAP = 0.01 m`.

On flat ground: `PIECE_eff ≈ 3.00 m` (same as before).  
On 65% slope (`mag ≈ 1.193`): `LEN_eff ≈ 2.507 m`, `PIECE_eff ≈ 2.517 m` — troughs are
shorter horizontally but exactly 2.99 m in 3D.

### Trough count and trim

```python
available = (sub_e - sub_s) - d_left - d_right
n         = int(available / PIECE_eff)         # full factory troughs
remaining = available - n * PIECE_eff
trim_len  = remaining - TROUGH_GAP             # trimmed trough length
has_trim  = trim_len >= MIN_TRIM               # MIN_TRIM = 2.0 m (horizontal)
```

### Zone offset (centering)

```python
zone_offset = 0.0 if (is_first or has_trim) else remaining / 2.0
zone_start  = sub_s + d_left + zone_offset
```

- First sub (`k=0`) and any sub with a trim: troughs start flush at left edge.
- Others: remaining space split equally before first trough and after last trough.

### Physical end of last trough

```python
if has_trim:
    trough_end = zone_start + n * PIECE_eff + trim_len
elif n > 0:
    trough_end = zone_start + (n - 1) * PIECE_eff + LEN_eff
else:
    trough_end = zone_start   # empty zone (no troughs fit)
```

`trough_end` is the right edge of the last trough body — used as the left anchor of the monolith fill in Pass 3.

### Stored in zones dict

`zone_start`, `n`, `has_trim`, `trim_len`, `trough_end`, `PIECE_eff`, `LEN_eff`, `slope_zone`.

---

## Pass 2 — place factory troughs

For each zone (sub-segment):

```python
for i in range(n):
    sta_A = zone_start + i * PIECE_eff
    sta_B = sta_A + LEN_eff
    sta_m = (sta_A + sta_B) / 2.0
    ang   = get_xy_angle(align, sta_m)
    rx_v, ry_v = -sin(ang), cos(ang)
    body_A, cover_A = sections_at(sta_A, rx_v, ry_v, slope=slope_zone)
    body_B, cover_B = sections_at(sta_B, rx_v, ry_v, slope=slope_zone)
    build_solid(body_A, body_B, body_layer)
    build_solid(cover_A, cover_B, cover_layer)
```

Trimmed trough (if `has_trim`): same but `sta_A = zone_start + n * PIECE_eff`, `sta_B = sta_A + trim_len`, layer = `lk_cut` / `pt_cut`.

### Cross-section tilt (`sections_at`)

```python
def sections_at(sta, rx_v, ry_v, slope=None):
    x, y = get_xy(align, sta)
    z    = profile.ElevationAt(sta)
    if slope is None:
        slope = get_slope(profile, sta)
    mag  = sqrt(1 + slope²)
    s_a, c_a = slope/mag, 1/mag
    body, cover, _ = trough_section_pts(
        x, y, z, rx_v, ry_v, tp,
        ux = -s_a * ry_v,   # "up" vector tilted along slope
        uy =  s_a * rx_v,
        uz =  c_a,
    )
    return body, cover
```

**Why tilt the up-vector:** with `uz=1` (vertical) the end face of the trough is a vertical plane, which causes a visible mismatch at slope changes. Tilting `(ux, uy, uz)` so it is perpendicular to the 3D alignment tangent makes the end face perpendicular to the trough axis — "walls pointing up, extruded along the slope."

**Why use `slope_zone` (not per-trough midpoint slope):** both cross-sections of a single trough must use the same slope. If `sta_A` and `sta_B` straddle a profile PVI they get different slopes → non-parallel sections → 3D edge lengths 3.04–3.05 m instead of exactly 2.99 m. Using the zone midpoint slope for all troughs in the zone fixes this.

---

## Pass 3 — monolith fill at plan PI gaps

For each internal PI between sub `k` and sub `k+1`:

```
trough_end_prev   PI   zone_start_next
      [monolith left] ← PI → [monolith right]
```

Two separate 2-section lofts (not a 3-section smooth loft — that would round the corner):

```python
# left half: trough_end_prev → bisector plane at PI
build_solid(body_A,    body_PI_l,  body_mono_layer)
build_solid(cover_A,   cover_PI_l, cover_mono_layer)

# right half: bisector plane at PI → zone_start_next
build_solid(body_PI_r, body_B,     body_mono_layer)
build_solid(cover_PI_r, cover_B,   cover_mono_layer)
```

**PI bisector direction:** `ang_PI = ang_in + Δang/2` where `Δang = ang_out − ang_in` (wrapped to `(−π, π]`).

**Slope for each half:** midpoint slope of that half, to keep sections parallel within each loft:

```python
slope_left  = get_slope(profile, (sta_A  + pi_sta) / 2)
slope_right = get_slope(profile, (pi_sta + sta_B)  / 2)
```

---

## Sandy preparation (подготовка)

The prep slab is **monolithic cast-in-place concrete** — it is poured as one continuous bed
under the entire trough segment. There are **no gaps** between factory-piece spans, cut pieces,
or monolith zones. The contractor simply casts it end-to-end without interruption.

**Geometry** (from `trough_section_pts`):
```
width  = outer_w + 2 × prep_overhang   (wider than the trough on each side)
height = prep_t                         (thickness, typically 0.10 m)
bottom = trough bottom face (z_bot = -bot_wall)
```

**Build rule:** one solid per sub-span (`sub_s → sub_e`), not one per factory trough.
No gaps, no alignment to the 2.99 m piece grid. The prep solid spans the full available
length of each sub-span including the `d_left`/`d_right` setback zones and the monolith
gap — i.e., it runs from `sub_s` to `sub_e` without any setback.

**Layer:** all prep (under factory pieces, cut pieces, and monolith) → single layer
`inf_model_canals_3d_t{N}_prep`. Defined in `config/layers.json`; created by `layers.dyn`.


---

## Layers

| Part | Layer |
|------|-------|
| Standard body (лоток 2.99 м) | `inf_model_canals_3d_t{N}_lk` |
| Standard cover (крышка) | `inf_model_canals_3d_t{N}_pt` |
| Trimmed body (доборный лоток) | `inf_model_canals_3d_t{N}_lk_cut` |
| Trimmed cover | `inf_model_canals_3d_t{N}_pt_cut` |
| Sandy preparation — all zones | `inf_model_canals_3d_t{N}_prep` |
| Monolith body + cover (PI, PVI, end) | `inf_model_canals_3d_t{N}_mono` |

`_lk_cut` and `_pt_cut` are created on the fly via `ensure_layer()`.
`_prep` and `_mono` are defined in `config/layers.json` and created by `layers.dyn`.

---

## Key constants

| Name | Value | Meaning |
|------|-------|---------|
| `TROUGH_STD_LEN` | 2.99 m | target 3D length of each factory trough |
| `TROUGH_GAP` | 0.01 m | horizontal gap between troughs |
| `MIN_TRIM` | 2.0 m | minimum allowed trimmed-trough horizontal length |
| `MONO_MIN_ZONE` | 0.2 m | mono zone shorter than this is skipped |
| `SLICE_END_GAP` | 0.05 m | don't slice closer than this to `seg_e` |

---

## Config references

- `config/trough_types.json` — geometry per type (see `trough_types.md`)
- `config/canals/<name>.json` — segment `"type": 9–12` triggers trough placement
- `trough_types.md` — outer_w, outer_h, bot_wall, cover_t, etc.
- `trough_section_points.md` — cross-section point layout

---

## See also
- [trough_corners.md](trough_corners.md) — miter geometry at plan PIs
- [trough_section_points.md](trough_section_points.md) — cross-section point layout
- [trough_types.md](trough_types.md) — type dimensions (outer_w, inner_bot_w, cover_t, etc.)
- [../../../../docs/platform/01_civil3d_errors.md](../../../../docs/platform/01_civil3d_errors.md) — bugs #9 #12 #14 #20 #21: monolith and zone issues