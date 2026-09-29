import clr, os, sys

clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

try:
    _ROOT = os.path.dirname(os.path.abspath(__file__))
    while (
        not os.path.isdir(os.path.join(_ROOT, "common"))
        and os.path.dirname(_ROOT) != _ROOT
    ):
        _ROOT = os.path.dirname(_ROOT)
except NameError:
    # Inside the Dynamo .dyn node __file__ is undefined -> ONE shared project anchor;
    # every root below is derived relative to it, identical for every nk_toolkit script.
    _ROOT = os.environ.get("NK_TOOLKIT_ROOT", r"C:\nk_toolkit")

_COMMON = os.path.join(_ROOT, "common")
for _p in (_ROOT, _COMMON):
    if _p not in sys.path:
        sys.path.insert(0, _p)
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
