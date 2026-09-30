"""Close недотяги (paired open ends), trace faces, draw the TWO largest enclosed areas."""

from __future__ import annotations

import clr, datetime, math, os, traceback

clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import (
    OpenMode,
    Line,
    Polyline,
    LayerTableRecord,
)
from Autodesk.AutoCAD.Geometry import Point2d
from Autodesk.AutoCAD.Colors import Color, ColorMethod

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\zone_segments\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"zone_top2_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)

LAYER = "Новые Откосы.Ситуация.Откосы"
OUT_LAYER = "Контур_зоны"
EPS = 0.5
BRIDGE = (
    60.0  # max distance to bridge a pair of open ends (m); long ribbon tails stay open
)
TOP_N = 2


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
        log(f"  bridged open ends {a}<->{b} gap={d:.2f} m")
    return added, len(ends)


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


def ensure_layer(db, tx, name):
    lt = tx.GetObject(db.LayerTableId, OpenMode.ForRead)
    if lt.Has(name):
        return
    lt.UpgradeOpen()
    ltr = LayerTableRecord()
    ltr.Name = name
    ltr.Color = Color.FromColorIndex(ColorMethod.ByAci, 1)
    lt.Add(ltr)
    tx.AddNewlyCreatedDBObject(ltr, True)


def draw_polyline(ms, tx, pts, layer):
    pl = Polyline()
    for i, (x, y) in enumerate(pts):
        pl.AddVertexAt(i, Point2d(x, y), 0.0, 0.0, 0.0)
    pl.Closed = True
    pl.Layer = layer
    ms.AppendEntity(pl)
    tx.AddNewlyCreatedDBObject(pl, True)


doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        ms = tx.GetObject(db.CurrentSpaceId, OpenMode.ForWrite)
        segs = []
        for oid in ms:
            try:
                ent = tx.GetObject(oid, OpenMode.ForRead)
            except Exception:
                continue
            if isinstance(ent, Line) and getattr(ent, "Layer", None) == LAYER:
                s, e = ent.StartPoint, ent.EndPoint
                segs.append((s.X, s.Y, e.X, e.Y))

        log(f"layer [{LAYER}]: {len(segs)} segs; EPS={EPS} BRIDGE={BRIDGE}")
        nodes, edges = weld(segs, EPS)
        added, nends = bridge_open_ends(nodes, edges, BRIDGE)
        log(
            f"nodes={len(nodes)}, edges={len(edges)}, open ends={nends}, bridged pairs={added}"
        )

        faces = trace_faces(nodes, edges)
        polys = [([nodes[n] for n in f]) for f in faces]
        scored = sorted(
            ((signed_area(p), p) for p in polys), key=lambda t: t[0], reverse=True
        )
        log(f"traced {len(faces)} faces")
        log("=== top 10 positive faces by area ===")
        for ar, p in scored[:10]:
            bb = bbox(p)
            log(
                f"  area={ar:10.1f}  verts={len(p):4d}  bbox=({bb[0]:.0f},{bb[1]:.0f})-({bb[2]:.0f},{bb[3]:.0f})"
            )

        ensure_layer(db, tx, OUT_LAYER)
        drawn = 0
        for ar, p in scored[:TOP_N]:
            if ar > 1.0:
                draw_polyline(ms, tx, p, OUT_LAYER)
                drawn += 1
                bb = bbox(p)
                log(
                    f"DREW face area={ar:.1f} verts={len(p)} bbox=({bb[0]:.0f},{bb[1]:.0f})-({bb[2]:.0f},{bb[3]:.0f})"
                )
        log(f"drawn {drawn} contour(s) on '{OUT_LAYER}'")
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
