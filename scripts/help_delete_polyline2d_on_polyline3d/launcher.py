import clr, os, sys

clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

try:
    _REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
    while (
        not os.path.isdir(os.path.join(_REPO_ROOT, "common"))
        and os.path.dirname(_REPO_ROOT) != _REPO_ROOT
    ):
        _REPO_ROOT = os.path.dirname(_REPO_ROOT)
except NameError:
    # Inside the Dynamo .dyn node __file__ is undefined -> ONE shared project anchor;
    # every root below is derived relative to it, identical for every nk_toolkit script.
    _REPO_ROOT = os.environ.get("NK_TOOLKIT_ROOT", r"C:\nk_toolkit")

_ROOT = os.path.join(_REPO_ROOT, "scripts")
_COMMON = os.path.join(_REPO_ROOT, "common")
for _p in (_ROOT, _COMMON):
    if _p in sys.path:
        sys.path.remove(_p)
    sys.path.insert(0, _p)
# both toolkits have a top-level paths.py: never reuse the copy cached by the OTHER toolkit's
# scripts earlier in this Dynamo session (own dirs are moved to the front just above)
sys.modules.pop("paths", None)
for _name in sorted(
    [m for m in sys.modules if m.startswith("help_delete_polyline2d_on_polyline3d")],
    reverse=True,
):
    del sys.modules[_name]
from help_delete_polyline2d_on_polyline3d.builder import DeleteFlatPolylineBuilder


# Layer whitelists default to layers_config.json (UTF-8 sidecar) so Cyrillic
# layer names stay out of the .dyn. Wiring IN[2]/IN[3] (comma-separated
# strings) overrides the config; leaving them unset => use the config.
def _split(s):
    return [p for p in (s or "").split(",") if p.strip()]


_tol = float(IN[0]) if IN and len(IN) > 0 and IN[0] else 0.001
_min_ov = float(IN[1]) if IN and len(IN) > 1 and IN[1] else 0.1
_layers_2d = _split(IN[2]) if IN and len(IN) > 2 and IN[2] else None
_layers_3d = _split(IN[3]) if IN and len(IN) > 3 and IN[3] else None

OUT = DeleteFlatPolylineBuilder(_tol, _min_ov, _layers_2d, _layers_3d).run()
