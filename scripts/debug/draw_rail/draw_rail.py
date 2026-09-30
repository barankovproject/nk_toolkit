"""Draw the rounded offset "rail" (capsule) around a canal so the user can eyeball whether
the construction is right. Builds the closed outer outline from the canal JSON (P7 left +
P4 right), offsets it OUTWARD by OFFSET with rounded (filleted) convex corners, and draws
one closed lightweight polyline on a debug layer. Re-runnable: clears its own layer first.

Edit QUERY / OFFSET below. Run via draw_rail.dyn (RUNDYNAMOSCRIPT).
"""

from __future__ import annotations

import clr, datetime, json, math, os, sys, traceback

clr.AddReference("AecBaseMgd")
clr.AddReference("AeccDbMgd")
clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import (
    LayerTable,
    LayerTableRecord,
    Line,
    OpenMode,
    Polyline,
    SymbolUtilityServices,
)
from Autodesk.AutoCAD.Geometry import Point2d, Point3d

_LIB_ROOT = r"C:\Arhyz\automation\scripts"
if _LIB_ROOT not in sys.path:
    sys.path.insert(0, _LIB_ROOT)

from civil.utils import normalize  # noqa: E402
from paths import CANALS_DATA_DIR  # noqa: E402

QUERY = "НК-2B-1"
OFFSET = 4.0
LAYER = "dbg_offset_rail"
LEADER_LAYER = "dbg_rail_leaders"
MIN_GAP = 2.5  # min spacing between shelf-starts along the rail

BASE = r"C:\Arhyz\automation\scripts\debug\draw_rail"
LOG_DIR = os.path.join(BASE, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"draw_rail_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)


def log(msg=""):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(str(msg) + "\n")


def load_outline(query):
    norm = normalize(query)
    path = None
    for fn in os.listdir(CANALS_DATA_DIR):
        if fn.endswith(".json") and normalize(fn[:-5]) == norm:
            path = os.path.join(CANALS_DATA_DIR, fn)
            break
    if path is None:
        return None
    sp = json.load(open(path, encoding="utf-8-sig")).get("section_points", {})
    keys = sorted(sp.keys(), key=lambda k: float(k))
    if len(keys) < 2:
        return None
    return [sp[k][8][:2] for k in keys] + [sp[k][5][:2] for k in reversed(keys)]


def load_callout_points(query):
    """Characteristic points to label: P6 (idx 7) and P5 (idx 6) at each callout station."""
    norm = normalize(query)
    path = None
    for fn in os.listdir(CANALS_DATA_DIR):
        if fn.endswith(".json") and normalize(fn[:-5]) == norm:
            path = os.path.join(CANALS_DATA_DIR, fn)
            break
    if path is None:
        return []
    d = json.load(open(path, encoding="utf-8-sig"))
    sp = d.get("section_points", {})
    cs = sorted(float(x) for x in d.get("callout_stations", []))
    pts = []  # (x, y, idx) — idx 7 = P6 (left rail), idx 6 = P5 (right rail)
    for sta in cs:
        k = f"{sta:.3f}"
        if k in sp:
            pts.append((sp[k][7][0], sp[k][7][1], 7))
            pts.append((sp[k][6][0], sp[k][6][1], 6))
    return pts


def ensure_layer(db, tx, name):
    lt = tx.GetObject(db.LayerTableId, OpenMode.ForRead)
    if not lt.Has(name):
        lt.UpgradeOpen()
        rec = LayerTableRecord()
        rec.Name = name
        lt.Add(rec)
        tx.AddNewlyCreatedDBObject(rec, True)


def _area(curve):
    try:
        return abs(float(curve.Area))
    except Exception:
        return 0.0


def spread_centered(vals, gap):
    """vals ascending -> ascending positions >= gap apart, minimal move, centred (PAVA)."""
    blocks = []  # [sum, count]
    for v in vals:
        blocks.append([v, 1])
        while len(blocks) > 1:
            s2, n2 = blocks[-1]
            s1, n1 = blocks[-2]
            bot1 = s1 / n1 + (n1 - 1) / 2.0 * gap  # highest of prev block
            top2 = s2 / n2 - (n2 - 1) / 2.0 * gap  # lowest of next block
            if top2 - bot1 < gap - 1e-9:
                blocks[-2] = [s1 + s2, n1 + n2]
                blocks.pop()
            else:
                break
    out = []
    for s, n in blocks:
        c = s / n
        for k in range(n):
            out.append(c - (n - 1) / 2.0 * gap + k * gap)
    return out


def main(tx, db):
    loop = load_outline(QUERY)
    if not loop:
        log(f"no section_points for '{QUERY}'")
        return
    ensure_layer(db, tx, LAYER)
    ensure_layer(db, tx, LEADER_LAYER)
    ms = tx.GetObject(SymbolUtilityServices.GetBlockModelSpaceId(db), OpenMode.ForWrite)
    # idempotent: erase EVERYTHING previously drawn on the debug layers (any entity type —
    # catches leftover hand-rolled offset polylines and stray arcs, not just Polyline/Line).
    erased = 0
    for oid in ms:
        ent = tx.GetObject(oid, OpenMode.ForRead)
        if ent.Layer in (LAYER, LEADER_LAYER):
            ent.UpgradeOpen()
            ent.Erase()
            erased += 1

    # build the closed canal outline (P7 left + P4 right), then let AutoCAD OFFSET it with
    # rounded corners — OFFSETGAPTYPE=1 = fillet (radius = offset distance). Far more robust
    # than hand-rolled offset geometry.
    Application.SetSystemVariable("OFFSETGAPTYPE", 1)
    outline = Polyline()
    outline.SetDatabaseDefaults()
    for i, (x, y) in enumerate(loop):
        outline.AddVertexAt(i, Point2d(x, y), 0.0, 0.0, 0.0)
    outline.Closed = True

    base = _area(outline)
    best, best_area = None, -1.0
    for dist in (OFFSET, -OFFSET):  # outward = the one whose area grows
        try:
            for c in outline.GetOffsetCurves(dist):
                a = _area(c)
                if a > base and a > best_area:
                    best, best_area = c, a
        except Exception as e:
            log(f"offset {dist} failed: {e}")
    outline.Dispose()
    if best is None:
        log("no outward offset produced")
        return
    best.Layer = LAYER
    ms.AppendEntity(best)
    tx.AddNewlyCreatedDBObject(best, True)

    # Place shelf-starts on the rail. KEY RULE: walk the callout points in the SAME order
    # they wrap around the capsule — left side P6 by ascending station, then right side P5
    # by DESCENDING station (the outline was built P7-asc + P4-desc). Their nearest-rail
    # distances are then monotonic around the closed loop; we UNWRAP the 0-crossing so the
    # sequence is strictly increasing, then spread (PAVA → >= MIN_GAP, order preserved) and
    # map back mod total. Nothing can land out of sequence / fly off.
    total = float(best.GetDistanceAtParameter(best.EndParam))
    pts = load_callout_points(QUERY)
    left = [(x, y) for x, y, idx in pts if idx == 7]  # P6, station ascending
    right_asc = [(x, y) for x, y, idx in pts if idx == 6]  # P5, station ascending

    def foot(p):
        return best.GetDistAtPoint(
            best.GetClosestPointTo(Point3d(p[0], p[1], 0.0), False)
        )

    def draw_leader(p, d):
        ln = Line(Point3d(p[0], p[1], 0.0), best.GetPointAtDist(d % total))
        ln.Layer = LEADER_LAYER
        ms.AppendEntity(ln)
        tx.AddNewlyCreatedDBObject(ln, True)

    axis = [
        ((lx + rx) / 2.0, (ly + ry) / 2.0)
        for (lx, ly), (rx, ry) in zip(left, right_asc)
    ]

    def cap_apex_dist(m, fx, fy):
        """Rail distance of the cap apex — the rail point off the end along the canal axis
        (m + OFFSET * outward), used to pick which arc between the two corners IS the cap."""
        d = (fx * fx + fy * fy) ** 0.5 or 1.0
        target = (m[0] + OFFSET * fx / d, m[1] + OFFSET * fy / d)
        return foot(target)

    nlead = 0
    # --- caps: the two end-section corners fan EVENLY (1/3, 2/3) across the cap arc — the arc
    #     between their feet that passes through the apex (so it wraps AROUND the end, not back
    #     into the canal).
    caps = [
        (
            [left[-1], right_asc[-1]],
            axis[-1],
            axis[-1][0] - axis[-2][0],
            axis[-1][1] - axis[-2][1],
        ),
        (
            [left[0], right_asc[0]],
            axis[0],
            axis[0][0] - axis[1][0],
            axis[0][1] - axis[1][1],
        ),
    ]

    def circ_dist(a, b):  # shortest distance between two positions on the closed rail
        d = abs(a - b) % total
        return min(d, total - d)

    arc = math.pi * OFFSET  # full cap arc length (180° semicircle, R = OFFSET)
    for pair, m, fx, fy in caps:
        apex = cap_apex_dist(m, fx, fy)
        # the 2 corners splay EVENLY (1/3, 2/3) across the FULL cap arc centred on the apex.
        q = [apex - arc / 2.0 + arc / 3.0, apex - arc / 2.0 + 2.0 * arc / 3.0]
        # keep each corner on its own side of the cap (nearest target to its own foot)
        if circ_dist(foot(pair[0]), q[0]) > circ_dist(foot(pair[0]), q[1]):
            q = [q[1], q[0]]
        for p, qd in zip(pair, q):
            draw_leader(p, qd)
            nlead += 1

    # --- sides: the middle points (excluding the cap corners) in loop order, unwrapped and
    #     spread so they stay sequential and >= MIN_GAP apart (near-perpendicular leaders).
    seq = left[1:-1] + list(reversed(right_asc))[1:-1]
    if seq:
        raw = [foot(p) for p in seq]

        def unwrap(vals):
            out = [vals[0]]
            for v in vals[1:]:
                while v < out[-1] - total / 2.0:
                    v += total
                while v > out[-1] + total / 2.0:
                    v -= total
                out.append(v)
            return out

        fwd = unwrap(raw)
        if fwd[-1] - fwd[0] < 0:
            seq = seq[::-1]
            fwd = unwrap([foot(p) for p in seq])
        for p, d1 in zip(seq, spread_centered(fwd, MIN_GAP)):
            draw_leader(p, d1)
            nlead += 1
    log(
        f"'{QUERY}': OFFSET={OFFSET} via GetOffsetCurves, area={best_area:.1f}, "
        f"erased {erased} old, {nlead} leaders (MIN_GAP={MIN_GAP})"
    )


doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        log("=== DRAW RAIL ===")
        main(tx, db)
        log("=== DONE ===")
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
