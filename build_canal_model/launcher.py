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
# DELETE (not reload) so the next import re-reads every submodule fresh from
# disk -- deleting needs no leaf-first/orchestrator-last ordering the way
# importlib.reload() used to (a fresh `import` naturally resolves dependency
# order on its own), so the old custom _reload_key sort is gone too.
for _name in [
    m
    for m in list(sys.modules)
    if m.startswith("build_canal_model") or m.startswith("civil") or m == "paths"
]:
    del sys.modules[_name]
from build_canal_model.canal_builder import CanalBuilder

OUT = CanalBuilder(IN[0]).run()
