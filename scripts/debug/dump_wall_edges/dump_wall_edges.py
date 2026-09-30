"""Dump: find GSI ditch-wall blocks (inf_gsi_ditch_wall) with any edge chord > 2.0 m.

Iteration 2 — the first pass found NO edge > 2.0 among 189 blocks, yet the user
measured 2.336 on V-5A-2. So now also: per-block XData tube tag (which tubes' walls
are in this drawing at all), max same-face vertex-pair distance (a DIST snap across a
face diagonal), and max any-vertex-pair distance (3D box diagonal). Regular 2x1x1
block: face diagonal 2.236, box diagonal 2.449 — report faces whose diagonal exceeds
2.30 and blocks whose box diagonal exceeds 2.46, with the vertex pair coordinates.
"""

from __future__ import annotations

import clr
import datetime
import math
import os
import traceback

clr.AddReference("acmgd")
clr.AddReference("acdbmgd")
clr.AddReference("acdbmgdbrep")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.BoundaryRepresentation import Brep
from Autodesk.AutoCAD.DatabaseServices import OpenMode, Solid3d, SymbolUtilityServices

LOG_DIR = r"C:\Arhyz\automation\scripts\debug\dump_wall_edges\logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(
    LOG_DIR, f"dump_wall_edges_{datetime.datetime.now():%Y%m%d_%H%M%S}.log"
)

_LAYER = "inf_gsi_ditch_wall"
_MAX_EDGE = 2.001


def log(msg: str = "") -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def block_geom(sol):
    """(edges, faces) of a solid via Brep: unique edge chords + per-face vertex sets."""
    brep = Brep(sol)
    seen = set()
    edges = []
    faces = []
    for face in brep.Faces:
        for loop in face.Loops:
            for ed in loop.Edges:
                p1 = ed.Vertex1.Point
                p2 = ed.Vertex2.Point
                a = (round(p1.X, 6), round(p1.Y, 6), round(p1.Z, 6))
                b = (round(p2.X, 6), round(p2.Y, 6), round(p2.Z, 6))
                key = (a, b) if a <= b else (b, a)
                if key in seen:
                    continue
                seen.add(key)
                edges.append((a, b))
    for face in brep.Faces:
        fverts = set()
        for loop in face.Loops:
            for ed in loop.Edges:
                p1 = ed.Vertex1.Point
                p2 = ed.Vertex2.Point
                fverts.add((round(p1.X, 6), round(p1.Y, 6), round(p1.Z, 6)))
                fverts.add((round(p2.X, 6), round(p2.Y, 6), round(p2.Z, 6)))
        faces.append(sorted(fverts))
    return edges, faces


def max_pair(verts):
    """(dist, a, b) of the farthest vertex pair."""
    best = (0.0, None, None)
    for i in range(len(verts)):
        for j in range(i + 1, len(verts)):
            d = math.dist(verts[i], verts[j])
            if d > best[0]:
                best = (d, verts[i], verts[j])
    return best


def read_tag(ent):
    try:
        rb = ent.GetXDataForApplication("ARHYZ_GSI")
    except Exception:
        return None
    if rb is None:
        return None
    vals = [str(v.Value) for v in list(rb) if v.TypeCode == 1000]
    return tuple(vals[:2]) if len(vals) >= 2 else None


doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        log(f"drawing: {db.Filename}")
        ms = tx.GetObject(
            SymbolUtilityServices.GetBlockModelSpaceId(db), OpenMode.ForRead
        )
        n_blocks = 0
        tubes = {}  # tag -> [count, max_edge, max_face_diag, max_box_diag]
        suspects = []  # (metric, text lines)
        for oid in ms:
            o = tx.GetObject(oid, OpenMode.ForRead)
            if not (isinstance(o, Solid3d) and o.Layer == _LAYER):
                continue
            n_blocks += 1
            tag = read_tag(o) or ("?", "untagged")
            try:
                edges, faces = block_geom(o)
            except Exception as e:
                log(f"block {n_blocks} [{tag[1]}]: Brep failed: {e}")
                continue
            max_edge = max((math.dist(a, b) for a, b in edges), default=0.0)
            fd_best = (0.0, None, None)
            for fverts in faces:
                fd = max_pair(fverts)
                if fd[0] > fd_best[0]:
                    fd_best = fd
            all_verts = sorted({v for a, b in edges for v in (a, b)})
            box = max_pair(all_verts)
            st = tubes.setdefault(tag, [0, 0.0, 0.0, 0.0])
            st[0] += 1
            st[1] = max(st[1], max_edge)
            st[2] = max(st[2], fd_best[0])
            st[3] = max(st[3], box[0])
            if max_edge > _MAX_EDGE or fd_best[0] > 2.30 or box[0] > 2.46:
                a, b = fd_best[1], fd_best[2]
                suspects.append(
                    (
                        max(max_edge, fd_best[0]),
                        f"block #{n_blocks} [{tag[0]}/{tag[1]}] "
                        f"max_edge={max_edge:.3f} face_diag={fd_best[0]:.3f} "
                        f"box_diag={box[0]:.3f}\n"
                        f"    face_diag pair: A=({a[0]:.3f},{a[1]:.3f},{a[2]:.3f}) "
                        f"B=({b[0]:.3f},{b[1]:.3f},{b[2]:.3f})\n"
                        f"    box pair: A={box[1]}  B={box[2]}",
                    )
                )
        log(f"wall blocks scanned: {n_blocks}")
        log("per tube tag: count / max edge / max face diag / max box diag")
        for tag in sorted(tubes):
            c, me, mf, mb = tubes[tag]
            log(f"    {tag[0]}/{tag[1]}: {c}  {me:.3f}  {mf:.3f}  {mb:.3f}")
        log("")
        log(
            f"suspect blocks (edge>2.001 or face_diag>2.30 or box_diag>2.46): "
            f"{len(suspects)}"
        )
        for _, txt in sorted(suspects, reverse=True):
            log(txt)
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
