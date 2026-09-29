import datetime
import glob
import os
import traceback

from Autodesk.AutoCAD.ApplicationServices import Application
from Autodesk.AutoCAD.DatabaseServices import OpenMode

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
_LOG_PREFIX = "clear_inf"


def _trim_logs(log_dir, prefix, keep=10):
    for f in sorted(glob.glob(os.path.join(log_dir, f"{prefix}_*.log")))[:-keep]:
        try:
            os.remove(f)
        except OSError:
            pass


class ClearInfBuilder:
    def __init__(self, prefix="inf"):
        self.prefix = prefix.strip() if prefix else "inf"
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
        log(f"=== SCRIPT STARTED: prefix='{self.prefix}' ===")

        deleted = 0
        errors = []

        doc = Application.DocumentManager.MdiActiveDocument
        db = doc.Database

        try:
            lock = doc.LockDocument()
            try:
                tx = db.TransactionManager.StartTransaction()
                try:
                    ms = tx.GetObject(db.CurrentSpaceId, OpenMode.ForWrite)
                    ids_to_erase = []

                    for oid in ms:
                        try:
                            obj = tx.GetObject(oid, OpenMode.ForRead)
                            layer = obj.Layer
                            if layer and layer.startswith(self.prefix):
                                ids_to_erase.append(oid)
                        except Exception as e:
                            errors.append(f"read {oid}: {e}")

                    log(f"found {len(ids_to_erase)} objects on '{self.prefix}*' layers")

                    for oid in ids_to_erase:
                        try:
                            obj = tx.GetObject(oid, OpenMode.ForWrite)
                            obj.Erase()
                            deleted += 1
                        except Exception as e:
                            err = f"erase {oid}: {e}"
                            errors.append(err)
                            log(err, "ERROR")

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

        log(f"=== DONE: deleted={deleted}, errors={len(errors)} ===")
        return f"deleted {deleted} objects" if not errors else errors
