import clr, os, sys

clr.AddReference("AecBaseMgd")
clr.AddReference("AeccDbMgd")
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
    if _p not in sys.path:
        sys.path.insert(0, _p)

for _name in [
    m
    for m in list(sys.modules)
    if m.startswith("build_gsi_grid") or m.startswith("civil")
]:
    del sys.modules[_name]

from build_gsi_grid.builder import GsiGridBuilder

# Step 1 of the new GSI layout: pick OUTER / MIDDLE / INNER polylines, then draw the
# construction grid at each acute (<90 deg) corner -- a blue diagonal (outer vertex ->
# inner vertex) and magenta perpendiculars (dropped from a vertex onto an edge, kept only
# where the foot lands on the actual edge segment). No IN[] needed.
OUT = GsiGridBuilder().run()
