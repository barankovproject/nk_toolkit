import clr, importlib, os, sys

clr.AddReference("AecBaseMgd")
clr.AddReference("AeccDbMgd")
clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

try:
    _LIB_ROOT = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
except NameError:
    _LIB_ROOT = os.environ.get("ARHYZ_LIB_ROOT", r"C:\Arhyz\automation\scripts\ditch")

_AUTOMATION_ROOT = os.path.dirname(_LIB_ROOT)

if _LIB_ROOT not in sys.path:
    sys.path.insert(0, _LIB_ROOT)
if _AUTOMATION_ROOT not in sys.path:
    sys.path.insert(0, _AUTOMATION_ROOT)

# Drop the whole package so the next import reloads every submodule fresh in
# dependency order (see launcher.py for the why).
for _name in [m for m in list(sys.modules) if m.startswith("ditch_core")]:
    del sys.modules[_name]
for _name in sorted(
    [m for m in sys.modules if m.startswith("civil")],
    reverse=True,
):
    try:
        importlib.reload(sys.modules[_name])
    except Exception:
        pass

from ditch_core.builder import CrossDitchBuilder

# Flip script: IN[0] is the ditch picked by a Dynamo ObjectSelection node.
# Toggles that ditch's manual-flip state (persisted to file) and rebuilds, so it
# flips on the spot. A missing/unconnected port → plain rebuild.
try:
    _picked = IN[0]
except (NameError, IndexError, TypeError):
    _picked = None

OUT = CrossDitchBuilder(_picked).run()
