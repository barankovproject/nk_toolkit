"""Snap a rough hand-drawn closed polyline to the real banks/frame; draw a cleaned contour."""

from __future__ import annotations

import clr, datetime, math, os, traceback

clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import (
    OpenMode,
    Line,
    Polyline,
    MText,
    LayerTableRecord,
)
from Autodesk.AutoCAD.Geometry import Point2d
from Autodesk.AutoCAD.Colors import Color, ColorMethod

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\zone_segments\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"zone_snap_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)

OUT_LAYER = "Контур_зоны"
# Layers whose Line entities are "real boundary" to snap onto.
BOUNDARY_LINE_LAYERS = {
    "Новые Откосы.Ситуация.Откосы",
    "Откосы.Поверхность.Структурные линии",
    "0",
}
RESAMPLE = 1.0  # densify the rough polyline to this step (m)
SNAP_R = 40.0  # snap a resampled point to a real edge within this radius (m)
SIMPLIFY_TOL = (
    0.3  # Douglas-Peucker tolerance (m): drop vertices within this of the chord
)
FRAME_AREA_MIN = (
    1.0e6  # closed polylines larger than this are the frame, not a rough contour
)


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def poly_pts(pl):
    return [
        (pl.GetPoint2dAt(i).X, pl.GetPoint2dAt(i).Y) for i in range(pl.NumberOfVertices)
    ]


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


def resample(pts, step):
    out = []
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        seg = math.hypot(x2 - x1, y2 - y1)
        k = max(1, int(seg / step))
        for t in range(k):
            f = t / k
            out.append((x1 + f * (x2 - x1), y1 + f * (y2 - y1)))
    return out


def nearest_on_seg(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return (x1, y1), math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / L2))
    qx, qy = x1 + t * dx, y1 + t * dy
    return (qx, qy), math.hypot(px - qx, py - qy)


class Grid:
    """Spatial hash of boundary segments for fast nearest-segment queries."""

    def __init__(self, segs, cell):
        self.cell = cell
        self.segs = segs
        self.idx = {}
        for k, (x1, y1, x2, y2) in enumerate(segs):
            for cx, cy in self._cells(x1, y1, x2, y2):
                self.idx.setdefault((cx, cy), []).append(k)

    def _cells(self, x1, y1, x2, y2):
        c = self.cell
        n = max(1, int(math.hypot(x2 - x1, y2 - y1) / c))
        out = set()
        for t in range(n + 1):
            f = t / n
            out.add((int((x1 + f * (x2 - x1)) // c), int((y1 + f * (y2 - y1)) // c)))
        return out

    def nearest(self, px, py, rmax):
        c = self.cell
        gx, gy = int(px // c), int(py // c)
        rc = int(rmax // c) + 1
        best, bestd = None, rmax
        seen = set()
        for dx in range(-rc, rc + 1):
            for dy in range(-rc, rc + 1):
                for k in self.idx.get((gx + dx, gy + dy), ()):
                    if k in seen:
                        continue
                    seen.add(k)
                    q, d = nearest_on_seg(px, py, *self.segs[k])
                    if d < bestd:
                        best, bestd = q, d
        return best, bestd


def rdp(points, eps):
    """Iterative Douglas-Peucker: drop vertices closer than eps to the chord they span.

    Removes points that lie (within eps) on a straight line between kept neighbours.
    `points` is an open path; for a closed ring, append the first point before calling.
    """
    n = len(points)
    if n < 3:
        return points[:]
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        s, e = stack.pop()
        x1, y1 = points[s]
        x2, y2 = points[e]
        dx, dy = x2 - x1, y2 - y1
        L2 = dx * dx + dy * dy
        dmax, idx = 0.0, -1
        for i in range(s + 1, e):
            px, py = points[i]
            if L2 == 0:
                d = math.hypot(px - x1, py - y1)
            else:
                t = ((px - x1) * dx + (py - y1) * dy) / L2
                qx, qy = x1 + t * dx, y1 + t * dy
                d = math.hypot(px - qx, py - qy)
            if d > dmax:
                dmax, idx = d, i
        if dmax > eps and idx != -1:
            keep[idx] = True
            stack.append((s, idx))
            stack.append((idx, e))
    return [points[i] for i in range(n) if keep[i]]


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
        bound_segs = []
        markers = []
        rough = []  # (pts, area, oid) candidate rough contours
        out_oids = []  # existing OUT_LAYER entities to delete
        for oid in ms:
            try:
                ent = tx.GetObject(oid, OpenMode.ForRead)
            except Exception:
                continue
            ly = getattr(ent, "Layer", None)
            if ly == OUT_LAYER:
                out_oids.append(oid)
                continue
            if isinstance(ent, Line) and ly in BOUNDARY_LINE_LAYERS:
                s, e = ent.StartPoint, ent.EndPoint
                bound_segs.append((s.X, s.Y, e.X, e.Y))
            elif isinstance(ent, Polyline):
                pts = poly_pts(ent)
                ar = poly_area(pts)
                if ent.Closed and ar >= FRAME_AREA_MIN:
                    # the frame: a real boundary to snap onto
                    for i in range(len(pts)):
                        a = pts[i]
                        b = pts[(i + 1) % len(pts)]
                        bound_segs.append((a[0], a[1], b[0], b[1]))
                elif ent.Closed and ar > 100.0:
                    rough.append((pts, ar, oid))
            elif isinstance(ent, MText) and ent.Text in ("1", "2"):
                p = ent.Location
                markers.append((ent.Text, p.X, p.Y))

        log(
            f"boundary segs={len(bound_segs)}, rough candidates={len(rough)}, markers={markers}"
        )
        for pts, ar, _ in rough:
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            log(
                f"  rough: nverts={len(pts)} area={ar:.1f} "
                f"bbox=({min(xs):.0f},{min(ys):.0f})-({max(xs):.0f},{max(ys):.0f})"
            )

        # delete previous OUT_LAYER outputs
        for oid in out_oids:
            try:
                tx.GetObject(oid, OpenMode.ForWrite).Erase()
            except Exception:
                pass
        log(f"erased {len(out_oids)} old '{OUT_LAYER}' entities")

        if not rough:
            log(
                "NO rough contour found — draw a closed polyline around the zone and re-run."
            )
            log("=== DONE ===")
            tx.Commit()
        else:
            grid = Grid(bound_segs, cell=10.0)
            ensure_layer(db, tx, OUT_LAYER)
            drawn = 0
            for pts, ar, oid in rough:
                rs = resample(pts, RESAMPLE)
                snapped = []
                n_snap = 0
                for px, py in rs:
                    q, d = grid.nearest(px, py, SNAP_R)
                    if q is not None:
                        snapped.append(q)
                        n_snap += 1
                    else:
                        snapped.append((px, py))
                # dedupe consecutive duplicates
                clean = [snapped[0]]
                for p in snapped[1:]:
                    if math.hypot(p[0] - clean[-1][0], p[1] - clean[-1][1]) > 0.05:
                        clean.append(p)
                # thin out collinear / near-collinear vertices (closed ring)
                simp = rdp(clean + [clean[0]], SIMPLIFY_TOL)
                if len(simp) > 1 and simp[-1] == simp[0]:
                    simp = simp[:-1]
                draw_polyline(ms, tx, simp, OUT_LAYER)
                drawn += 1
                log(
                    f"  rough(area={ar:.0f}): {len(rs)} samples, {n_snap} snapped "
                    f"({100 * n_snap / len(rs):.0f}%), snapped verts={len(clean)} "
                    f"-> simplified={len(simp)} (tol={SIMPLIFY_TOL} m)"
                )
            log(f"drawn {drawn} cleaned contour(s) on '{OUT_LAYER}'")
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
