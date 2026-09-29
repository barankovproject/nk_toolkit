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
for _p in (_ROOT, _COMMON):
    if _p not in sys.path:
        sys.path.insert(0, _p)
# Purge cached package modules instead of importlib.reload: reload() re-imports a
# module's dependencies from sys.modules in whatever order the reload loop runs, so
# builder could bind a stale BlockManager before blocks reloaded. Deleting the
# entries forces the import below to rebuild the whole tree in dependency order.
for _name in [
    m
    for m in list(sys.modules)
    if m == "draw_gabion_view"
    or m.startswith("draw_gabion_view.")
    or m == "civil"
    or m.startswith("civil.")
    or m == "paths"
]:
    del sys.modules[_name]

from draw_gabion_view.builder import GabionViewBuilder

OUT = GabionViewBuilder(IN[0]).run()
