"""Trace each component into an ordered ring, bridge single gaps, find smallest loop per marker."""

from __future__ import annotations

import clr, datetime, math, os, traceback

clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import OpenMode, Line, MText

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\zone_segments\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"zone_trace_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)

LAYER = "Новые Откосы.Ситуация.Откосы"
EPS = 0.5  # endpoint welding tolerance (m)


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def weld(segs, eps):
    cell = eps if eps > 0 else 1.0
    grid: dict = {}
    nodes: list = []

    def get_node(x, y):
        gx, gy = int(x // cell), int(y // cell)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for nid, nx, ny in grid.get((gx + dx, gy + dy), ()):
                    if (nx - x) ** 2 + (ny - y) ** 2 <= eps * eps:
                        return nid
        nid = len(nodes)
        nodes.append((x, y))
        grid.setdefault((gx, gy), []).append((nid, x, y))
        return nid

    adj: dict = {}
    seg_nodes = []
    for x1, y1, x2, y2 in segs:
        n1, n2 = get_node(x1, y1), get_node(x2, y2)
        if n1 == n2:
            continue
        seg_nodes.append((n1, n2))
        adj.setdefault(n1, set()).add(n2)
        adj.setdefault(n2, set()).add(n1)
    return nodes, adj, seg_nodes


def components(adj):
    seen = set()
    comps = []
    for start in adj:
        if start in seen:
            continue
        stack = [start]
        comp = []
        seen.add(start)
        while stack:
            n = stack.pop()
            comp.append(n)
            for m in adj[n]:
                if m not in seen:
                    seen.add(m)
                    stack.append(m)
        comps.append(comp)
    return comps


def trace_ring(comp_nodes, adj, nodes, eps):
    """Trace an ordered ring. Bridge the two open ends (deg=1) if present."""
    ends = [n for n in comp_nodes if len(adj[n]) == 1]
    maxdeg = max(len(adj[n]) for n in comp_nodes)
    # bridge: if exactly two open ends, connect them (close the недотяг)
    local_adj = {n: set(adj[n]) for n in comp_nodes}
    bridged = False
    if len(ends) == 2:
        a, b = ends
        local_adj[a].add(b)
        local_adj[b].add(a)
        bridged = True
    # walk the cycle starting anywhere
    start = comp_nodes[0]
    ring = [start]
    prev = None
    cur = start
    while True:
        nbrs = [m for m in local_adj[cur] if m != prev]
        if not nbrs:
            break
        nxt = nbrs[0]
        if nxt == start:
            break
        ring.append(nxt)
        prev, cur = cur, nxt
        if len(ring) > len(comp_nodes) + 5:
            break
    closed = len(ring) >= 3 and (start in local_adj[ring[-1]])
    return ring, closed, maxdeg, len(ends), bridged


def poly_area(pts):
    a = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


def point_in_poly(px, py, pts):
    inside = False
    n = len(pts)
    j = n - 1
    for i in range(n):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if ((yi > py) != (yj > py)) and (
            px < (xj - xi) * (py - yi) / (yj - yi + 1e-12) + xi
        ):
            inside = not inside
        j = i
    return inside


doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        ms = tx.GetObject(db.CurrentSpaceId, OpenMode.ForRead)
        segs = []
        markers = []
        for oid in ms:
            try:
                ent = tx.GetObject(oid, OpenMode.ForRead)
            except Exception:
                continue
            if isinstance(ent, Line) and getattr(ent, "Layer", None) == LAYER:
                s, e = ent.StartPoint, ent.EndPoint
                segs.append((s.X, s.Y, e.X, e.Y))
            elif isinstance(ent, MText) and ent.Text in ("1", "2"):
                p = ent.Location
                markers.append((ent.Text, p.X, p.Y))

        log(f"layer [{LAYER}]: {len(segs)} segments; markers={markers}; EPS={EPS}")
        nodes, adj, seg_nodes = weld(segs, EPS)
        comps = components(adj)
        log(f"{len(comps)} components")
        log("")

        rings = []  # (cid, pts, area, closed, bridged)
        for cid, comp in enumerate(comps):
            ring, closed, maxdeg, nends, bridged = trace_ring(comp, adj, nodes, EPS)
            pts = [nodes[n] for n in ring]
            area = poly_area(pts) if len(pts) >= 3 else 0.0
            covered = len(ring) >= 0.9 * len(comp)  # did the walk cover the component?
            log(
                f"comp #{cid}: nodes={len(comp)}, ring_pts={len(ring)}, "
                f"maxdeg={maxdeg}, open_ends={nends}, bridged={bridged}, "
                f"closed={closed}, covered={covered}, area={area:.1f}"
            )
            if closed and len(pts) >= 3:
                rings.append((cid, pts, area))

        log("")
        log("=== marker -> smallest enclosing closed ring ===")
        for mtext, mx, my in markers:
            enclosing = [
                (area, cid, pts)
                for (cid, pts, area) in rings
                if point_in_poly(mx, my, pts)
            ]
            enclosing.sort()
            if enclosing:
                area, cid, pts = enclosing[0]
                log(
                    f"  marker '{mtext}' ({mx:.1f},{my:.1f}) -> comp #{cid}, "
                    f"area={area:.1f}, ring_pts={len(pts)}"
                )
                for a2, c2, _ in enclosing[1:]:
                    log(f"      (also inside comp #{c2}, area={a2:.1f})")
            else:
                log(
                    f"  marker '{mtext}' ({mx:.1f},{my:.1f}) -> NO enclosing closed ring"
                )

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
