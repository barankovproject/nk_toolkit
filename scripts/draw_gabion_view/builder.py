import datetime
import glob
import json
import math
import os
import traceback

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import (
    BlockReference,
    OpenMode,
    Polyline,
    RegAppTable,
    RegAppTableRecord,
    ResultBuffer,
    TypedValue,
)
from Autodesk.AutoCAD.Geometry import Point2d, Point3d
from Autodesk.Civil.ApplicationServices import CivilApplication
from Autodesk.Civil.DatabaseServices import Profile

from .blocks import BlockManager
from .layout import ShelfCfg, plan_shelves, _spread_var
from .config import (
    DATA_DIR,
    DRAWING,
    LAYOUT,
    TYPES_FILE,
    find_best_match,
    load_canal_config,
    normalize,
    section_params_at,
)
from .geometry import get_xy, get_xy_angle, section_pts

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
_LOG_PREFIX = "gabion_view"

# Clones placed by this script carry this RegApp XData tag (code 1001) so a re-run
# erases only its own output; the user's source template blocks stay untagged.
_REGAPP = "ARHYZ_GABION_VIEW"


def _profile_elev(profile, sta):
    """profile.ElevationAt that clamps `sta` into the profile's own station range.

    Some profiles do not span the whole alignment (e.g. НК-3С-1), and ElevationAt raises
    'value out of range' outside their domain. bz is only a datum and section elevations
    are continuous, so clamping to the nearest valid station is safe.
    """
    try:
        return float(profile.ElevationAt(sta))
    except Exception:
        lo = float(profile.StartingStation)
        hi = float(profile.EndingStation)
        return float(profile.ElevationAt(min(max(sta, lo + 1e-3), hi - 1e-3)))


def _decimate(pts: list, tol: float = 0.01) -> list:
    """Drop vertices closer than `tol` to the chord last-kept -> next (collinear runs)."""
    out = [pts[0]]
    for k in range(1, len(pts) - 1):
        ax, ay = out[-1]
        bx, by = pts[k]
        cx, cy = pts[k + 1]
        dx, dy = cx - ax, cy - ay
        m = math.hypot(dx, dy) or 1.0
        if abs((bx - ax) * dy - (by - ay) * dx) / m > tol:
            out.append(pts[k])
    out.append(pts[-1])
    return out


def _trim_logs(log_dir, prefix, keep=10):
    for f in sorted(glob.glob(os.path.join(log_dir, f"{prefix}_*.log")))[:-keep]:
        try:
            os.remove(f)
        except OSError:
            pass


class GabionViewBuilder:
    def __init__(self, query):
        self.query = query.strip()
        os.makedirs(_LOG_DIR, exist_ok=True)
        _trim_logs(_LOG_DIR, _LOG_PREFIX)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self._log_path = os.path.join(_LOG_DIR, f"{_LOG_PREFIX}_{ts}.log")

    def _log(self, msg, level="INFO"):
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [{level}] {msg}\n")

    def run(self):
        log = self._log
        log("=== SCRIPT STARTED ===")
        log(f"query='{self.query}'")

        errors = []
        added = 0

        try:
            with open(TYPES_FILE, encoding="utf-8") as f:
                cfg_types = json.load(f)["types"]

            canal_cfg = load_canal_config(self.query)
            segments = canal_cfg["segments"]
            widening = canal_cfg.get("widening")
            log(f"canal config loaded: {len(segments)} segments")

            canal_data = self._load_canal_data()
            json_spts = canal_data.get("section_points", {})
            section_stas = sorted(float(k) for k in json_spts)
            callout_stas = self._resolve_callout_stations(canal_data, json_spts)
            izlom_set = [float(s) for s in canal_data.get("pvi_stations", [])]
            izlom_set += [float(p["station"]) for p in canal_data.get("plan_pis", [])]
            log(
                f"section points: {len(json_spts)}, callout stations: {len(callout_stas)}"
            )

            doc = Application.DocumentManager.MdiActiveDocument
            db = doc.Database
            civil_db = CivilApplication.ActiveDocument

            lock = doc.LockDocument()
            try:
                tx = db.TransactionManager.StartTransaction()
                try:
                    align, align_name = self._find_alignment(tx, civil_db)
                    profile, profile_name = self._find_profile(tx, align)
                    log(f"alignment: '{align_name}'  profile: '{profile_name}'")

                    sta_start = float(align.StartingStation)
                    sta_end = float(align.EndingStation)

                    bx, by = get_xy(align, sta_start)
                    bz = _profile_elev(profile, sta_start)

                    ms = tx.GetObject(db.CurrentSpaceId, OpenMode.ForWrite)

                    # idempotent re-run: drop this script's previous output first, so the
                    # only blocks left are the user's untagged source templates.
                    self._ensure_regapp(db, tx)
                    purged = self._purge(ms, tx, align_name)
                    log(f"purged {purged} blocks from a previous run")

                    source_br_oid = self._find_block(tx, ms, DRAWING.block_name)
                    source_gnum_oid = self._find_block(
                        tx, ms, DRAWING.gnum_block, required=False
                    )
                    if source_gnum_oid is None:
                        log(
                            f"'{DRAWING.gnum_block}' block not found — skipping GSI numbering",
                            "WARN",
                        )

                    bm = BlockManager(
                        tx,
                        ms,
                        db,
                        source_br_oid,
                        source_gnum_oid,
                        errors,
                        _REGAPP,
                        align_name,
                    )

                    # section context: align, profile, bx, by, bz, segments, cfg_types, sta_end, widening
                    sctx = (
                        align,
                        profile,
                        bx,
                        by,
                        bz,
                        segments,
                        cfg_types,
                        sta_end,
                        widening,
                    )

                    try:
                        placements = self._rail_placements(
                            callout_stas, json_spts, sctx
                        )
                        log("placement: offset-rail")
                    except Exception as e:
                        log(f"rail placement failed ({e}) — fallback to fan", "WARN")
                        placements = self._label_params(
                            callout_stas, izlom_set, json_spts, sctx
                        )
                    n, errs = self._draw(callout_stas, placements, json_spts, sctx, bm)
                    added += n
                    errors.extend(errs)

                    if source_gnum_oid is not None:
                        gsi_n = self._draw_gsi(section_stas, sctx, bm)
                        added += gsi_n
                        log(f"gsi numbers added: {gsi_n}")

                    log(f"objects added: {added}")
                    tx.Commit()
                except Exception:
                    tx.Abort()
                    raise
                finally:
                    tx.Dispose()
            finally:
                lock.Dispose()

        except Exception as ex:
            errors.insert(0, f"ERROR: {ex}")
            log(f"ERROR: {ex}", "CRITICAL")
            log(traceback.format_exc(), "CRITICAL")

        for e in errors:
            log(e, "ERROR")
        log(f"=== DONE: added={added}, errors={len(errors)} ===")
        return added if not errors else errors

    def _load_canal_data(self):
        data_path = os.path.join(DATA_DIR, f"{self.query}.json")
        if not os.path.exists(data_path):
            norm_q = normalize(self.query)
            if os.path.isdir(DATA_DIR):
                for fname in os.listdir(DATA_DIR):
                    if normalize(fname[:-5]) == norm_q and fname.endswith(".json"):
                        data_path = os.path.join(DATA_DIR, fname)
                        break
        if os.path.exists(data_path):
            with open(data_path, encoding="utf-8") as f:
                return json.load(f)
        self._log(f"no canal data JSON at {data_path}", "WARN")
        return {}

    def _resolve_callout_stations(self, canal_data, json_spts):
        """Callout stations (изломы + доборные) straight from build_canal_model.

        Falls back to PVI + plan-PI stations snapped to the nearest section key when
        the JSON predates the callout_stations field — run build_canal_model to
        regenerate for the correct dobornie boundaries.
        """
        cs = canal_data.get("callout_stations")
        if cs:
            return sorted(float(s) for s in cs)
        self._log(
            "no 'callout_stations' in JSON — regenerate via build_canal_model; "
            "falling back to PVI+PI snapped to section keys",
            "WARN",
        )
        keys = sorted(float(k) for k in json_spts)
        if not keys:
            return []
        breaks = [float(s) for s in canal_data.get("pvi_stations", [])]
        breaks += [float(p["station"]) for p in canal_data.get("plan_pis", [])]
        snapped = {min(keys, key=lambda k: abs(k - b)) for b in breaks}
        return sorted(snapped)

    def _find_alignment(self, tx, civil_db):
        objs = []
        for oid in civil_db.GetAlignmentIds():
            try:
                objs.append(tx.GetObject(oid, OpenMode.ForRead))
            except Exception:
                continue
        names = [a.Name for a in objs]
        result = find_best_match(self.query, names)
        if result is None:
            raise Exception(f"No alignment matching '{self.query}'. Available: {names}")
        return objs[result[0]], result[1]

    def _find_profile(self, tx, align):
        objs = []
        for pid in align.GetProfileIds():
            try:
                p = tx.GetObject(pid, OpenMode.ForRead)
                if isinstance(p, Profile):
                    objs.append(p)
            except Exception:
                continue
        names = [p.Name for p in objs]
        result = find_best_match(self.query, names)
        if result is None:
            raise Exception(f"No profile matching '{self.query}'. Profiles: {names}")
        return objs[result[0]], result[1]

    def _ensure_regapp(self, db, tx):
        rat = tx.GetObject(db.RegAppTableId, OpenMode.ForRead)
        if not rat.Has(_REGAPP):
            rat.UpgradeOpen()
            ratr = RegAppTableRecord()
            ratr.Name = _REGAPP
            rat.Add(ratr)
            tx.AddNewlyCreatedDBObject(ratr, True)

    def _purge(self, ms, tx, scope):
        """Erase only this script's clones FOR THIS CANAL — tagged with _REGAPP and a
        code-1000 value == scope (the canal name). Other canals' callouts are left alone."""
        to_erase = []
        for oid in ms:
            try:
                ent = tx.GetObject(oid, OpenMode.ForRead)
                rb = ent.GetXDataForApplication(_REGAPP)
                if rb is None:
                    continue
                nm = next((str(tv.Value) for tv in rb if tv.TypeCode == 1000), None)
                if nm == scope:
                    to_erase.append(oid)
            except Exception:
                continue
        for oid in to_erase:
            try:
                tx.GetObject(oid, OpenMode.ForWrite).Erase()
            except Exception:
                continue
        return len(to_erase)

    def _find_block(self, tx, ms, block_name, required=True):
        for oid in ms:
            try:
                obj = tx.GetObject(oid, OpenMode.ForRead)
                if isinstance(obj, BlockReference):
                    btr = tx.GetObject(obj.BlockTableRecord, OpenMode.ForRead)
                    if btr.Name == block_name:
                        return oid
            except Exception:
                continue
        if required:
            raise Exception(
                f"no '{block_name}' block in model space — insert one manually first"
            )
        return None

    def _section_pts(self, sta, sctx):
        align, profile, bx, by, bz, segments, cfg_types, sta_end, widening = sctx
        x, y = get_xy(align, sta)
        ang = get_xy_angle(align, sta, sta_end)
        rx, ry = -math.sin(ang), math.cos(ang)
        elev = _profile_elev(profile, sta) - bz
        bw, d, m_s, t = section_params_at(sta, segments, cfg_types, sta_end, widening)
        return section_pts(x - bx, y - by, elev, rx, ry, bx, by, bz, bw, d, m_s, t)

    def _pts_for_block(self, sta, json_spts, sctx):
        key = f"{sta:.3f}"
        if key in json_spts:
            raw = json_spts[key]
            return [Point3d(p[0], p[1], p[2]) for p in raw]
        return self._section_pts(sta, sctx)

    def _label_params(self, callout_stas, izlom_set, json_spts, sctx):
        """Thin wrapper over layout.plan_shelves (the pure, tested placement core).

        Builds a station record per callout (top-of-wall corners idx 7/6, axis X,
        gabion world-X extent each side, излом flag) and returns plan_shelves'
        per-station list of placed callouts (point_idx, flip, pos1x, pos1y).
        """

        def is_izlom(sta):
            return any(abs(sta - z) < 0.12 for z in izlom_set)

        stations = []
        for sta in callout_stas:
            bpts = self._pts_for_block(sta, json_spts, sctx)
            p6_pt, p5_pt = (
                bpts[7],
                bpts[6],
            )  # idx 7 = P6 (-u side), idx 6 = P5 (+u side)
            ax = (p6_pt.X + p5_pt.X) / 2.0
            ay = (p6_pt.Y + p5_pt.Y) / 2.0
            dx, dy = p5_pt.X - p6_pt.X, p5_pt.Y - p6_pt.Y
            mag = math.hypot(dx, dy) or 1.0
            ux, uy = dx / mag, dy / mag  # transverse unit, P6 -> P5
            proj = [(p.X - ax) * ux + (p.Y - ay) * uy for p in bpts]  # corners along u
            stations.append(
                {
                    "p7": (p6_pt.X, p6_pt.Y),
                    "p6": (p5_pt.X, p5_pt.Y),
                    "u": (ux, uy),
                    "a": (ax, ay),
                    "ext_plus": max(proj),
                    "ext_minus": max(-q for q in proj),
                    "t": float(sta),
                    "izlom": is_izlom(sta),
                }
            )
        cfg = ShelfCfg(
            w=LAYOUT.shelf_w,
            h=LAYOUT.shelf_h,
            gap=LAYOUT.gap,
            fan_gap=LAYOUT.fan_gap,
            drop_pos1y=LAYOUT.drop_pos1y,
        )
        return plan_shelves(stations, cfg)

    def _rail_placements(self, callout_stas, json_spts, sctx):
        """Offset-rail ("паучок") placement. The shelf-starts sit on the rounded OFFSET of
        the canal outline (built by AutoCAD OFFSET, OFFSETGAPTYPE=1). Sides ride the rail in
        station order (sequential, nothing flies off); the two end-section corners anchor at
        the START OF THE CAP ROUNDING — the tangent points where the cap's end straight
        meets the corner fillet arcs. Returns the same per-station list as _label_params.
        """
        keys = sorted(json_spts, key=lambda k: float(k))
        if len(keys) < 2:
            return [[] for _ in callout_stas]
        loop = [(json_spts[k][8][0], json_spts[k][8][1]) for k in keys]
        loop += [(json_spts[k][5][0], json_spts[k][5][1]) for k in reversed(keys)]
        # The fillet-gap offset (OFFSETGAPTYPE=1) returns NOTHING for a dense outline
        # (НК-1А-3: 322 verts from 161 sections, fails at any distance — arc insertion
        # chokes on nearly-collinear vertices), so drop vertices within 1 cm of the
        # running chord first. The rail is a coarse guide: 1 cm is invisible at
        # rail_offset scale, and section corners (real direction changes) all survive.
        loop = _decimate(loop)
        Application.SetSystemVariable("OFFSETGAPTYPE", 1)
        outline = Polyline()
        outline.SetDatabaseDefaults()
        for i, (x, y) in enumerate(loop):
            outline.AddVertexAt(i, Point2d(x, y), 0.0, 0.0, 0.0)
        outline.Closed = True

        def _area(c):
            try:
                return abs(float(c.Area))
            except Exception:
                return 0.0

        base = _area(outline)
        rail, ra = None, -1.0
        for dist in (LAYOUT.rail_offset, -LAYOUT.rail_offset):  # outward = area grows
            try:
                for c in outline.GetOffsetCurves(dist):
                    a = _area(c)
                    if a > base and a > ra:
                        rail, ra = c, a
            except Exception:
                pass
        outline.Dispose()
        if rail is None:
            raise Exception("rail offset produced nothing")
        total = float(rail.GetDistanceAtParameter(rail.EndParam))

        def foot(p):
            return rail.GetDistAtPoint(
                rail.GetClosestPointTo(Point3d(p[0], p[1], 0.0), False)
            )

        bpts_by = {
            sta: self._pts_for_block(sta, json_spts, sctx) for sta in callout_stas
        }
        first_sta, last_sta = callout_stas[0], callout_stas[-1]

        # End-section corner shelf-starts anchor at the START OF THE CAP ROUNDING (user
        # convention «торцы в начало скруглений»): the fillet arc of an outline corner is
        # centred at the corner with R = rail_offset, so its cap-side end — where the cap's
        # end straight begins — is corner (idx 8/5) + rail_offset * outward axis direction.
        # Only when the first/last callout station IS the outline end section.
        def _mid(key):
            lc, rc = json_spts[key][8], json_spts[key][5]
            return ((lc[0] + rc[0]) / 2.0, (lc[1] + rc[1]) / 2.0)

        anchors = {}  # (sta, idx) -> shelf-start target xy (a tangent point on the rail)
        for sta, k_end, k_prev in (
            (first_sta, keys[0], keys[1]),
            (last_sta, keys[-1], keys[-2]),
        ):
            if abs(sta - float(k_end)) > 0.01:
                continue
            (ex, ey), (px, py) = _mid(k_end), _mid(k_prev)
            fx, fy = ex - px, ey - py
            mg = math.hypot(fx, fy) or 1.0
            fx, fy = fx / mg, fy / mg
            for idx, li in ((7, 8), (6, 5)):
                c = json_spts[k_end][li]
                anchors[(sta, idx)] = (
                    c[0] + LAYOUT.rail_offset * fx,
                    c[1] + LAYOUT.rail_offset * fy,
                )

        def anchor(it):
            return anchors.get((it["sta"], it["idx"])) or (it["pt"].X, it["pt"].Y)

        # INTRINSIC loop order around the capsule: left side (P6, station ascending) then
        # right side (P5, station descending). This — NOT a sort by projection distance — is
        # what keeps each point on its own side (a point whose nearest rail spot lands on the
        # wrong arc near a cap won't jump out of order).
        seq = [{"sta": s, "idx": 7, "pt": bpts_by[s][7]} for s in callout_stas]
        seq += [
            {"sta": s, "idx": 6, "pt": bpts_by[s][6]} for s in reversed(callout_stas)
        ]
        m = len(seq)

        # Rotate so the unwrap seam (the chain's two ends) sits on the LARGEST rail gap
        # between same-side neighbours. The spread below is linear: there is no gap
        # constraint across the seam, so if it lands between two crowded points they get
        # pushed *through* each other — inverted shelves / crossed leaders (т.33/т.35 on
        # НК-1A-6, callouts 0.73 m apart exactly at the old mid-left seam). Same-side
        # pairs only (same idx) — caps stay interior so corner anchors are constrained.
        feet = [foot(anchor(it)) for it in seq]
        r, widest = len(callout_stas) // 2, -1.0
        for i in range(m):
            if seq[i - 1]["idx"] != seq[i]["idx"]:
                continue
            d = (feet[i] - feet[i - 1]) % total
            d = min(d, total - d)
            if d > widest:
                r, widest = i, d
        order = seq[r:] + seq[:r]

        def unwrap(items):
            ds = [foot(anchor(it)) for it in items]
            out = [ds[0]]
            for v in ds[1:]:
                while v < out[-1] - total / 2.0:
                    v += total
                while v > out[-1] + total / 2.0:
                    v -= total
                out.append(v)
            return out

        unw = unwrap(order)
        if unw[-1] < unw[0]:  # rail parameter runs opposite the loop order → flip
            order = order[::-1]
            unw = unwrap(order)

        # ONE monotone spread around the whole loop ⇒ strictly sequential, so leaders can
        # never invert / cross. The corner anchors already sit at the cap tangent points,
        # so every pair keeps the plain rail_gap (the spread only nudges a corner off its
        # tangent when a side neighbour actually crowds it).
        gaps = [LAYOUT.rail_gap] * (m - 1)
        fanned = _spread_var(unw, gaps)
        seam_clear = total - (fanned[-1] - fanned[0])
        if seam_clear < LAYOUT.rail_gap:
            self._log(
                f"rail seam clearance {seam_clear:.2f} < rail_gap "
                f"{LAYOUT.rail_gap} — chain ends may cross",
                "WARN",
            )
        shelf = {
            (it["sta"], it["idx"]): rail.GetPointAtDist(d % total)
            for it, d in zip(order, fanned)
        }

        out = []
        for sta in callout_stas:
            here = []
            for idx in (7, 6):
                if (sta, idx) in shelf:
                    sp = shelf[
                        (sta, idx)
                    ]  # the RED point (polka↔leader junction) on the rail
                    pt = bpts_by[sta][idx]
                    dx, dy = (
                        sp.X - pt.X,
                        sp.Y - pt.Y,
                    )  # red point relative to the section point
                    # flip = which horizontal side the red point sits; the polka (text) then
                    # extends away from it. The grip (Положение1) is polka_len beyond the red
                    # point along world X (mirrored by flip), so back it out to put the RED
                    # point — not the grip — on the rail. This also makes |pos1x| >= polka_len
                    # ⇒ a stable flip (matches the эталон).
                    flip = 1.0 if dx >= 0 else 0.0
                    p1x = dx - (1.0 - 2.0 * flip) * LAYOUT.polka_len
                    here.append((idx, flip, p1x, dy))
            out.append(here)
        rail.Dispose()
        return out

    def _draw(self, callout_stas, placements, json_spts, sctx, bm):
        added = 0
        errors = []
        num = 0  # running point label, sequential along the whole canal
        for sta, placed in zip(callout_stas, placements):
            if not placed:
                continue
            bpts = self._pts_for_block(sta, json_spts, sctx)
            for idx, flip, p1x, p1y in placed:
                num += 1
                bm.add_block_ref(bpts[idx], flip, p1x, p1y, "inf_model_heigh", num)
                added += 1
        return added, errors

    def _draw_gsi(self, all_stations, sctx, bm):
        align, _, _, _, _, _, _, sta_end, _ = sctx
        count = 0
        for i in range(len(all_stations) - 1):
            sta_mid = (all_stations[i] + all_stations[i + 1]) / 2.0
            mid_pts = self._section_pts(sta_mid, sctx)
            ang = get_xy_angle(align, sta_mid, sta_end)
            bm.add_gnum_ref(mid_pts[2], ang, 1, "inf_model_text")
            count += 1
        return count
