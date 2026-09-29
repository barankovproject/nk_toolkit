# Widening assemblies (cross-section variants needed)

Each canal with widening ends in a flat zone whose cross-section has:
- bw = widening.b
- d, m, t = same as the LAST gabion segment in the canal

To build these zones into a Civil 3D Corridor we need an Assembly per unique (d, m, t, b) combo.

## Unique combos (base-type / target b -> assembly)

| Base type | d (m) | m | t (m) | b (m) | Assembly name | # canals |
|---|---|---|---|---|---|---|
| 1 | 0.50 | 1.0 | 0.17 | 2.0 | 2000x500_170 | 11 |
| 1 | 0.50 | 1.0 | 0.17 | 5.0 | 5000x500_170 | 1 |
| 2 | 0.60 | 1.0 | 0.17 | 3.0 | 3000x600_170 | 3 |
| 2 | 0.60 | 1.0 | 0.17 | 5.0 | 5000x600_170 | 1 |
| 3 | 0.75 | 1.0 | 0.30 | 3.0 | 3000x750_300 | 5 |
| 3 | 0.75 | 1.0 | 0.30 | 10.0 | 10000x750_300 | 1 |
| 4 | 0.75 | 1.0 | 0.17 | 3.0 | 3000x750_170 | 2 |
| 4 | 0.75 | 1.0 | 0.17 | 5.0 | 5000x750_170 | 5 |
| 5 | 0.75 | 1.0 | 0.50 | 5.0 | 5000x750_500 | 5 |
| 5 | 0.75 | 1.0 | 0.50 | 6.0 | 6000x750_500 | 1 |
| 5 | 0.75 | 1.0 | 0.50 | 10.0 | 10000x750_500 | 1 |
| 6 | 0.75 | 1.0 | 0.50 | 10.0 | 10000x750_500 | 3 |
| 7 | 1.50 | 1.0 | 0.50 | 15.0 | 15000x1500_500 | 2 |
| 8 | 2.00 | 1.0 | 0.50 | 25.0 | 25000x2000_500 | 2 |

## Unique assembly count

Total unique Assembly objects needed: **13**

| Assembly | Used by (type / b) | # canals |
|---|---|---|
| 2000x500_170 | 1/b=2.0 | 11 |
| 3000x600_170 | 2/b=3.0 | 3 |
| 3000x750_170 | 4/b=3.0 | 2 |
| 3000x750_300 | 3/b=3.0 | 5 |
| 5000x500_170 | 1/b=5.0 | 1 |
| 5000x600_170 | 2/b=5.0 | 1 |
| 5000x750_170 | 4/b=5.0 | 5 |
| 5000x750_500 | 5/b=5.0 | 5 |
| 6000x750_500 | 5/b=6.0 | 1 |
| 10000x750_300 | 3/b=10.0 | 1 |
| 10000x750_500 | 5/b=10.0, 6/b=10.0 | 4 |
| 15000x1500_500 | 7/b=15.0 | 2 |
| 25000x2000_500 | 8/b=25.0 | 2 |

## Detail: canals per combo

### type 1, b=2.0m -> 2000x500_170 (11 canals)

| Canal | widening.length |
|---|---|
| НК-1D-1 | 8.0 |
| НК-1В-1 | 9.0 |
| НК-1В-2 | 8.0 |
| НК-1В-4 | 6.0 |
| НК-1Е-3 | 10.0 |
| НК-2G-2 | 10.0 |
| НК-2H-1 | 10.0 |
| НК-2В-2 | 5.0 |
| НК-2Е-1 | 6.8 |
| НК-3А-2 | 10.0 |
| НК-3В-1 | 10.0 |

### type 1, b=5.0m -> 5000x500_170 (1 canals)

| Canal | widening.length |
|---|---|
| НК-1F-3 | 10.0 |

### type 2, b=3.0m -> 3000x600_170 (3 canals)

| Canal | widening.length |
|---|---|
| НК-1А-11 | 9.4 |
| НК-1С-7 | 10.0 |
| НК-2D-3 | 10.0 |

### type 2, b=5.0m -> 5000x600_170 (1 canals)

| Canal | widening.length |
|---|---|
| НК-1А-14 | 11.84 |

### type 3, b=3.0m -> 3000x750_300 (5 canals)

| Canal | widening.length |
|---|---|
| НК-1F-2 | 10.0 |
| НК-1А-2 | 10.0 |
| НК-1С-6 | 10.0 |
| НК-2F-1 | 10.0 |
| НК-2В-1 | 10.0 |

### type 3, b=10.0m -> 10000x750_300 (1 canals)

| Canal | widening.length |
|---|---|
| НК-1С-2 | 10.0 |

### type 4, b=3.0m -> 3000x750_170 (2 canals)

| Canal | widening.length |
|---|---|
| НК-1А-10 | 10.0 |
| НК-3D-1 | 7.95 |

### type 4, b=5.0m -> 5000x750_170 (5 canals)

| Canal | widening.length |
|---|---|
| НК-1F-1 | 10.0 |
| НК-1А-13 | 13.72 |
| НК-1В-3 | 10.0 |
| НК-2В-3 | 10.0 |
| НК-3D-2 | 10.0 |

### type 5, b=5.0m -> 5000x750_500 (5 canals)

| Canal | widening.length |
|---|---|
| НК-1А-5 | 10.0 |
| НК-1А-7 | 10.0 |
| НК-1Е-1 | 10.0 |
| НК-1Е-2 | 10.0 |
| НК-2А-1 | 10.0 |

### type 5, b=6.0m -> 6000x750_500 (1 canals)

| Canal | widening.length |
|---|---|
| НК-1А-1 | 10.0 |

### type 5, b=10.0m -> 10000x750_500 (1 canals)

| Canal | widening.length |
|---|---|
| НК-1А-8 | 10.0 |

### type 6, b=10.0m -> 10000x750_500 (3 canals)

| Canal | widening.length |
|---|---|
| НК-1А-3 | 10.0 |
| НК-1А-6 | 10.0 |
| НК-1С-3 | 20.0 |

### type 7, b=15.0m -> 15000x1500_500 (2 canals)

| Canal | widening.length |
|---|---|
| НК-2G-1 | 10.0 |
| НК-3С-3 | 10.0 |

### type 8, b=25.0m -> 25000x2000_500 (2 canals)

| Canal | widening.length |
|---|---|
| НК-2D-1 | 16.4 |
| НК-2H-2 | 14.51 |

## Existing base-type assemblies (already in drawing)

| Assembly | Canal type |
|---|---|
| 500x500_170 | 1 |
| 600x600_170 | 2 |
| 750x750_300 | 3 |
| 1500x750_170 | 4 |
| 1500x750_500 | 5 |
| 4000x750_500 | 6 |
| 7000x1500_500 | 7 |
| 10000x2000_500 | 8 |

## Notes

- Naming follows existing assemblies: <bw_mm>x<d_mm>_<t_mm>.
- 10000x750_500 is shared by type 5 (b=10) and type 6 (b=10) -- identical cross-section, single Assembly suffices.
- No combo collides with the 8 existing base-type assemblies.
- m (slope) is 1.0 for every type -- not encoded in the name; assumed default.
- Each widening zone is preceded by a 2 m linear transition from the base type bw to b.
  The transition itself is not a separate Assembly -- handled by the existing builder logic.
---

## See also
- [config_format.md](config_format.md) — widening field in canal config (b, length)
- [../../../../docs/platform/04_corridor_workflow.md](../../../../docs/platform/04_corridor_workflow.md) — corridor build workflow that uses these assemblies