from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Optional

from .acad_helpers import (
    add_solid,
    ensure_layer,
    ensure_ps_defs,
    gabion_layer,
    loft_solid,
    tag_gabion,
    tag_gabion_baskets,
)
from .config import pk_to_sta
from .geometry import section_pts
from .section_params import (
    loft_substations,
    pi_reach_at,
    section_params_at,
    type_key_at,
)

if TYPE_CHECKING:
    from .context import BuildContext

_OUTER_INDICES = [5, 6, 7, 8]  # P4, P5, P6, P7


def _outer_shell_area(pts0: list[Any], pts1: list[Any]) -> float:
    """Surface area of P4→P5→P6→P7 outer shell between two cross-sections.

    Each of the 3 edge segments forms a quadrilateral, split into two triangles.
    """

    def xyz(p: Any) -> tuple[float, float, float]:
        return (float(p.X), float(p.Y), float(p.Z))

    def tri_area(
        a: tuple[float, float, float],
        b: tuple[float, float, float],
        c: tuple[float, float, float],
    ) -> float:
        ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
        cx = uy * vz - uz * vy
        cy = uz * vx - ux * vz
        cz = ux * vy - uy * vx
        return 0.5 * math.sqrt(cx * cx + cy * cy + cz * cz)

    area = 0.0
    for k in range(len(_OUTER_INDICES) - 1):
        i, j = _OUTER_INDICES[k], _OUTER_INDICES[k + 1]
        a0, b0 = xyz(pts0[i]), xyz(pts0[j])
        a1, b1 = xyz(pts1[i]), xyz(pts1[j])
        area += tri_area(a0, b0, b1) + tri_area(a0, b1, a1)
    return area


class GabionBuilder:
    """Builds gabion Solid3d solids for all non-trough stations along the alignment."""

    def __init__(
        self,
        ctx: BuildContext,
        cfg_types: dict[str, Any],
        trough_cfg_types: dict[str, Any],
        segments: list[dict[str, Any]],
        widening: Optional[dict[str, Any]],
        bx: float,
        by: float,
        bz: float,
        virtual_arc_overrides: Optional[
            dict[float, tuple[float, float, float, float]]
        ] = None,
        canal_name: str = "",
        gsi_baskets: Optional[dict[str, str]] = None,
    ) -> None:
        self.ctx = ctx
        self.cfg_types = cfg_types
        self.trough_cfg_types = trough_cfg_types
        self.segments = segments
        self.widening = widening
        self.bx = bx
        self.by = by
        self.bz = bz
        self.virtual_arc_overrides = virtual_arc_overrides or {}
        self._canal = canal_name
        self._gsi_baskets: dict[str, str] = gsi_baskets or {}
        self._psd_gabion: Any = None
        self._psd_basket: Any = None
        self.errors: list[str] = []

        self.last_gabion_key: str = next(
            (str(s["type"]) for s in reversed(segments) if str(s["type"]) in cfg_types),
            str(segments[0]["type"]),
        )

    def _section_at(self, sta: float, use_bisector: bool = False) -> list[Any]:
        """Return 9-point gabion cross-section profile at station sta.

        Priority:
          1. virtual_arc_overrides[sta] — XY and direction from a fan-slice anchor
             along a sharp-PI virtual arc; bisector flag is ignored here.
          2. use_bisector=True — bisector direction at a plan-PI boundary (legacy
             behaviour for non-sharp PIs).
          3. Otherwise — local alignment tangent.
        """
        ctx = self.ctx
        override = self.virtual_arc_overrides.get(round(sta, 4))
        if override is not None:
            x, y, ax_v, ay_v = override
            rx_v, ry_v = -ay_v, ax_v
        elif use_bisector:
            x, y = ctx.align.xy_at(sta)
            ax_v, ay_v = ctx.align.bisector_at(sta)
            rx_v, ry_v = -ay_v, ax_v
        else:
            x, y = ctx.align.xy_at(sta)
            ang = ctx.align.angle_at(sta)
            ax_v, ay_v = math.cos(ang), math.sin(ang)
            rx_v, ry_v = -ay_v, ax_v
        elev = ctx.profile.elevation_at(sta) - self.bz
        slope = ctx.profile.slope_at(sta)
        bw, d, m_s, t = section_params_at(
            sta, self.segments, self.cfg_types, ctx.sta_end, self.widening
        )
        return section_pts(
            x - self.bx,
            y - self.by,
            elev,
            rx_v,
            ry_v,
            ax_v,
            ay_v,
            slope,
            self.bx,
            self.by,
            self.bz,
            bw,
            d,
            m_s,
            t,
        )

    def _reach_at(self, sta: float, pi_set: set[float]) -> float:
        """Bisector-miter reach (pullback + lean) when sta is a plan PI, else 0.0.

        Sharp-PI fan anchors (virtual_arc_overrides) are not bisector miters —
        their spans need no corner-piece reservation.
        """
        if round(sta, 4) in self.virtual_arc_overrides:
            return 0.0
        return pi_reach_at(
            sta,
            pi_set,
            self.ctx.align,
            self.ctx.profile.slope_at,
            self.segments,
            self.cfg_types,
            self.ctx.sta_end,
            self.widening,
        )

    def _is_trough(self, sta: float) -> bool:
        """Return True if station sta falls inside a trough segment (skip gabion lofting there)."""
        if self.widening is not None:
            if sta >= self.ctx.sta_end - float(self.widening["length"]) - 1e-6:
                return False
        for seg in self.segments:
            if (
                pk_to_sta(seg["from"]) <= sta <= pk_to_sta(seg["to"]) + 0.001
                and str(seg["type"]) in self.trough_cfg_types
            ):
                return True
        return False

    def _loft_span(
        self,
        s0: float,
        s1: float,
        pts0: list[Any],
        pts1: list[Any],
    ) -> int:
        """Loft one gabion span s0→s1 from pre-computed cross-sections; returns 1 on success."""
        ctx = self.ctx
        try:
            solid = loft_solid(pts0, pts1, ctx)
            tk = type_key_at((s0 + s1) / 2.0, self.segments)
            if tk not in self.cfg_types:
                tk = self.last_gabion_key
            layer = gabion_layer(tk)
            # Layers "inf_model_canals_3d_t1".."t8" already exist in every canal
            # drawing's template (created once, by hand) -- but a NEW type key
            # from an alternate type_table (e.g. Stage 1's "10"/"11") has no such
            # pre-existing layer, and Entity.set_Layer raises eKeyNotFound on an
            # unknown name (НК-4А-6, 2026-09-18). ensure_layer is a cheap no-op
            # once the layer exists, same defensive call trough_builder.py
            # already makes for ITS OWN newer (non-template) layers.
            ensure_layer(ctx.ms.Database, ctx.tx, layer)
            add_solid(solid, layer, ctx)
            if self._psd_gabion is not None:
                area = _outer_shell_area(pts0, pts1)
                vol = 0.0
                try:
                    vol = float(solid.MassProperties.Volume)
                except Exception:
                    pass
                tp_cfg = self.cfg_types.get(tk, {})
                tag_gabion(
                    solid,
                    self._psd_gabion,
                    ctx.tx,
                    canal=self._canal,
                    type_no=tk,
                    geotextile_area=area,
                    fill_volume=vol,
                    anchor_count=int(tp_cfg.get("anchor_count", 0)),
                )
                if self._psd_basket is not None:
                    dim_key = str(tp_cfg.get("basket_dim", ""))
                    tag_gabion_baskets(
                        solid,
                        self._psd_basket,
                        ctx.tx,
                        basket_dim=self._gsi_baskets.get(dim_key, dim_key),
                        basket_count=int(tp_cfg.get("basket_count", 0)),
                    )
            return 1
        except Exception as e:
            err = f"section {s0:.1f}-{s1:.1f}: {e}"
            self.errors.append(err)
            ctx.log(err, "ERROR")
            return 0

    def build(
        self,
        stations: list[float],
        plan_pi_stas: list[float],
    ) -> tuple[int, list[str]]:
        """Loft all gabion solids.

        At plan-PI boundaries the cross-section uses the bisector direction so the
        two arms of the gabion meet with a proper miter joint instead of a sheared
        loft (which creates an apparent gap in plan view).
        """
        try:
            self._psd_gabion, _, self._psd_basket, _ = ensure_ps_defs(
                self.ctx.ms.Database, self.ctx.tx
            )
        except Exception as e:
            self.ctx.log(f"gabion property set init failed: {e}", "WARN")
            self._psd_gabion = None
            self._psd_basket = None

        pi_set: set[float] = set(plan_pi_stas)
        count = 0
        for i in range(len(stations) - 1):
            seg0, seg1 = stations[i], stations[i + 1]
            if self._is_trough((seg0 + seg1) / 2.0):
                continue

            # PI-adjacent corner pieces are reserved so they neither
            # self-intersect (НК-3А-1 degenerate wedge) nor grow a
            # longitudinal 3D edge beyond loft_step (НК-1А-3 3.21 m edge).
            sub = loft_substations(
                seg0,
                seg1,
                self.ctx.profile.slope_at,
                reach_head=self._reach_at(seg0, pi_set),
                reach_tail=self._reach_at(seg1, pi_set),
            )

            for j in range(len(sub) - 1):
                s0, s1 = sub[j], sub[j + 1]
                use_bis_0 = any(abs(s0 - p) < 0.01 for p in pi_set)
                use_bis_1 = any(abs(s1 - p) < 0.01 for p in pi_set)
                pts0 = self._section_at(s0, use_bisector=use_bis_0)
                pts1 = self._section_at(s1, use_bisector=use_bis_1)
                count += self._loft_span(s0, s1, pts0, pts1)

        return count, self.errors
