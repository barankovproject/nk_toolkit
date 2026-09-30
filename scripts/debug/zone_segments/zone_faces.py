"""Planar-arrangement face extraction: weld gaps, trace faces, draw the face enclosing each marker."""

from __future__ import annotations

import clr, datetime, math, os, traceback

clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import (
    OpenMode,
    Line,
    MText,
    Polyline,
    LayerTable,
    LayerTableRecord,
)
from Autodesk.AutoCAD.Geometry import Point2d
from Autodesk.AutoCAD.Colors import Color, ColorMethod

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\zone_segments\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"zone_faces_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)

LAYER = "Новые Откосы.Ситуация.Откосы"
OUT_LAYER = "Контур_зоны"
EPS = 0.5  # endpoint weld tolerance (m)
BRIDGE = 3.0  # max distance to bridge a remaining open end to another open end (m)


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
    """Connect each degree-1 node to its nearest other degree-1 node within `bridge`."""
    deg: dict = {}
    for a, b in edges:
        deg[a] = deg.get(a, 0) + 1
        deg[b] = deg.get(b, 0) + 1
    ends = [n for n in range(len(nodes)) if deg.get(n, 0) == 1]
    added = 0
    used = set()
    for i in ends:
        if i in used:
            continue
        xi, yi = nodes[i]
        best, bestd = None, bridge * bridge
        for j in ends:
            if j == i or j in used:
                continue
            xj, yj = nodes[j]
            d = (xi - xj) ** 2 + (yi - yj) ** 2
            if d <= bestd:
                best, bestd = j, d
        if best is not None:
            edges.add((min(i, best), max(i, best)))
            used.add(i)
            used.add(best)
            added += 1
    return added, len(ends)


def trace_faces(nodes, edges):
    """Half-edge face traversal. Returns list of faces as lists of node ids (CCW positive)."""
    adj: dict = {}
    for a, b in edges:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    # CCW-sorted neighbours per node
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
                nxt = lst[(idx - 1) % len(lst)]  # clockwise-next around cv
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


def ensure_layer(db, tx, name):
    lt = tx.GetObject(db.LayerTableId, OpenMode.ForRead)
    if lt.Has(name):
        return
    lt.UpgradeOpen()
    ltr = LayerTableRecord()
    ltr.Name = name
    ltr.Color = Color.FromColorIndex(ColorMethod.ByAci, 1)  # red
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

        log(
            f"layer [{LAYER}]: {len(segs)} segs; markers={markers}; EPS={EPS} BRIDGE={BRIDGE}"
        )
        nodes, edges = weld(segs, EPS)
        added, nends = bridge_open_ends(nodes, edges, BRIDGE)
        log(
            f"welded nodes={len(nodes)}, edges={len(edges)}, open ends={nends}, bridged={added}"
        )

        faces = trace_faces(nodes, edges)
        log(f"traced {len(faces)} half-edge faces")

        # bounded faces = positive signed area (CCW); skip the outer face (largest |area|, CW)
        face_polys = []
        for f in faces:
            pts = [nodes[n] for n in f]
            ar = signed_area(pts)
            face_polys.append((ar, pts))
        areas = [ar for ar, _ in face_polys]
        log(f"signed-area range: min={min(areas):.1f} max={max(areas):.1f}")

        ensure_layer(db, tx, OUT_LAYER)
        drawn = 0
        for mtext, mx, my in markers:
            cand = [
                (ar, pts)
                for ar, pts in face_polys
                if ar > 1.0 and point_in_poly(mx, my, pts)
            ]
            cand.sort(key=lambda t: t[0])  # smallest positive area enclosing the marker
            if cand:
                ar, pts = cand[0]
                draw_polyline(ms, tx, pts, OUT_LAYER)
                drawn += 1
                log(
                    f"  marker '{mtext}' ({mx:.1f},{my:.1f}) -> face area={ar:.1f}, "
                    f"verts={len(pts)} -> drawn on '{OUT_LAYER}'"
                )
            else:
                log(
                    f"  marker '{mtext}' ({mx:.1f},{my:.1f}) -> NO enclosing bounded face"
                )

        log(f"drawn {drawn} contour(s)")
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
