from __future__ import annotations

import datetime
import glob
import os
import traceback
from typing import Any

from Autodesk.AutoCAD.ApplicationServices import Application

from help_layers_from_json.layers import ensure_filter, ensure_layers, load_spec

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
_LOG_PREFIX = "layers"


def _trim_logs(log_dir: str, prefix: str, keep: int = 10) -> None:
    for f in sorted(glob.glob(os.path.join(log_dir, f"{prefix}_*.log")))[:-keep]:
        try:
            os.remove(f)
        except OSError:
            pass


class LayerSetupBuilder:
    """Read the folder's layers.json and create its layers + one property filter group.

    Layers are style-enforced every run (JSON is the single source of truth); the filter
    groups them in the Layer Manager. Both steps are idempotent -- re-running is safe.
    """

    def __init__(self) -> None:
        os.makedirs(_LOG_DIR, exist_ok=True)
        _trim_logs(_LOG_DIR, _LOG_PREFIX)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self._log_path = os.path.join(_LOG_DIR, f"{_LOG_PREFIX}_{ts}.log")

    def _log(self, msg: str, level: str = "INFO") -> None:
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [{level}] {msg}\n")

    def run(self) -> Any:
        log = self._log
        log("=== SCRIPT STARTED ===")

        created: list[str] = []
        updated: list[str] = []
        errors: list[str] = []
        filter_name = ""

        doc = Application.DocumentManager.MdiActiveDocument
        db = doc.Database

        try:
            spec = load_spec()
            log(f"spec loaded: {len(spec.get('layers', {}))} layers")

            lock = doc.LockDocument()
            try:
                tx = db.TransactionManager.StartTransaction()
                try:
                    created, updated = ensure_layers(db, tx, spec)
                    tx.Commit()
                    log(f"committed: created={len(created)}, updated={len(updated)}")
                    for name in created:
                        log(f"created: {name}")
                    for name in updated:
                        log(f"updated: {name}")
                except Exception:
                    tx.Abort()
                    raise
                finally:
                    tx.Dispose()

                # filters must be set inside the document lock but outside any transaction
                try:
                    filter_name = ensure_filter(db, spec)
                    log(f"filter ensured: {filter_name!r}")
                except Exception as e:
                    log(f"layer filter warning: {e}", "WARN")
            finally:
                lock.Dispose()

        except Exception as ex:
            errors.append(str(ex))
            log(f"ERROR: {ex}", "CRITICAL")
            log(traceback.format_exc(), "CRITICAL")

        log(
            f"=== DONE: created={len(created)}, updated={len(updated)}, "
            f"filter={filter_name!r}, errors={len(errors)} ==="
        )
        if errors:
            return errors
        return {"created": created, "updated": updated, "filter": filter_name}
