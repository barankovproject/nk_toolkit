# Gabion PI miter geometry

Two regimes:

- **Narrow types (everything except 7-8):** bisector miter at the PI, with a
  minimum length on the PI-adjacent loft spans (see
  [Bisector miter on narrow types](#bisector-miter-on-narrow-types-min-span--pullback)).
- **Wide types (7-8), deflection ≥ 15°:** virtual arc fan (below).

## Bisector miter on narrow types (corner piece: reach ≤ piece ≤ edge cap)

At a plan PI the cross-section uses the bisector direction
(`_section_at(pi, use_bisector=True)`), so both arms share one rotated face.
That face's points advance along the tangent by the **miter reach**:

```
reach    = pullback + lean
pullback = half_top_w · tan(φ / 2)            # plan rotation of the outermost point
lean     = d · |Δ(slope/mag)|                 # top-wall kink when a grade break sits on the PI
top_w    = bottom_w + 2·(m·d + t·√(1+m²))
```

(`lean` exists because `geometry.section_pts` builds sections perpendicular
to the 3D flow: points at height vz shift longitudinally by −(slope/mag)·vz,
so a slope change across the station kinks the top points — НК-3А-1
PI 250.307 = PVI with Δslope 0.445 → +0.29 m on the P4/P5 edges.)

Two failure modes bound the PI-adjacent piece length:

- **Too short** (< reach + `miter_margin`): the inner-side points of the
  bisector section land *behind* the neighbouring section, the loft profiles
  self-intersect, and AutoCAD silently produces a degenerate solid → visible
  gap (НК-3А-1, PI 133.562 @ 39.37°: span 0.513 m vs pullback 0.80 m).
  See `docs/platform/01_civil3d_errors.md` bug #27.
- **Too long** (piece·mag + reach > loft_step): the outer longitudinal 3D
  edge exceeds the 2 m standard basket (НК-1А-3, PI 276.104 @ 39.24° type 6:
  full 2 m step → 3.21 m edge).

Therefore each loft span `seg0 → seg1` is split by
`section_params.loft_substations(s0, s1, slope_at, reach_head, reach_tail)`:

- when a span boundary is a bisector plan PI, a **corner piece** of
  `corner_piece_len(reach, mag)` is reserved at that end:
  `max(reach + miter_margin, (loft_step − edge_safety − reach)/mag)`,
  with `mag` refined at the piece midpoint (the slope often changes right at
  the PI);
- the remaining span gets regular steps of `GABION.loft_step` along-slope;
- a trailing remainder `< GABION.min_unit` merges with previous full steps
  and the chunk splits into even dobornie pieces (`split_even`: most
  loft_step-like count whose pieces still clear the minimum —
  6.4 m → 2, 2, 1.2, 1.2).

When the corner window is **empty** (no length satisfies both bounds —
type 6 @ ≥ ~32°, type 5 @ ≥ ~45°), the PI is routed to the **virtual arc
fan** below: `_find_sharp_pis` triggers geometrically, not only by type.

The same helper drives both the actual lofts (`gabion_builder.build`) and the
JSON export sub-stations / dobornie callout marks (`export.py`) — they must
never diverge. `automation/tools/check_edge_lengths.py --pi-only` verifies
the ≤ 2 m rule offline from the exported `section_points`.

Related station-level rule: PVIs within `GABION.pi_merge_tol` (0.5 m) of a
plan PI are dropped in `canal_builder._build_stations` — the PI wins, keeping
the bisector miter (НК-1E-2: PVI 0.109 m from a PI lofted a 0.11 m sliver;
bug #28).

---

# Gabion sharp-PI handling on wide canals (virtual arc fan)

## Problem

On wide gabion canals (types 7-8) the alignment has sharp polyline PIs (no real
Civil 3D arc inscribed). The default bisector cut at PI produces:

- One bisector cross-section at PI shared by both arm lofts.
- In plan view the bisector face is wider than the arms — the inner-corner edges
  of the two arm solids overlap on the inner side of the turn.
- Visually 4–5 cuts converge to a single point on the inner edge → looks like
  the cuts "smear" / overlap (see `pictures/баг налезание.png`).

For narrow canals the same geometry produces a barely-visible artifact, so the
fix only kicks in for types 7-8.

## Idea

Replace the discrete bisector cut with a **virtual circular arc** centered on
the inner side of the turn. Cross-sections are sampled radially along the arc
→ each fan slice is a discrete prism whose end faces are perpendicular to its
own local tangent. In plan view the slices fan out from the arc center like
steps of a circular staircase, no overlap.

The trass (alignment) is **not modified** — only the gabion model uses the
virtual arc geometry. Profile / elevation / section_points export still use
the real alignment XY at PI.

## Trigger

A plan PI on a gabion (non-trough) segment activates the virtual arc when
**either** holds:

- Segment covering this PI has `type ∈ {7, 8}` (`WIDE_GABION_TYPES`) **and**
  deflection `|φ| ≥ SHARP_PI_DEG` (= 15°) — legacy visual-smear rule.
- The bisector corner-piece window is empty:
  `(loft_step − edge_safety − reach)/mag < reach + miter_margin` — no piece
  length both avoids self-intersection and keeps the longitudinal 3D edge
  ≤ loft_step (НК-1А-3: type 6 @ 39.24°).

Computed in `CanalBuilder._find_sharp_pis()`.

## Geometry

```
                    arc center
                       ●
                      /|\
                     / | \   R
                    /  |  \
                   /   |   \
                 PC----PI----PT   ← real alignment (polyline)
                 ←  L  ●  L  →
                       ↑
              real PI XY (tangent intersection)
```

- `R = top_width × SHARP_PI_ARC_RADIUS_FACTOR` (= top_w × 1.1)
  - `top_width = bottom_w + 2·(m·d + t·√(1+m²))` — outer-to-outer top width
- `L = R · tan(|φ| / 2)` — tangent length from PI to PC and from PI to PT
- `PC_station = pi_station − L`, `PT_station = pi_station + L`
- Arc center is on the **inner side** of the turn (left of incoming tangent for
  CCW turn, right for CW). Distance R perpendicular to incoming tangent at PC.

Implemented in `geometry.compute_virtual_arc()`.

## Sub-station sampling

Along `[PC, PT]` the arc is sliced into `N` equal fan pieces (N+1 cross-section
anchors). N is chosen so:

```
N = max(SHARP_PI_ARC_MIN_STEPS,                                # ≥ 4 always
        ceil(outer_R × |φ_rad| / LOFT_STEP),                   # outer edge ≤ 2m
        ceil(|φ_deg| / SHARP_PI_ARC_DEG_PER_STEP))             # ≤ 6° per slice
if N is odd: N += 1                                            # PI midpoint sampled
```

- `outer_R = R + top_width / 2` — radius of the outer (longest) edge of a slice.
  This is the binding constraint when R or φ is large (e.g. for type 8 at φ=24°
  the outer edge would be 2.57m at N=4 → bumped to N=6 → 1.71m).
- Forcing N even ensures one sub-station lands exactly at the PI midpoint, which
  keeps the legacy `use_bisector` code path inert for sharp PIs.

For each `i ∈ [0, N]`:
```
sub_sta = PC + (i / N) · (PT − PC)
x, y, ax, ay = arc_pt_dir(arc_info, sub_sta)
virtual_arc_overrides[round(sub_sta, 4)] = (x, y, ax, ay)
```

`virtual_arc_overrides` is then passed to `GabionBuilder`. In `_section_at()`
it takes precedence over `align.xy_at(sta)` / `align.angle_at(sta)`.

## arc_pt_dir math

At parameter `t ∈ [0, φ]` along the arc (signed):
```
ang(t) = ang_in + t
x(t)   = cx + R · sign(φ) · sin(ang(t))
y(t)   = cy − R · sign(φ) · cos(ang(t))
ax,ay  = cos(ang(t)), sin(ang(t))
```

Linear mapping from station to arc parameter:
```
t = φ · (sta − PC) / (PT − PC)
```

## Interaction with widening

When widening's `trans_start = sta_end − widening.length` lands inside any
sharp-PI arc zone `[PC, PT]`, it is pushed to `PT`:

```python
if PC − 0.05 ≤ trans_start ≤ PT + 0.05:
    widening["length"] = sta_end - PT
    trans_start = PT
```

The widening dict is **mutated** so all downstream consumers (`section_params_at`,
rib placement) see the shortened widening zone automatically.

This solves the НК-2D-1 case where `trans_start = 90.947` originally collided
with PI 90.953 — now it lands cleanly at PT (≈ 94.5) past the fan zone.

## Constants

In `config.py`:
| Name | Value | Meaning |
|---|---|---|
| `SHARP_PI_DEG` | 15.0 | min deflection (deg) for sharp-PI handling |
| `SHARP_PI_ARC_RADIUS_FACTOR` | 1.1 | R = top_width × this |
| `SHARP_PI_ARC_MIN_STEPS` | 4 | absolute minimum N |
| `SHARP_PI_ARC_DEG_PER_STEP` | 6.0 | one slice per this many degrees (angular cap) |
| `WIDE_GABION_TYPES` | {"7", "8"} | types eligible for sharp-PI virtual arc |

## Code map

| Where | What |
|---|---|
| `config.py` | constants |
| `geometry.compute_virtual_arc()` | builds arc_info dict (PC, PT, center, etc.) |
| `geometry.arc_pt_dir()` | (x, y, ax, ay) at arbitrary station on arc |
| `canal_builder._find_sharp_pis()` | filter PIs by deflection + wide segment |
| `canal_builder.run()` | builds arc_infos + virtual_arc_overrides per sharp PI |
| `canal_builder._build_stations()` | inserts N+1 fan-slice anchors; pushes widening past PT |
| `gabion_builder.GabionBuilder` | `virtual_arc_overrides` param |
| `gabion_builder._section_at()` | override takes precedence over alignment lookup |

## Effect on НК-2D-1 (the canonical case)

Type 8 (`bw=10, d=2, m=1, t=0.5`) → top_w ≈ 15.41m → R ≈ 16.96m → outer_R ≈ 24.66m

| PI | φ° | L (m) | N | outer_step (m) |
|---|---|---|---|---|
| 68.418 | 26.83 | 4.04 | 6 | 1.93 |
| 90.953 | 23.86 | 3.58 | 6 | 1.71 |

Widening: original `trans_start = 90.947` inside PI 90.953's arc [87.37, 94.54]
→ pushed to PT = 94.54, `widening.length` 16.4 → 12.81m.

PIs 20.541 and 43.288 are below 15° (3.6° and 5.4°) — not affected.

## Why not just scale the bisector by 1/cos(φ/2)?

That fix (`trough_corners.md` approach) eliminates the geometric overlap at the
join face but still leaves one solid spanning the whole corner — the inner
edge of that solid still converges to a single point in plan. Visually it's
two big sheared pieces meeting at the bisector, not a "circular staircase".

The virtual arc gives N discrete slices, each with its own footprint, which
matches the user's expectation of how gabion blocks should look on a turn.

---

## See also
- [section_points.md](section_points.md) — cross-section point layout
- [trough_corners.md](trough_corners.md) — analogous PI handling for troughs
- [../../../../docs/platform/01_civil3d_errors.md](../../../../docs/platform/01_civil3d_errors.md) — bug #24: wide canal overlap (virtual arc fix)