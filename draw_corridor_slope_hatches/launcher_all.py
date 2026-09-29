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

for _name in sorted(
    [
        m
        for m in sys.modules
        if m.startswith("draw_corridor_slope_hatches") or m.startswith("civil")
    ],
    reverse=True,
):
    try:
        importlib.reload(sys.modules[_name])
    except Exception:
        del sys.modules[_name]

from draw_corridor_slope_hatches.builder import SlopeHatchBuilder

OUT = SlopeHatchBuilder().run()
