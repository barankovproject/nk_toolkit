# Documentation Maintenance

## Rules

- Algorithm or input format changed → update the relevant MD in the same commit
- Found and fixed a non-obvious bug → add it to `docs/platform/01_civil3d_errors.md`
- A script's own input/output/config location changed → update its own `README.md`
  in the same commit (see [02_development.md → Script README](02_development.md#script-readme))

## What goes where

| What changed | Where to document |
|---|---|
| Cross-section geometry rule | `projects/arhyz_s2/references/section_points.md` or `gabion_corners.md` |
| Canal config field added/changed | `projects/arhyz_s2/references/config_format.md` |
| Civil 3D bug found and fixed | `docs/platform/01_civil3d_errors.md` |
| Layer name added or changed | `projects/arhyz_s2/references/layers.md` |
| Trough type added | `projects/arhyz_s2/references/trough_types.md` |
| A script's own input/output, or where it reads extra config from | that script's own `README.md` |

## What does NOT need a doc update

- Refactors that don't change behavior
- Bug fixes where the correct behavior was already documented
- Internal variable renames
