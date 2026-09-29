# Canal cross-section points

`section_pts()` returns a list of 9 Point3d in this order:

| idx | name | where |
|-----|------|-------|
| 0   | P0   | top-left inner — top of left wall, inner edge |
| 1   | P1   | bottom-left inner — bottom of left slope, inner corner |
| 2   | Pc   | bottom center — canal axis / trass point (XY = alignment exactly) |
| 3   | P2   | bottom-right inner — bottom of right slope, inner corner |
| 4   | P3   | top-right inner — top of right wall, inner edge |
| 5   | P4   | top-right outer — top of right wall, outer edge (P3 offset by t) |
| 6   | P5   | bottom-right outer — outer corner of right wall base |
| 7   | P6   | bottom-left outer — outer corner of left wall base |
| 8   | P7   | top-left outer — top of left wall, outer edge (P0 offset by t) |

ASCII cross-section (Z up, X across):

```
z=+d   P7--P0              P3--P4
        \   \              /   /
         \   \            /   /
z=0       \  P1----Pc----P2  /
            \               /
z=-t        P6-------------P5
```

- `d` = vertical canal depth (direct input) — P0/P3 sit at z=+d above P1/Pc/P2
- `m` = slope coefficient (horizontal : vertical), so horizontal run a = m·d
- `t` = wall thickness (perpendicular to slope face)
- z=0 is at the P1–Pc–P2 level (canal bottom / trass elevation)
- Slant length sl = sqrt(d² + (m·d)²) = d·sqrt(1+m²) — used only for unit normals
X- Inner U-shape: P0->P1->Pc->P2->P3
- Top wall faces: P7-P0 (left), P3-P4 (right)
- Outer shell: P4->P5->P6->P7

```
x = cx + rx·lat  −  slope·ax·vz
y = cy + ry·lat  −  slope·ay·vz
z = cz + vz
```
The `−slope·ax·vz` / `−slope·ay·vz` correction tilts the plane so its normal equals
the 3D tangent. At zero slope the formula reduces to the old vertical-plane formula.

This applies to **both** gabion canals (`section_pts`) and troughs (`trough_section_pts`).
Visual check: in the longitudinal section the element boundary appears perpendicular
to the sloped alignment, not vertical.

## project_xy.dyn

Projected edges (ver 0.5): indices `[8, 0, 1, 3, 4, 5]` = P7-P0-P1-P2-P3-P4

Not shown: Pc (idx 2), P5 (idx 6), P6 (idx 7)

Circles diameter 1 drawn at P1 (idx 1) and P2 (idx 3) at every station.

---

## See also
- [gabion_corners.md](gabion_corners.md) — PI miter geometry using these cross-section points
- [config_format.md](config_format.md) — type params (bottom_w, d, m, t) that position the points
- [layers.md](layers.md) — which layer each gabion solid lands on