import datetime
import glob
import json
import math
import os
import traceback
import unicodedata

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import OpenMode
from Autodesk.Civil.ApplicationServices import CivilApplication
from Autodesk.Civil.DatabaseServices import Profile

from paths import ALIGNMENT_REPORT_DIR as _OUT_DIR

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
_LOG_PREFIX = "alignment_report"


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s).strip()


def _trim_logs(log_dir, prefix, keep=10):
    for f in sorted(glob.glob(os.path.join(log_dir, f"{prefix}_*.log")))[:-keep]:
        try:
            os.remove(f)
        except OSError:
            pass


def _get_xy_angle(align, sta, sta_end, delta=0.3):
    s0 = max(float(align.StartingStation), sta - delta)
    s1 = min(sta_end, sta + delta)
    ac0 = align.GetPointAtDist(s0)
    ac1 = align.GetPointAtDist(s1)
    return math.atan2(float(ac1.Y) - float(ac0.Y), float(ac1.X) - float(ac0.X))


class AlignmentReportBuilder:
    def __init__(self):
        os.makedirs(_LOG_DIR, exist_ok=True)
        _trim_logs(_LOG_DIR, _LOG_PREFIX)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self._log_path = os.path.join(_LOG_DIR, f"{_LOG_PREFIX}_{ts}.log")
        os.makedirs(_OUT_DIR, exist_ok=True)

    def _log(self, msg, level="INFO"):
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [{level}] {msg}\n")

    def run(self):
        log = self._log
        log("=== SCRIPT STARTED ===")

        results = []
        errors = []

        doc = Application.DocumentManager.MdiActiveDocument
        db = doc.Database
        civil_db = CivilApplication.ActiveDocument

        try:
            lock = doc.LockDocument()
            try:
                tx = db.TransactionManager.StartTransaction()
                try:
                    align_objects = []
                    for oid in civil_db.GetAlignmentIds():
                        try:
                            align_objects.append(tx.GetObject(oid, OpenMode.ForRead))
                        except Exception:
                            continue
                    log(f"alignments found: {len(align_objects)}")

                    for align in align_objects:
                        try:
                            data = self._process_alignment(align, tx)
                            safe_name = align.Name.replace("/", "_").replace("\\", "_")
                            out_path = os.path.join(_OUT_DIR, f"{safe_name}.json")
                            with open(out_path, "w", encoding="utf-8") as f:
                                json.dump(data, f, ensure_ascii=False, indent=2)
                            results.append(f"OK  {align.Name}  -> {out_path}")
                            log(f"OK: {align.Name}")
                        except Exception as e:
                            msg = f"ERR {align.Name}: {e}"
                            errors.append(msg)
                            results.append(msg)
                            log(msg, "ERROR")

                    tx.Commit()
                except Exception:
                    tx.Abort()
                    raise
                finally:
                    tx.Dispose()
            finally:
                lock.Dispose()

        except Exception as ex:
            errors.append(f"FATAL: {ex}")
            log(f"FATAL: {ex}", "CRITICAL")
            log(traceback.format_exc(), "CRITICAL")

        summary = f"Done: {len(results) - len(errors)} OK, {len(errors)} errors"
        results.append(summary)
        log(f"=== {summary} ===")
        return results

    def _process_alignment(self, align, tx):
        sta_start = float(align.StartingStation)
        sta_end = float(align.EndingStation)

        data = {
            "name": align.Name,
            "station_start": round(sta_start, 3),
            "station_end": round(sta_end, 3),
            "length": round(sta_end - sta_start, 3),
            "plan_turns": [],
            "profiles": [],
        }

        try:
            ents = align.Entities
            pi_stas = []
            for i in range(ents.Count):
                try:
                    s = float(ents[i].StartStation)
                    if sta_start + 0.01 < s < sta_end - 0.01:
                        pi_stas.append(s)
                except Exception:
                    continue

            for sta in sorted(pi_stas):
                ang_in = _get_xy_angle(align, sta - 0.5, sta_end)
                ang_out = _get_xy_angle(align, sta + 0.5, sta_end)
                defl = ang_out - ang_in
                while defl > math.pi:
                    defl -= 2 * math.pi
                while defl < -math.pi:
                    defl += 2 * math.pi
                defl_deg = math.degrees(defl)
                data["plan_turns"].append(
                    {
                        "station": round(sta, 3),
                        "deflection_deg": round(abs(defl_deg), 3),
                        "direction": "left" if defl_deg > 0 else "right",
                        "azimuth_in": round((90 - math.degrees(ang_in)) % 360, 3),
                        "azimuth_out": round((90 - math.degrees(ang_out)) % 360, 3),
                    }
                )
        except Exception as e:
            data["plan_turns_error"] = str(e)

        for pid in align.GetProfileIds():
            try:
                prof = tx.GetObject(pid, OpenMode.ForRead)
                if not isinstance(prof, Profile):
                    continue
                if _norm(prof.Name) != _norm(align.Name):
                    continue
            except Exception:
                continue

            prof_data = {"name": prof.Name, "pvis": []}

            try:
                pvis = []
                for pvi in prof.PVIs:
                    try:
                        pvis.append((float(pvi.Station), float(pvi.Elevation), pvi))
                    except Exception:
                        pass
                pvis.sort(key=lambda x: x[0])

                for idx in range(len(pvis)):
                    sta, elev, pvi_obj = pvis[idx]

                    g_in = None
                    if idx > 0:
                        prev_sta, prev_elev, _ = pvis[idx - 1]
                        ds = sta - prev_sta
                        if ds > 1e-9:
                            g_in = round((elev - prev_elev) / ds * 1000, 4)

                    g_out = None
                    if idx < len(pvis) - 1:
                        nxt_sta, nxt_elev, _ = pvis[idx + 1]
                        ds = nxt_sta - sta
                        if ds > 1e-9:
                            g_out = round((nxt_elev - elev) / ds * 1000, 4)

                    if g_in is not None and g_out is not None:
                        diff = g_out - g_in
                        if abs(diff) < 0.01:
                            ptype = "straight"
                        elif diff > 0:
                            ptype = "sag"
                        else:
                            ptype = "crest"
                    else:
                        ptype = None

                    prof_data["pvis"].append(
                        {
                            "station": round(sta, 3),
                            "elevation": round(elev, 3),
                            "grade_in_ppm": g_in,
                            "grade_out_ppm": g_out,
                            "type": ptype,
                        }
                    )
            except Exception as e:
                prof_data["pvis_error"] = str(e)

            data["profiles"].append(prof_data)

        return data
