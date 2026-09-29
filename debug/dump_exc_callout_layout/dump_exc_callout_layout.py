"""Dump the user's hand-tuned excavation BOTTOM (низ) callout layout.

Two things are captured so annotate_excavation_points/_rail_params_inner can be tuned:

1. Reference rails — polylines the user drew at lineweight 0.50: external PURPLE
   (фиолетовая) and internal YELLOW (жёлтая). Their vertices, colour and lineweight
   are logged, and each is classified yellow-vs-other by ACI.

2. Every point_number BlockReference — insertion (= contour vertex), the dynamic
   props "Отраженное состояние1" (flip), "Положение1 X/Y", and the т.N text. From
   those the RED point (polka↔leader junction) is reconstructed exactly as the
   builder places it: red = insertion + (p1x + (1-2*flip)*POLKA_LEN, p1y). For each
   callout the min distance from its red point to each rail is reported, so we can
   read off which rail (inner/outer) it rides and the offset from the contour.
"""

from __future__ import annotations

import clr, datetime, math, os, traceback
from typing import Any

clr.AddReference("acmgd")
clr.AddReference("acdbmgd")

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import (
    AttributeReference,
    BlockReference,
    LineWeight,
    OpenMode,
    Polyline,
    Polyline2d,
    Polyline3d,
    SymbolUtilityServices,
)

BASE = r"C:\Arhyz\automation\scripts\debug\dump_exc_callout_layout"
os.makedirs(os.path.join(BASE, "logs"), exist_ok=True)
LOG = os.path.join(BASE, "logs", f"dump_{datetime.datetime.now():%Y%m%d_%H%M%S}.log")

# Must match builder._POLKA_LEN so the reconstructed red point matches placement.
POLKA_LEN = 1.647
LW_050 = int(LineWeight.LineWeight050)  # 50


def log(m: Any = "") -> None:
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(str(m) + "\n")


def eff_name(br: Any, tx: Any) -> str:
    try:
        if br.IsDynamicBlock:
            return tx.GetObject(br.DynamicBlockTableRecord, OpenMode.ForRead).Name
    except Exception:
        pass
    return tx.GetObject(br.BlockTableRecord, OpenMode.ForRead).Name


def color_desc(ent: Any) -> str:
    try:
        c = ent.Color
        if c.IsByAci:
            return f"ACI={c.ColorIndex}"
        return f"RGB=({c.Red},{c.Green},{c.Blue}) method={c.ColorMethod}"
    except Exception as e:
        return f"?({e})"


def poly_vertices(ent: Any, tx: Any) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    if isinstance(ent, Polyline):
        for i in range(ent.NumberOfVertices):
            p = ent.GetPoint3dAt(i)
            out.append((float(p.X), float(p.Y)))
    elif isinstance(ent, Polyline3d):
        for vid in ent:
            try:
                p = tx.GetObject(vid, OpenMode.ForRead).Position
                out.append((float(p.X), float(p.Y)))
            except Exception:
                continue
    elif isinstance(ent, Polyline2d):
        for vid in ent:
            try:
                p = tx.GetObject(vid, OpenMode.ForRead).Position
                out.append((float(p.X), float(p.Y)))
            except Exception:
                continue
    return out


def pt_seg_dist(p, a, b) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 < 1e-12:
        return math.hypot(p[0] - ax, p[1] - ay)
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
    return math.hypot(p[0] - (ax + dx * t), p[1] - (ay + dy * t))


def pt_poly_dist(p, verts, closed: bool) -> float:
    n = len(verts)
    if n < 2:
        return float("inf")
    best = float("inf")
    segs = n if closed else n - 1
    for k in range(segs):
        d = pt_seg_dist(p, verts[k], verts[(k + 1) % n])
        if d < best:
            best = d
    return best


def _min_poly_dist(p, rails: list[dict]) -> float:
    best = float("inf")
    for r in rails:
        d = pt_poly_dist(p, r["verts"], r["closed"])
        if d < best:
            best = d
    return best


def main(tx: Any, db: Any) -> None:
    ms = tx.GetObject(SymbolUtilityServices.GetBlockModelSpaceId(db), OpenMode.ForRead)

    # ── pass 1: the two reference rails: yellow ACI=2 (inner) + purple ACI=6 ──
    # (magenta = фиолетовый). Both closed, lineweight 0.50. Ignore every other
    # lineweight-0.50 polyline in the drawing.
    yellows: list[dict] = []
    purples: list[dict] = []
    for oid in ms:
        try:
            ent = tx.GetObject(oid, OpenMode.ForRead)
        except Exception:
            continue
        if not isinstance(ent, (Polyline, Polyline2d, Polyline3d)):
            continue
        try:
            if int(ent.LineWeight) != LW_050:
                continue
        except Exception:
            continue
        cd = color_desc(ent)
        rec = {
            "verts": poly_vertices(ent, tx),
            "closed": bool(getattr(ent, "Closed", False)),
        }
        if cd == "ACI=2":
            yellows.append(rec)
        elif cd == "ACI=6":
            purples.append(rec)

    log("=== REFERENCE RAILS ===")
    log(f"yellow (inner, ACI=2): {len(yellows)}  purple (outer, ACI=6): {len(purples)}")
    for r in yellows:
        log(f"  yellow nverts={len(r['verts'])} closed={r['closed']}")
    for r in purples:
        log(f"  purple nverts={len(r['verts'])} closed={r['closed']}")

    # perpendicular gap between the rails: dist from each yellow vertex to purple
    if yellows and purples:
        gaps = [_min_poly_dist(v, purples) for r in yellows for v in r["verts"]]
        gaps.sort()
        log(
            f"rail gap yellow→purple: min={gaps[0]:.3f} "
            f"median={gaps[len(gaps) // 2]:.3f} max={gaps[-1]:.3f} (m)"
        )

    # ── pass 2: point_number callouts, keep only the BOTTOM set (near a rail) ──
    rows: list[tuple] = []
    for oid in ms:
        try:
            o = tx.GetObject(oid, OpenMode.ForRead)
        except Exception:
            continue
        if (
            not isinstance(o, BlockReference)
            or eff_name(o, tx).lower() != "point_number"
        ):
            continue
        if o.Layer == "0":
            continue  # the manual source template
        ins = o.Position
        flip = pos1x = pos1y = None
        try:
            for p in o.DynamicBlockReferencePropertyCollection:
                nm = p.PropertyName
                if nm == "Отраженное состояние1":
                    flip = float(p.Value)
                elif nm == "Положение1 X":
                    pos1x = float(p.Value)
                elif nm == "Положение1 Y":
                    pos1y = float(p.Value)
        except Exception:
            pass
        text = ""
        try:
            for aoid in o.AttributeCollection:
                a = tx.GetObject(aoid, OpenMode.ForRead)
                if isinstance(a, AttributeReference):
                    text = a.TextString
                    break
        except Exception:
            pass
        if None in (flip, pos1x, pos1y):
            continue
        red = (
            ins.X + pos1x + (1.0 - 2.0 * flip) * POLKA_LEN,
            ins.Y + pos1y,
        )
        d_in = _min_poly_dist(red, yellows) if yellows else float("inf")
        d_out = _min_poly_dist(red, purples) if purples else float("inf")
        if min(d_in, d_out) > 4.0:
            continue  # верх (top) callout — far from the bottom rails; skip
        rows.append((text, ins.X, ins.Y, flip, red, d_in, d_out))

    def keyf(r):
        try:
            return (0, int(r[0].replace("т.", "").strip()))
        except Exception:
            return (1, 0)

    rows.sort(key=keyf)
    n_in = sum(1 for r in rows if r[5] <= r[6])
    log(
        f"\n=== BOTTOM CALLOUTS (near a rail) : {len(rows)} "
        f"({n_in} inner, {len(rows) - n_in} outer) ==="
    )
    for text, ix, iy, flip, red, d_in, d_out in rows:
        near = "INNER/yellow" if d_in <= d_out else "OUTER/purple"
        # straight-line ins→red offset (rough perpendicular from contour)
        off = math.hypot(red[0] - ix, red[1] - iy)
        log(
            f"{text:>6} flip={int(flip)} ins=({ix:.2f},{iy:.2f}) "
            f"red=({red[0]:.2f},{red[1]:.2f}) off={off:.2f}  "
            f"d_in={d_in:.2f} d_out={d_out:.2f} -> {near}"
        )


doc = Application.DocumentManager.MdiActiveDocument
db = doc.Database
lock = doc.LockDocument()
try:
    tx = db.TransactionManager.StartTransaction()
    try:
        log("=== DUMP EXCAVATION CALLOUT LAYOUT ===")
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

OUT = LOG
