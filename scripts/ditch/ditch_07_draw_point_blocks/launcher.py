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
_DITCH = os.path.join(_ROOT, "ditch")
for _p in (_DITCH, _ROOT, _COMMON):
    if _p in sys.path:
        sys.path.remove(_p)
    sys.path.insert(0, _p)
# both toolkits have a top-level paths.py: never reuse the copy cached by the OTHER toolkit's
# scripts earlier in this Dynamo session (own dirs are moved to the front just above)
sys.modules.pop("paths", None)
# Drop this package + ditch_core so the next import reloads every submodule fresh
# in dependency order (see ditch_04_build_cross/launcher.py for why).
for _name in [
    m
    for m in list(sys.modules)
    if m.startswith("ditch_07_draw_point_blocks") or m.startswith("ditch_core")
]:
    del sys.modules[_name]
for _name in sorted(
    [m for m in sys.modules if m.startswith("civil")],
    reverse=True,
):
    del sys.modules[_name]
from ditch_07_draw_point_blocks.builder import PointBlockBuilder

# Main script: place the "Номер_точки_канавы" block at every characteristic point of
# the cross + longitudinal ditches. No selection / IN[0] needed.
OUT = PointBlockBuilder().run()
