import clr, os, sys

clr.AddReference("AecBaseMgd")
clr.AddReference("AeccDbMgd")
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
_DITCH = os.path.join(_ROOT, "ditch")
for _p in (_DITCH, _ROOT, _COMMON):
    if _p not in sys.path:
        sys.path.insert(0, _p)
# Drop both this package and ditch_core (the imported geometry) from
# sys.modules so the next import reloads every submodule fresh in dependency
# order. importlib.reload() in name order rebinds `from .x import y` against stale
# modules when a dependant reloads before its dependency — deleting avoids that.
for _name in [
    m
    for m in list(sys.modules)
    if m.startswith("ditch_04_build_cross") or m.startswith("ditch_core")
]:
    del sys.modules[_name]
for _name in sorted(
    [m for m in sys.modules if m.startswith("civil")],
    reverse=True,
):
    del sys.modules[_name]
from ditch_04_build_cross.builder import MarkedDitchBuilder

# Main script: project every marker circle (inf_md_marker) onto the alignment and
# build a cross-ditch at each. No selection / IN[0] needed.
OUT = MarkedDitchBuilder().run()
