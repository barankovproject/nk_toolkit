"""Diagnose why markers aren't enclosed: list open ends + gaps, and locate each marker vs faces."""

from __future__ import annotations

import clr, datetime, math, os, traceback

clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import OpenMode, Line, MText

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\zone_segments\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"zone_diag_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)

LAYER = "Новые Откосы.Ситуация.Откосы"
EPS = 0.5


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

    edges = set()
    for x1, y1, x2, y2 in segs:
        n1, n2 = get_node(x1, y1), get_node(x2, y2)
        if n1 != n2:
            edges.add((min(n1, n2), max(n1, n2)))
    return nodes, edges


def trace_faces(nodes, edges):
    adj: dict = {}
    for a, b in edges:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    order: dict = {}
    for u, nbrs in adj.items():
        ux, uy = nodes[u]
        order[u] = sorted(
            nbrs, key=lambda v: math.atan2(nodes[v][1] - uy, nodes[v][0] - ux)
        )
    pos = {u: {v: i for i, v in enumerate(lst)} for u, lst in order.items()}
    visited = set()
    faces = []
    for a, b in edges:
        for u, v in ((a, b), (b, a)):
            if (u, v) in visited:
                continue
            face = []
            cu, cv = u, v
            guard = 0
            while True:
                visited.add((cu, cv))
                face.append(cu)
                lst = order[cv]
                idx = pos[cv][cu]
                nxt = lst[(idx - 1) % len(lst)]
                cu, cv = cv, nxt
                guard += 1
                if (cu, cv) == (u, v) or guard > len(edges) * 2 + 10:
                    break
            if len(face) >= 3:
                faces.append(face)
    return faces


def signed_area(pts):
    a = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return a / 2.0


def bbox(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


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


def seg_dist(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


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

        nodes, edges = weld(segs, EPS)
        deg: dict = {}
        for a, b in edges:
            deg[a] = deg.get(a, 0) + 1
            deg[b] = deg.get(b, 0) + 1
        ends = [n for n in range(len(nodes)) if deg.get(n, 0) == 1]
        log(
            f"{len(segs)} segs, {len(nodes)} nodes, {len(edges)} edges, {len(ends)} open ends, EPS={EPS}"
        )
        log("")
        log("=== OPEN ENDS (deg=1) and nearest other open end ===")
        for i in ends:
            xi, yi = nodes[i]
            best, bestd = None, 1e18
            for j in ends:
                if j == i:
                    continue
                xj, yj = nodes[j]
                d = math.hypot(xi - xj, yi - yj)
                if d < bestd:
                    best, bestd = j, d
            log(f"  node {i} ({xi:.2f},{yi:.2f}) nearest open end -> {bestd:.2f} m")

        faces = trace_faces(nodes, edges)
        polys = [
            (signed_area([nodes[n] for n in f]), [nodes[n] for n in f]) for f in faces
        ]
        polys.sort(key=lambda t: t[0])
        log("")
        log("=== top 5 faces by area (most negative = outer) ===")
        for ar, pts in polys[:3] + polys[-5:]:
            bb = bbox(pts)
            log(
                f"  area={ar:10.1f} verts={len(pts):4d} bbox=({bb[0]:.0f},{bb[1]:.0f})-({bb[2]:.0f},{bb[3]:.0f})"
            )

        log("")
        log("=== marker location ===")
        for mtext, mx, my in markers:
            containing = []
            for ar, pts in polys:
                if point_in_poly(mx, my, pts):
                    containing.append((ar, len(pts)))
            # nearest edge distance
            mind = 1e18
            for x1, y1, x2, y2 in segs:
                d = seg_dist(mx, my, x1, y1, x2, y2)
                if d < mind:
                    mind = d
            log(
                f"  marker '{mtext}' ({mx:.1f},{my:.1f}): nearest edge={mind:.2f} m; "
                f"contained in {len(containing)} faces: {containing[:6]}"
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
