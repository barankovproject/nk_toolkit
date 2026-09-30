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
    if _p not in sys.path:
        sys.path.insert(0, _p)
for _name in sorted(
    [m for m in sys.modules if m.startswith("help_clear_inf")], reverse=True
):
    del sys.modules[_name]
from help_clear_inf.builder import ClearInfBuilder

OUT = ClearInfBuilder(IN[0] if IN and IN[0] else "inf").run()
