"""Analyze segment connectivity: weld endpoints by tolerance, find components, map to markers."""

from __future__ import annotations

import clr, datetime, os, traceback

clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import OpenMode, Line, Circle, MText

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\zone_segments\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"zone_conn_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)

# Layers that may carry the zone-boundary segments.
LAYERS = {
    "Новые Откосы.Ситуация.Откосы",
    "Откосы.Поверхность.Структурные линии",
    "0",
}
# Endpoint welding tolerances to try (metres). A gap < EPS between two endpoints
# is treated as a connection ("недотяг" bridged).
EPS_LIST = [0.05, 0.2, 0.5, 1.0]


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


class DSU:
    def __init__(self) -> None:
        self.parent: dict = {}

    def find(self, a):
        p = self.parent.setdefault(a, a)
        while p != a:
            self.parent[a] = self.parent[p]
            a, p = p, self.parent[p]
        return a

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def weld_and_components(segs, eps):
    """Snap endpoints to nodes within eps using a spatial hash; union segments sharing a node.

    Returns (node_of, comp_of_node, components) where:
      node_of[(x,y)] -> node id; components: comp_id -> list of seg indices.
    """
    cell = eps if eps > 0 else 1.0
    grid: dict = {}  # (gx,gy) -> list of (node_id, x, y)
    nodes: list = []  # node_id -> (x,y)

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

    dsu = DSU()
    seg_nodes = []
    for x1, y1, x2, y2 in segs:
        n1, n2 = get_node(x1, y1), get_node(x2, y2)
        dsu.union(n1, n2)
        seg_nodes.append((n1, n2))

    comps: dict = {}
    deg: dict = {}
    for n1, n2 in seg_nodes:
        deg[n1] = deg.get(n1, 0) + 1
        deg[n2] = deg.get(n2, 0) + 1
    for i, (n1, n2) in enumerate(seg_nodes):
        comps.setdefault(dsu.find(n1), []).append(i)
    return nodes, seg_nodes, comps, deg, dsu


doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        ms = tx.GetObject(db.CurrentSpaceId, OpenMode.ForRead)

        segs_by_layer: dict = {ly: [] for ly in LAYERS}
        markers = []  # (text, x, y)
        for oid in ms:
            try:
                ent = tx.GetObject(oid, OpenMode.ForRead)
            except Exception:
                continue
            ly = getattr(ent, "Layer", None)
            if isinstance(ent, Line) and ly in segs_by_layer:
                s, e = ent.StartPoint, ent.EndPoint
                segs_by_layer[ly].append((s.X, s.Y, e.X, e.Y))
            elif isinstance(ent, MText) and ent.Text in ("1", "2"):
                p = ent.Location
                markers.append((ent.Text, p.X, p.Y))

        for ly in LAYERS:
            log(f"layer [{ly}]: {len(segs_by_layer[ly])} segments")
        log(f"markers: {markers}")
        log("")

        # Analyze the main slope layer alone, then combined, across tolerances.
        scenarios = {
            "Откосы only": list(segs_by_layer.get("Новые Откосы.Ситуация.Откосы", [])),
            "Откосы+Структурные": (
                list(segs_by_layer.get("Новые Откосы.Ситуация.Откосы", []))
                + list(segs_by_layer.get("Откосы.Поверхность.Структурные линии", []))
            ),
        }

        for sname, segs in scenarios.items():
            log(
                f"================ SCENARIO: {sname} ({len(segs)} segs) ================"
            )
            for eps in EPS_LIST:
                nodes, seg_nodes, comps, deg, dsu = weld_and_components(segs, eps)
                sizes = sorted(((len(v), k) for k, v in comps.items()), reverse=True)
                open_ends_total = sum(1 for n, d in deg.items() if d == 1)
                log(
                    f"  --- EPS={eps}: {len(comps)} components, "
                    f"{len(nodes)} welded nodes, {open_ends_total} open ends (deg=1) ---"
                )
                for size, cid in sizes[:6]:
                    seg_ids = comps[cid]
                    xs, ys = [], []
                    comp_nodes = set()
                    for i in seg_ids:
                        n1, n2 = seg_nodes[i]
                        comp_nodes.add(n1)
                        comp_nodes.add(n2)
                        x1, y1, x2, y2 = segs[i]
                        xs += [x1, x2]
                        ys += [y1, y2]
                    open_ends = sum(1 for n in comp_nodes if deg.get(n, 0) == 1)
                    bbox = (min(xs), min(ys), max(xs), max(ys))
                    # which markers fall inside this component's bbox
                    inside = [
                        m[0]
                        for m in markers
                        if bbox[0] <= m[1] <= bbox[2] and bbox[1] <= m[2] <= bbox[3]
                    ]
                    log(
                        f"      comp size={size} segs, nodes={len(comp_nodes)}, "
                        f"open_ends={open_ends}, "
                        f"bbox=({bbox[0]:.1f},{bbox[1]:.1f})-({bbox[2]:.1f},{bbox[3]:.1f}), "
                        f"markers_in_bbox={inside}"
                    )
            log("")

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
