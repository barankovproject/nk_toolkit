# Testing

## Rules

- Acceptance on one canal is not acceptance — test on at least two different canals
- When a bug appears on a new canal, add it to this file before fixing it
- Check the log after every run — a silent run is not a passing run

## How to run

```
cd C:\Arhyz
pytest tests/
```

## Test organisation

### Folder structure mirrors scripts/

Each script package gets its own subfolder under `tests/`, named identically to the package:

```
automation/scripts/build_canal_model/   ←→   tests/build_canal_model/
automation/scripts/report_canal/        ←→   tests/report_canal/
automation/scripts/draw_gabion_view/    ←→   tests/draw_gabion_view/
```

Test files inside the subfolder follow the standard `test_<module>.py` convention.
`conftest.py` and `helpers.py` stay at the `tests/` root — pytest loads them for all subfolders automatically.

### One class per function under test

Group tests by the function they cover. Each class tests exactly one function.

```python
class TestComputeVirtualArc:
    """compute_virtual_arc derives key arc parameters from alignment tangent angles."""

    def test_deflection_angle(self, right_turn_90) -> None: ...
    def test_tangent_length(self, right_turn_90) -> None: ...
    def test_pc_pt_stations(self, right_turn_90) -> None: ...
```

### Tests contain only assertions

No logic in test methods. Computation and setup go in fixtures or helper methods.
Test bodies are: call the function, assert the result.

```python
def test_tangent_is_unit_vector(self, right_turn_90) -> None:
    for sta in (9.0, 9.5, 10.0, 10.5, 11.0):
        _, _, ax, ay = arc_pt_dir(right_turn_90, sta)
        assert math.hypot(ax, ay) == pytest.approx(1.0, abs=1e-6), f"sta={sta}"
```

### Fixtures for shared setup, module constants for shared data

Use `@pytest.fixture` when setup is expensive or reused across multiple test classes.
Use module-level constants for input dicts that many tests share.

```python
_SECTION_BASE = dict(cx=0.0, cy=0.0, cz=0.0, rx=1.0, ...)  # shared input

@pytest.fixture
def right_turn_90():
    align = MockAlignment(ang_in=0.0, ang_out=-math.pi / 2, pi_sta=10.0)
    return compute_virtual_arc(pi_sta=10.0, R=1.0, align_w=align, eps=0.3)
```

### Private helper on the class to reduce repetition

When tests call the same function with slight variations, put the call in `_method()`.

```python
class TestGabionSection:
    def _pts(self, **override):
        return section_pts(**{**_SECTION_BASE, **override})

    def test_lateral_symmetry(self) -> None:
        pts = self._pts()  # defaults
        ...

    def test_slope_tilts_top_wall(self) -> None:
        flat = self._pts(slope=0.0)
        sloped = self._pts(slope=1.0)
        ...
```

### All float comparisons via pytest.approx

```python
assert right_turn_90["L"] == pytest.approx(1.0)
assert math.hypot(cx - pc[0], cy - pc[1]) == pytest.approx(1.0, abs=1e-6)
```

### Docstrings explain geometry invariants, not code

Class docstring: what the function does + what this test class covers.
Method docstring: only when the invariant being checked isn't obvious from the code.

## Stubs (conftest.py)

Civil 3D runs inside Dynamo/IronPython. Tests run in plain CPython.
`conftest.py` stubs out the host APIs so `canal_model` can import cleanly:

- `clr` module — stubbed (`AddReference` is a no-op)
- `Autodesk.AutoCAD.Geometry` — `Point3d`, `Vector3d`, `Plane` as plain Python classes
- `sys.path` — `automation/scripts/` and `tests/` added so imports work

Never mock real business logic — only stub the Civil 3D / Dynamo host boundary.

## Mock objects (helpers.py)

Duck-type stubs for Civil 3D wrapper classes go in `tests/helpers.py`.
Implement only the interface the tested function actually calls.

```python
class MockAlignment:
    """Minimal duck-type for AlignmentWrapper."""
    def __init__(self, ang_in, ang_out, pi_sta): ...
    def angle_at(self, sta): ...
    def xy_at(self, sta): ...
```

## Known problem canals

Document canals that revealed bugs here so they stay in the test rotation. Split by
script family (2026-09-04, one table had grown to 35 KB mixing every family) — pick the
file matching the script you're testing:

| File | Covers |
|---|---|
| [`testing/nk.md`](testing/nk.md) | `build_canal_model`, `draw_gabion_view` (НК canals) |
| [`testing/ditch.md`](testing/ditch.md) | `ditch_03_build_long`, `ditch_04_build_cross` |
| [`testing/tube.md`](testing/tube.md) | Everything under `automation/scripts/tube/` — GSI apron/walls/ribs, excavation callouts, well, КВ (В-* canals) |

## When to add a canal here

- Run on a new canal, something breaks
- Add canal name + symptom to the matching family file above, BEFORE fixing
- After fix: add the commit reference
- New script family with no matching file yet → create `testing/<family>.md` following the
  existing files' format (one "Known problem canals" table + a "When to add a canal here" section)

## Log inspection

Latest log for any script:
```
/latest-log <script_name>
```
