from __future__ import annotations

from typing import Any, Callable, Optional

from Autodesk.AutoCAD.DatabaseServices import Circle, OpenMode

# Reuse the cross-ditch alignment/surface lookup verbatim — same drawing, same
# fuzzy-match-by-name behaviour. Imported, not duplicated.
from ditch_core.selection import find_alignment_and_surface  # noqa: F401


def _project_station(align: Any, x: float, y: float) -> Optional[float]:
    """Project (x, y) onto the alignment, return its station (offset ignored).

    Uses StationOffsetAcceptOutOfRange so a marker that is not exactly on the
    axis — or slightly past an end — still yields a station instead of throwing
    (plain StationOffset raises eInvalidInput for off-line points). pythonnet
    returns the ref params appended to the tuple, so we pass seed values and read
    from the tail: (..., station, offset, outofrange). Falls back to StationOffset
    with the same tail convention if the AcceptOutOfRange overload is unavailable.
    """
    try:
        res = align.StationOffsetAcceptOutOfRange(x, y, 0.0, 0.0, False)
        if isinstance(res, tuple) and len(res) >= 3:
            return float(res[-3])  # station, offset, outofrange
    except Exception:
        pass
    try:
        res = align.StationOffset(x, y, 0.0, 0.0)
        if isinstance(res, tuple) and len(res) >= 2:
            return float(res[-2])  # station, offset
    except Exception:
        pass
    return None


def collect_marker_stations(
    ms: Any,
    tx: Any,
    align: Any,
    sta_start: float,
    sta_end: float,
    marker_layer: str,
    log: Callable[..., None],
) -> tuple[list[float], list[Any]]:
    """Return (sorted stations, marker oids to consume) for markers on `marker_layer`.

    Each circle's centre (X, Y) is projected onto the alignment; the resulting
    station is clamped to [sta_start, sta_end]. The circle's radius is irrelevant
    — only its location marks "build a ditch here". Markers may sit off the axis.

    The second list holds the ObjectIds of every marker that DID project — those
    are consumed (erased) by the caller once their ditch is built, so the marker
    layer ends up clean. Markers that could not be projected are left in place so
    the user can see and fix them, and their oids are not returned.
    """
    stations: list[float] = []
    consume: list[Any] = []
    skipped = 0
    for oid in ms:
        try:
            ent = tx.GetObject(oid, OpenMode.ForRead)
        except Exception:
            continue
        if not isinstance(ent, Circle) or ent.Layer != marker_layer:
            continue
        c = ent.Center
        sta = _project_station(align, float(c.X), float(c.Y))
        if sta is None:
            skipped += 1
            log(
                f"  marker at ({c.X:.2f}, {c.Y:.2f}): cannot project — left in place",
                "WARN",
            )
            continue
        clamped = max(sta_start, min(sta_end, sta))
        stations.append(clamped)
        consume.append(oid)
        log(f"  marker at ({c.X:.2f}, {c.Y:.2f}) -> station {clamped:.3f}")

    stations.sort()
    log(f"collected {len(stations)} marker station(s), {skipped} unprojectable")
    return stations, consume
