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
    if _p in sys.path:
        sys.path.remove(_p)
    sys.path.insert(0, _p)
# both toolkits have a top-level paths.py: never reuse the copy cached by the OTHER toolkit's
# scripts earlier in this Dynamo session (own dirs are moved to the front just above)
sys.modules.pop("paths", None)
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
