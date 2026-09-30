"""Include the rectangle polyline as a closing boundary; locate each marker's bounded face."""

from __future__ import annotations

import clr, datetime, math, os, traceback

clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import OpenMode, Line, Polyline, MText

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\zone_segments\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"zone_frame_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)

BANK_LAYER = "Новые Откосы.Ситуация.Откосы"
EPS = 0.5
BRIDGE = 60.0


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


def bridge_open_ends(nodes, edges, bridge):
    deg: dict = {}
    for a, b in edges:
        deg[a] = deg.get(a, 0) + 1
        deg[b] = deg.get(b, 0) + 1
    ends = [n for n in range(len(nodes)) if deg.get(n, 0) == 1]
    pairs = []
    for i in range(len(ends)):
        for j in range(i + 1, len(ends)):
            a, b = ends[i], ends[j]
            d = math.hypot(nodes[a][0] - nodes[b][0], nodes[a][1] - nodes[b][1])
            if d <= bridge:
                pairs.append((d, a, b))
    pairs.sort()
    used = set()
    added = 0
    for d, a, b in pairs:
        if a in used or b in used:
            continue
        edges.add((min(a, b), max(a, b)))
        used.add(a)
        used.add(b)
        added += 1
    return added, len(ends)


def trace_faces(nodes, edges):
    adj: dict = {}
    for a, b in edges:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    order = {}
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
                nxt = lst[(pos[cv][cu] - 1) % len(lst)]
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


doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        ms = tx.GetObject(db.CurrentSpaceId, OpenMode.ForRead)
        bank_segs = []
        poly_segs = []
        markers = []
        polys_info = []
        for oid in ms:
            try:
                ent = tx.GetObject(oid, OpenMode.ForRead)
            except Exception:
                continue
            ly = getattr(ent, "Layer", None)
            if isinstance(ent, Line) and ly == BANK_LAYER:
                s, e = ent.StartPoint, ent.EndPoint
                bank_segs.append((s.X, s.Y, e.X, e.Y))
            elif isinstance(ent, Polyline):
                n = ent.NumberOfVertices
                pts = [ent.GetPoint2dAt(i) for i in range(n)]
                bb = bbox([(p.X, p.Y) for p in pts])
                polys_info.append((ly, n, ent.Closed, bb))
                rng = max(bb[2] - bb[0], bb[3] - bb[1])
                # treat large polylines (the frame / трассы outlines) as boundary
                for i in range(n - 1 + (1 if ent.Closed else 0)):
                    a = pts[i % n]
                    b = pts[(i + 1) % n]
                    poly_segs.append((a.X, a.Y, b.X, b.Y))
            elif isinstance(ent, MText) and ent.Text in ("1", "2"):
                p = ent.Location
                markers.append((ent.Text, p.X, p.Y))

        log(
            f"bank segs={len(bank_segs)}, poly segs={len(poly_segs)}, markers={markers}"
        )
        log("polylines:")
        for ly, n, closed, bb in polys_info:
            log(
                f"  [{ly}] n={n} closed={closed} bbox=({bb[0]:.1f},{bb[1]:.1f})-({bb[2]:.1f},{bb[3]:.1f})"
            )

        segs = bank_segs + poly_segs
        nodes, edges = weld(segs, EPS)
        added, nends = bridge_open_ends(nodes, edges, BRIDGE)
        log(f"nodes={len(nodes)} edges={len(edges)} open_ends={nends} bridged={added}")

        faces = trace_faces(nodes, edges)
        polys = [
            (signed_area([nodes[n] for n in f]), [nodes[n] for n in f]) for f in faces
        ]
        log(f"traced {len(faces)} faces")

        for mtext, mx, my in markers:
            cand = [
                (ar, pts)
                for ar, pts in polys
                if ar > 1.0 and point_in_poly(mx, my, pts)
            ]
            cand.sort(key=lambda t: t[0])
            log(f"marker '{mtext}' ({mx:.1f},{my:.1f}): {len(cand)} enclosing faces")
            for ar, pts in cand[:3]:
                bb = bbox(pts)
                log(
                    f"    area={ar:.1f} verts={len(pts)} bbox=({bb[0]:.0f},{bb[1]:.0f})-({bb[2]:.0f},{bb[3]:.0f})"
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
