import clr, importlib, os, sys

clr.AddReference("AecBaseMgd")
clr.AddReference("AeccDbMgd")
clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

try:
    _LIB_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
except NameError:
    _LIB_ROOT = os.environ.get("ARHYZ_LIB_ROOT", r"C:\Arhyz\automation\scripts")

_AUTOMATION_ROOT = os.path.dirname(_LIB_ROOT)

if _LIB_ROOT not in sys.path:
    sys.path.insert(0, _LIB_ROOT)
if _AUTOMATION_ROOT not in sys.path:
    sys.path.insert(0, _AUTOMATION_ROOT)


def _reload_key(n):
    parts = n.split(".")
    if len(parts) == 1:
        return (2, n)  # bare package (build_canal_model, civil) — last
    if parts[-1] == "canal_builder":
        return (1, n)  # top-level orchestrator — after all submodules
    return (0, n)  # all other submodules — alphabetical (acad_helpers first)


for _name in sorted(
    [
        m
        for m in sys.modules
        if m.startswith("build_canal_model") or m.startswith("civil")
    ],
    key=_reload_key,
):
    try:
        importlib.reload(sys.modules[_name])
    except Exception:
        del sys.modules[_name]

from build_canal_model.all_builder import AllCanalBuilder

OUT = AllCanalBuilder().run()
