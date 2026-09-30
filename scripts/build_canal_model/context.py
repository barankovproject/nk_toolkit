from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from civil.alignment import AlignmentWrapper
    from civil.profile import ProfileWrapper


class BuildContext:
    """Shared Civil3D transaction objects passed to all builders."""

    def __init__(
        self,
        align: AlignmentWrapper,
        profile: ProfileWrapper,
        ms: Any,
        tx: Any,
        opts: Any,
        log: Callable[..., None],
        sta_end: float,
    ) -> None:
        self.align = align
        self.profile = profile
        self.ms = ms
        self.tx = tx
        self.opts = opts
        self.log = log
        self.sta_end = sta_end
