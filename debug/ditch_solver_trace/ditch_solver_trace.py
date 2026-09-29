"""Trace ditch_core.solve_ditch's skew search at specific out-of-band stations.

Replicates the candidate search from ditch_solver.solve_ditch but logs, for every
theta in BOTH rotation directions: whether each break-point was found and its
status (break/edge/cap), za/zb, length2d, cut_side, z_cut/z_fill, slope, whether
it drains correctly (z_cut > z_fill) and whether the along-axis projection stays
within step/2. The goal is to see WHY no theta lands slope in [slope_min, slope_max]
— i.e. why the gentle along-contour orientation is not a kept candidate.
"""

from __future__ import annotations

import clr
import datetime
import math
import os
import sys
import traceback

clr.AddReference("AecBaseMgd")
clr.AddReference("AeccDbMgd")
clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import OpenMode  # noqa: F401

_SCRIPTS_ROOT = r"C:\Arhyz\automation\scripts\ditch"
if _SCRIPTS_ROOT not in sys.path:
    sys.path.insert(0, _SCRIPTS_ROOT)
_AUTOMATION = r"C:\Arhyz\automation"
if _AUTOMATION not in sys.path:
    sys.path.insert(0, _AUTOMATION)

# The Dynamo CPython engine persists sys.modules across runs, so an edited
# ditch_core module would otherwise be served stale from cache. Drop them first.
for _m in list(sys.modules):
    if _m.startswith("ditch_core") or _m.startswith("civil"):
        del sys.modules[_m]

from ditch_core.config import CONFIG
from ditch_core.cross_profile import break_point
from ditch_core.geometry import classify_start_side, pick_theta, rotate
from ditch_core.selection import find_alignment_and_surface
from civil.alignment import AlignmentWrapper

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\ditch_solver_trace\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"ditch_solver_trace_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)

# Stations to trace (m). 624.19 = 1e #3 (was 0.092 out_of_band). 107.2 / 206.41 =
# 1e #8 / #9 (were already in band: 0.0216 / 0.0269) — controls that must NOT change.
STATIONS = [624.19, 107.2, 206.41]


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def _safe_elev(surface, x, y):
    try:
        return float(surface.FindElevationAtXY(x, y))
    except Exception:
        return None


def trace_station(surface, align_w, sta, cfg) -> None:
    log("")
    log("=" * 78)
    log(f"STATION {sta:.3f}")
    log("=" * 78)

    cx, cy = align_w.xy_at(sta)
    ang_ax = align_w.angle_at(sta)
    ax, ay = math.cos(ang_ax), math.sin(ang_ax)
    nx, ny = align_w.cross_axis_at(sta)

    z_ax = _safe_elev(surface, cx, cy)
    log(
        f"axis (x,y)=({cx:.2f},{cy:.2f}) z={z_ax}  ang_ax={math.degrees(ang_ax):.1f}deg"
    )
    if z_ax is None:
        log("axis off surface -> solver returns None")
        return

    gp = cfg.grade_probe
    e_fwd = _safe_elev(surface, *align_w.xy_at(sta + gp))
    e_back = _safe_elev(surface, *align_w.xy_at(sta - gp))
    descend_along = 1.0
    if e_fwd is not None and e_back is not None:
        descend_along = 1.0 if e_fwd < e_back else -1.0
    log(
        f"grade probe +-{gp}m: e_fwd={e_fwd} e_back={e_back} descend_along={descend_along}"
    )

    s_step = cfg.sample_step
    reach = cfg.max_reach
    thr = cfg.slope_break
    half_step = cfg.step / 2.0
    steep = cfg.scarp_min_slope
    up_n, down_n = (nx, ny), (-nx, -ny)

    pa0, sa0, sl_a0 = break_point(surface, cx, cy, nx, ny, s_step, reach, thr, steep)
    pb0, sb0, sl_b0 = break_point(surface, cx, cy, -nx, -ny, s_step, reach, thr, steep)
    za0 = _safe_elev(surface, pa0[0], pa0[1]) if pa0 is not None else 0.0
    zb0 = _safe_elev(surface, pb0[0], pb0[1]) if pb0 is not None else 0.0
    cut_side = classify_start_side(sl_a0, za0 or 0.0, sl_b0, zb0 or 0.0)
    log(
        f"theta=0: side A {sa0} sl={sl_a0} za={za0:.2f} | "
        f"side B {sb0} sl={sl_b0} zb={zb0:.2f} -> cut_side={cut_side}"
    )

    cut_dir = up_n if cut_side == "a" else down_n
    perp_cut = (-cut_dir[1], cut_dir[0])
    pc_dot = perp_cut[0] * ax + perp_cut[1] * ay
    sgn = -descend_along if pc_dot > 0 else descend_along
    log(f"pc_dot={pc_dot:.3f} sgn={sgn:+.0f}  (band [{cfg.slope_min},{cfg.slope_max}])")
    log(
        f"cfg: step={cfg.step} half_step={half_step} max_reach={reach} "
        f"theta_max={cfg.theta_max_deg} theta_step={cfg.theta_step_deg} "
        f"slope_break={thr} forbid_overlap={cfg.forbid_neighbour_overlap}"
    )

    def search(sign: float):
        log("")
        log(f"--- search sign={sign:+.0f} ---")
        header = (
            "  th   Astat Bstat   za      zb     len   cut  z_cut  z_fill "
            " slope  drain ovlp  -> kept"
        )
        log(header)
        cands = []
        data = {}
        t = 0.0
        while t <= cfg.theta_max_deg + 1e-9:
            ang = sign * math.radians(t)
            ur = rotate(up_n[0], up_n[1], ang)
            dr = rotate(down_n[0], down_n[1], ang)
            pa_, sa_, sl_a_ = break_point(
                surface, cx, cy, ur[0], ur[1], s_step, reach, thr, steep
            )
            pb_, sb_, sl_b_ = break_point(
                surface, cx, cy, dr[0], dr[1], s_step, reach, thr, steep
            )
            row = f"  {t:4.0f}  "
            if pa_ is None or pb_ is None:
                log(row + f"{str(sa_):5s} {str(sb_):5s}  (a or b None) -> skip")
                t += cfg.theta_step_deg
                continue
            proj_a = (pa_[0] - cx) * ax + (pa_[1] - cy) * ay
            proj_b = (pb_[0] - cx) * ax + (pb_[1] - cy) * ay
            ovlp = max(abs(proj_a), abs(proj_b)) > half_step
            za_ = _safe_elev(surface, pa_[0], pa_[1])
            zb_ = _safe_elev(surface, pb_[0], pb_[1])
            if za_ is None or zb_ is None:
                log(row + f"{sa_:5s} {sb_:5s}  (za/zb None) -> skip")
                t += cfg.theta_step_deg
                continue
            length = math.hypot(pb_[0] - pa_[0], pb_[1] - pa_[1])
            z_cut = za_ if cut_side == "a" else zb_
            z_fill = zb_ if cut_side == "a" else za_
            drain = z_cut > z_fill
            slope = (z_cut - z_fill) / length if length > 1e-6 else float("nan")
            ovlp_blocks = ovlp and cfg.forbid_neighbour_overlap
            kept = drain and length > 1e-6 and not ovlp_blocks
            log(
                row + f"{sa_:5s} {sb_:5s} {za_:7.2f} {zb_:7.2f} {length:6.2f}  "
                f"{cut_side}  {z_cut:6.2f} {z_fill:6.2f} {slope:7.4f} "
                f"{'Y' if drain else 'n':5s} {'Y' if ovlp else '.':4s} -> "
                f"{'KEEP' if kept else 'drop'}"
            )
            if kept and not (ovlp and cfg.forbid_neighbour_overlap):
                cands.append((t, slope))
                data[t] = (pa_, pb_, za_, zb_, sl_a_, sl_b_, "ok")
            if ovlp and cfg.forbid_neighbour_overlap:
                log(f"  {t:4.0f}  overlap guard would BREAK here (forbid_overlap=True)")
            t += cfg.theta_step_deg
        return cands, data

    cands, data = search(sgn)
    log("\n>>> ALSO tracing opposite sense (-sgn) for comparison <<<")
    cands_opp, data_opp = search(-sgn)
    if cands_opp:
        sl_opp = [s for _, s in cands_opp]
        log(
            f"\nopposite (-sgn) slope range: min={min(sl_opp):.4f} max={max(sl_opp):.4f} "
            f"n={len(sl_opp)}"
        )
        pick_opp = pick_theta(cands_opp, cfg.slope_min, cfg.slope_max)
        if pick_opp is not None:
            log(
                f"opposite (-sgn) pick_theta -> theta={pick_opp[0]:.0f} slope={pick_opp[1]:.4f} "
                f"in_band={cfg.slope_min <= pick_opp[1] <= cfg.slope_max}"
            )
    if not cands:
        log("\nno candidates in aimed direction -> using opposite")
        cands, _data = cands_opp, data_opp

    pick = pick_theta(cands, cfg.slope_min, cfg.slope_max)
    log("")
    if pick is None:
        log("pick_theta -> None (no candidate at all) -> solver returns None")
    else:
        th_sel, slope_sel = pick
        in_band = cfg.slope_min <= slope_sel <= cfg.slope_max
        log(
            f"pick_theta -> theta={th_sel:.0f} slope={slope_sel:.4f} "
            f"in_band={in_band} status={'ok' if in_band else 'out_of_band'}"
        )
        slopes = [s for _, s in cands]
        if slopes:
            log(
                f"candidate slope range: min={min(slopes):.4f} max={max(slopes):.4f} "
                f"n={len(slopes)}"
            )

    # End-to-end check: call the REAL solver and report what it now returns.
    from ditch_core.ditch_solver import solve_ditch

    d = solve_ditch(surface, align_w, sta, cfg)
    if d is None:
        log("\nREAL solve_ditch -> None")
    else:
        log(
            f"\nREAL solve_ditch -> theta={d.theta_deg:.0f} slope={d.slope:.4f} "
            f"status={d.status}  top_z={d.top[2]:.2f} bot_z={d.bot[2]:.2f} "
            f"drains={'Y' if d.top[2] > d.bot[2] else 'N'}"
        )


doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
log(f"=== ditch_solver_trace {datetime.datetime.now():%Y-%m-%d %H:%M:%S} ===")

lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        # list available alignments/surfaces for context
        from Autodesk.Civil.ApplicationServices import CivilApplication
        from Autodesk.Civil.DatabaseServices import Alignment, TinSurface

        cdb = CivilApplication.ActiveDocument
        a_names = []
        for oid in cdb.GetAlignmentIds():
            try:
                e = tx.GetObject(oid, OpenMode.ForRead)
                if isinstance(e, Alignment):
                    a_names.append(e.Name)
            except Exception:
                pass
        s_names = []
        for oid in cdb.GetSurfaceIds():
            try:
                e = tx.GetObject(oid, OpenMode.ForRead)
                if isinstance(e, TinSurface):
                    s_names.append(e.Name)
            except Exception:
                pass
        log(f"alignments: {a_names}")
        log(f"surfaces:   {s_names}")
        log(
            f"CONFIG.alignment_name='{CONFIG.alignment_name}' "
            f"surface_name='{CONFIG.surface_name}' CANAL-check via config"
        )

        align, surface = find_alignment_and_surface(
            tx, CONFIG.alignment_name, CONFIG.surface_name
        )
        log(f"using alignment '{align.Name}', surface '{surface.Name}'")
        align_w = AlignmentWrapper(align, float(align.EndingStation))
        log(f"station range [{align.StartingStation:.2f}, {align.EndingStation:.2f}]")

        for sta in STATIONS:
            try:
                trace_station(surface, align_w, sta, CONFIG)
            except Exception as e:
                log(f"station {sta} ERROR: {e}")
                log(traceback.format_exc())

        log("\n=== DONE ===")
        tx.Commit()
    except Exception as e:
        log(f"ERROR: {e}")
        log(traceback.format_exc())
        tx.Abort()
    finally:
        tx.Dispose()
finally:
    lock.Dispose()

OUT = LOG_FILE
