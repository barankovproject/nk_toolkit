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
# Drop the whole package from sys.modules so the next import reloads every
# submodule fresh in dependency order. importlib.reload() in name order rebinds
# `from .x import y` against stale modules when a dependant reloads before its
# dependency (e.g. ditch_solver before cross_profile) — deleting avoids that.
for _name in [m for m in list(sys.modules) if m.startswith("ditch_core")]:
    del sys.modules[_name]
for _name in sorted(
    [m for m in sys.modules if m.startswith("civil")],
    reverse=True,
):
    del sys.modules[_name]
from ditch_core.builder import CrossDitchBuilder

# Main script: build every ditch and apply any saved manual flips from file.
# Manual flipping (ObjectSelection → toggle) lives in launcher_flip.py / its own
# .dyn, so this graph never depends on a selection.
OUT = CrossDitchBuilder().run()
