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
_ANCHOR = os.path.join(_ROOT, "anchor")
for _p in (_ANCHOR, _ROOT, _COMMON):
    if _p not in sys.path:
        sys.path.insert(0, _p)
# Drop this package so the next import reloads every submodule fresh in
# dependency order (see ditch_04_build_cross/launcher.py for the rationale).
for _name in [m for m in list(sys.modules) if m.startswith("anchor_")]:
    del sys.modules[_name]
for _name in sorted(
    [m for m in sys.modules if m.startswith("civil")],
    reverse=True,
):
    del sys.modules[_name]
from anchor_04_place_anchors.builder import AnchorPointsBuilder

# Read the coloured horizontals + perpendiculars, place anchor circles at
# same-colour crossings. Returns the log file path.
OUT = AnchorPointsBuilder().run()
