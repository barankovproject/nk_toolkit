from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Optional

from .acad_helpers import (
    add_solid,
    ensure_layer,
    ensure_ps_defs,
    loft_solid,
    tag_trough,
    trough_layer,
)
from .config import GABION, TROUGH
from .geometry import slope_uvw, trough_section_pts

if TYPE_CHECKING:
    from .context import BuildContext


class TroughZone:
    """Computed layout for one sub-span between two split points. Plain class,
    not @dataclass -- Dynamo's CPython3 engine has no `dataclasses` module
    (surfaced 2026-09-18 on НК-4А-6). Both call sites below use keyword
    arguments, so this constructor's parameter order doesn't matter to them."""

    def __init__(
        self,
        skip: bool,
        sub_s: float,
        sub_e: float,
        zone_start: float = 0.0,
        trough_end: float = 0.0,
        n: int = 0,
        has_trim: bool = False,
        trim_len: float = 0.0,
        piece_eff: float = 0.0,
        len_eff: float = 0.0,
        slope_zone: float = 0.0,
    ) -> None:
        self.skip = skip
        self.sub_s = sub_s
        self.sub_e = sub_e
        self.zone_start = zone_start
        self.trough_end = trough_end
        self.n = n
        self.has_trim = has_trim
        self.trim_len = trim_len
        self.piece_eff = piece_eff
        self.len_eff = len_eff
        self.slope_zone = slope_zone


_TROUGH_WIDTH_KEYS = {
    "outer_w",
    "inner_top_w",
    "inner_bot_w",
    "chamfer",
    "prep_overhang",
}


class TroughBuilder:
    """Places ЛК trough Solid3d solids: factory pieces, cut pieces, and cast-in-place monolith zones."""

    def __init__(self, ctx: BuildContext, canal_name: str = "") -> None:
        self.ctx = ctx
        self._canal = canal_name
        self.errors: list[str] = []
        self._psd_trough: Any = None

    def _sections_at(
        self,
        sta: float,
        rx_v: float,
        ry_v: float,
        tp: dict[str, Any],
        slope: Optional[float] = None,
        vertical: bool = False,
        scale: float = 1.0,
    ) -> tuple[list[Any], list[Any], list[Any]]:
        """Return (body_pts, cover_pts, prep_pts) at station sta; scale widens the section for PI bisector monoliths."""
        ctx = self.ctx
        x, y = ctx.align.xy_at(sta)
        z = ctx.profile.elevation_at(sta)
        if vertical:
            body, cover, prep = trough_section_pts(x, y, z, rx_v, ry_v, tp)
            return body, cover, prep
        if slope is None:
            slope = ctx.profile.slope_at(sta)
        if scale != 1.0:
            tp = {
                k: float(v) * scale if k in _TROUGH_WIDTH_KEYS else v
                for k, v in tp.items()
            }
        ux, uy, uz = slope_uvw(slope, rx_v, ry_v)
        body, cover, prep = trough_section_pts(
            x, y, z, rx_v, ry_v, tp, ux=ux, uy=uy, uz=uz
        )
        return body, cover, prep

    def _build_solid(
        self,
        pts_A: list[Any],
        pts_B: list[Any],
        lyr: str,
        label: str,
        mark: Optional[str] = None,
        with_volume: bool = False,
    ) -> int:
        """Loft and add one solid; returns 1 on success, 0 on error (error appended to self.errors)."""
        try:
            solid = loft_solid(pts_A, pts_B, self.ctx)
            add_solid(solid, lyr, self.ctx)
            if self._psd_trough is not None:
                vol = 0.0
                if with_volume:
                    try:
                        vol = solid.MassProperties.Volume
                    except Exception:
                        pass
                tag_trough(
                    solid,
                    self._psd_trough,
                    self.ctx.tx,
                    canal=self._canal,
                    mark=mark or "",
                    volume=vol,
                )
            return 1
        except Exception as e:
            self.errors.append(f"{label}: {e}")
            self.ctx.log(f"{label}: {e}", "ERROR")
            return 0

    def _compute_zones(
        self,
        seg_s: float,
        seg_e: float,
        internal_pis: list[float],
        hw: float,
        internal_pvis: Optional[list[float]] = None,
        h_top: float = 0.0,
    ) -> tuple[list[TroughZone], list[float], set[float]]:
        """Divide seg_s→seg_e at plan PIs and profile PVIs; compute factory trough layout per sub-span.

        PI boundaries: d_left/d_right = hw*tan(phi/2)*TROUGH.mono_margin_factor (geometric miter clearance).
        PVI boundaries: d_left/d_right = TROUGH.mono_min_zone (grade-break clearance; prevents degenerate lofts).
        slope extension: at steep slopes the cover top extends forward/backward by |slope|/mag*h_top,
          reducing physical clearance — add this to d_right (downhill approach) or d_left (uphill approach).
        """
        ctx = self.ctx
        if internal_pvis is None:
            internal_pvis = []

        pi_set: set[float] = set(internal_pis)
        # Drop PVIs that are within GABION.pi_merge_tol of a plan PI — the PI setback already handles the gap,
        # and a near-coincident PVI creates a micro-span that skips the monolith entirely.
        merged_pvis = [
            s
            for s in internal_pvis
            if all(abs(s - p) > GABION.pi_merge_tol for p in pi_set)
        ]
        pvi_set: set[float] = set(merged_pvis)
        all_interior: list[float] = sorted(pi_set | pvi_set)
        boundaries = [seg_s] + all_interior + [seg_e]
        label = f"trough[{seg_s:.2f}-{seg_e:.2f}]"
        zones: list[TroughZone] = []

        for k in range(len(boundaries) - 1):
            sub_s, sub_e = boundaries[k], boundaries[k + 1]
            is_first = k == 0

            slope_zone = ctx.profile.slope_at((sub_s + sub_e) / 2.0)
            mag_zone = math.sqrt(1.0 + slope_zone * slope_zone)
            # Uphill (slope>0): cover top extends backward → increases d_left gap needed.
            # Downhill (slope<0): cover top extends forward → increases d_right gap needed.
            slope_ext_left = max(0.0, slope_zone) / mag_zone * h_top
            slope_ext_right = max(0.0, -slope_zone) / mag_zone * h_top

            # d_left: PI boundary → geometric setback; PVI boundary → TROUGH.mono_min_zone clearance.
            # If a PI also absorbed a nearby PVI (within GABION.pi_merge_tol), enforce the larger of both.
            # slope_ext_left added at all non-zero boundaries.
            d_left = 0.0
            if boundaries[k] in pi_set:
                phi_l = ctx.align.deflection_at(boundaries[k])
                base_l = hw * math.tan(phi_l / 2.0) * TROUGH.mono_margin_factor
                if any(
                    abs(boundaries[k] - p) < GABION.pi_merge_tol for p in internal_pvis
                ):
                    base_l = max(
                        base_l, TROUGH.mono_min_zone * TROUGH.mono_margin_factor
                    )
                d_left = base_l + slope_ext_left
            elif boundaries[k] in pvi_set:
                d_left = (
                    TROUGH.mono_min_zone * TROUGH.mono_margin_factor + slope_ext_left
                )

            # d_right: same logic for the right boundary.
            d_right = 0.0
            if boundaries[k + 1] in pi_set:
                phi_r = ctx.align.deflection_at(boundaries[k + 1])
                base_r = hw * math.tan(phi_r / 2.0) * TROUGH.mono_margin_factor
                if any(
                    abs(boundaries[k + 1] - p) < GABION.pi_merge_tol
                    for p in internal_pvis
                ):
                    base_r = max(
                        base_r, TROUGH.mono_min_zone * TROUGH.mono_margin_factor
                    )
                d_right = base_r + slope_ext_right
            elif boundaries[k + 1] in pvi_set:
                d_right = (
                    TROUGH.mono_min_zone * TROUGH.mono_margin_factor + slope_ext_right
                )

            available = (sub_e - sub_s) - d_left - d_right
            if available < GABION.min_trim:
                ctx.log(
                    f"  {label} sub[{sub_s:.2f}-{sub_e:.2f}]: available={available:.3f} m"
                    f" < {GABION.min_trim} m, skipped"
                )
                zones.append(TroughZone(skip=True, sub_s=sub_s, sub_e=sub_e))
                continue

            len_eff = TROUGH.std_len / mag_zone
            piece_eff = len_eff + TROUGH.gap

            n = int(available / piece_eff)
            remaining = available - n * piece_eff
            trim_len = (
                remaining - TROUGH.gap
                if remaining - TROUGH.gap >= GABION.min_trim
                else 0.0
            )
            has_trim = trim_len >= GABION.min_trim

            zone_offset = 0.0 if (is_first or has_trim) else remaining / 2.0
            zone_start = sub_s + d_left + zone_offset

            if has_trim:
                trough_end = zone_start + n * piece_eff + trim_len
            elif n > 0:
                trough_end = zone_start + (n - 1) * piece_eff + len_eff
            else:
                trough_end = zone_start

            ctx.log(
                f"  {label} sub[{sub_s:.2f}-{sub_e:.2f}]:"
                f" d_left={d_left:.3f} d_right={d_right:.3f}"
                f" avail={available:.3f} n={n} trim={trim_len if has_trim else 0.0:.3f}"
                f" offset={zone_offset:.3f} slope={slope_zone:.3f} len_eff={len_eff:.4f}"
            )
            zones.append(
                TroughZone(
                    skip=False,
                    sub_s=sub_s,
                    sub_e=sub_e,
                    zone_start=zone_start,
                    trough_end=trough_end,
                    n=n,
                    has_trim=has_trim,
                    trim_len=trim_len,
                    piece_eff=piece_eff,
                    len_eff=len_eff,
                    slope_zone=slope_zone,
                )
            )
        return zones, all_interior, pi_set

    def build_segment(
        self,
        tp: dict[str, Any],
        tp_key: str,
        seg_s: float,
        seg_e: float,
        plan_pi_stas: list[float],
        pvi_stas: list[float],
    ) -> tuple[int, dict[str, int]]:
        """Build all trough solids for one canal segment. Returns (solid_count, piece_stats)."""
        ctx = self.ctx
        hw = float(tp["outer_w"]) / 2.0
        label = f"trough[{seg_s:.2f}-{seg_e:.2f}]"
        lk_mark: str = tp.get("lk", "")
        pt_mark: str = tp.get("pt", "")

        try:
            _, self._psd_trough, _, _ = ensure_ps_defs(ctx.ms.Database, ctx.tx)
        except Exception as e:
            ctx.log(f"trough property set init failed: {e}", "WARN")
            self._psd_trough = None

        body_lyr = trough_layer(tp_key, "lk")
        cover_lyr = trough_layer(tp_key, "pt")
        prep_lyr = trough_layer(tp_key, "prep")
        mono_lyr = trough_layer(tp_key, "mono")
        body_cut_lyr = trough_layer(tp_key, "lk_cut")
        cover_cut_lyr = trough_layer(tp_key, "pt_cut")
        for lyr in (body_cut_lyr, cover_cut_lyr):
            ensure_layer(ctx.ms.Database, ctx.tx, lyr)

        internal_pis = sorted(
            s
            for s in plan_pi_stas
            if seg_s + TROUGH.slice_end_gap < s < seg_e - TROUGH.slice_end_gap
        )
        internal_pvis = sorted(
            s
            for s in pvi_stas
            if seg_s + TROUGH.slice_end_gap < s < seg_e - TROUGH.slice_end_gap
        )
        h_top = (
            float(tp["outer_h"]) - float(tp["bot_wall"]) + float(tp.get("cover_t", 0.0))
        )
        zones, all_interior, pi_set = self._compute_zones(
            seg_s, seg_e, internal_pis, hw, internal_pvis, h_top
        )

        for k, split_sta in enumerate(all_interior):
            zd_prev, zd_next = zones[k], zones[k + 1]
            if zd_prev.skip or zd_next.skip:
                continue
            gap = zd_next.zone_start - zd_prev.trough_end
            kind = "PI" if split_sta in pi_set else "PVI"
            flag = " ***" if gap > 2.0 else ""
            ctx.log(
                f"  {label} gap @{kind} {split_sta:.3f}:"
                f" {zd_prev.trough_end:.3f}→{zd_next.zone_start:.3f} ({gap:.3f}m){flag}"
            )
        last_zd = next((zd for zd in reversed(zones) if not zd.skip), None)
        if last_zd is not None:
            end_gap = seg_e - last_zd.trough_end
            if end_gap > 0.05:
                flag = " ***" if end_gap > 2.0 else ""
                ctx.log(
                    f"  {label} end gap: {last_zd.trough_end:.3f}→{seg_e:.3f} ({end_gap:.3f}m){flag}"
                )

        count = 0
        piece_stats: dict[str, int] = {"std": 0, "cut": 0, "mono": 0}

        def rx_ry_at(sta: float) -> tuple[float, float]:
            return ctx.align.cross_axis_at(sta)

        def _prep_pts(sta: float) -> list[Any]:
            """Cross-section for the prep slab; at a plan PI uses bisector + scale so the corner is wide enough."""
            if sta in pi_set:
                phi = ctx.align.deflection_at(sta)
                cos_half = math.cos(phi / 2.0)
                sc = 1.0 / cos_half if cos_half > 1e-6 else 1.0
                ax_bis, ay_bis = ctx.align.bisector_at(sta)
                _, _, p = self._sections_at(sta, -ay_bis, ax_bis, tp, scale=sc)
            else:
                _, _, p = self._sections_at(sta, *rx_ry_at(sta), tp)
            return p

        # pass 0: continuous prep slab — one solid per sub-span (sub_s → sub_e), no gaps.
        # Prep is cast-in-place monolithic concrete; no alignment to trough piece boundaries.
        # Includes skipped micro-spans so the slab is truly uninterrupted.
        # At plan PI boundaries the section uses the bisector and scale=1/cos(phi/2) so the
        # prep footprint is wide enough to cover the mitered corner.
        for zd in zones:
            pA = _prep_pts(zd.sub_s)
            pB = _prep_pts(zd.sub_e)
            count += self._build_solid(pA, pB, prep_lyr, label)

        pt_L = float(tp.get("pt_L", TROUGH.std_len))

        # pass 1: factory trough bodies (per-piece slope to avoid distortion at grade breaks)
        for zd in zones:
            if zd.skip:
                continue
            for i in range(zd.n):
                sta_A = zd.zone_start + i * zd.piece_eff
                sta_B = sta_A + zd.len_eff
                sta_mid = (sta_A + sta_B) / 2.0
                rx_v, ry_v = rx_ry_at(sta_mid)
                slope = ctx.profile.slope_at(sta_mid)
                bA, _, _ = self._sections_at(sta_A, rx_v, ry_v, tp, slope=slope)
                bB, _, _ = self._sections_at(sta_B, rx_v, ry_v, tp, slope=slope)
                count += self._build_solid(bA, bB, body_lyr, label, mark=lk_mark)
                piece_stats["std"] += 1

            if zd.has_trim:
                sta_A = zd.zone_start + zd.n * zd.piece_eff
                sta_B = sta_A + zd.trim_len
                sta_mid = (sta_A + sta_B) / 2.0
                rx_v, ry_v = rx_ry_at(sta_mid)
                slope = ctx.profile.slope_at(sta_mid)
                bA, _, _ = self._sections_at(sta_A, rx_v, ry_v, tp, slope=slope)
                bB, _, _ = self._sections_at(sta_B, rx_v, ry_v, tp, slope=slope)
                count += self._build_solid(bA, bB, body_cut_lyr, label, mark=lk_mark)
                piece_stats["cut"] += 1

        # pass 1b: factory trough covers — zone-level layout independent of body boundaries.
        # N full ПТ plates (pt_L each) laid consecutively from zone_start; remainder → mono_lyr.
        for zd in zones:
            if zd.skip:
                continue
            mag_z = math.sqrt(1.0 + zd.slope_zone**2)
            pt_L_eff = pt_L / mag_z
            span = zd.trough_end - zd.zone_start
            n_cov = int(span / pt_L_eff + 1e-9)
            for j in range(n_cov):
                csA = zd.zone_start + j * pt_L_eff
                csB = csA + pt_L_eff
                csta_mid = (csA + csB) / 2.0
                rx_v, ry_v = rx_ry_at(csta_mid)
                _, cA, _ = self._sections_at(csA, rx_v, ry_v, tp, slope=zd.slope_zone)
                _, cB, _ = self._sections_at(csB, rx_v, ry_v, tp, slope=zd.slope_zone)
                count += self._build_solid(cA, cB, cover_lyr, label, mark=pt_mark)
            cov_rem = span - n_cov * pt_L_eff
            if cov_rem > 0.05:
                csA = zd.zone_start + n_cov * pt_L_eff
                rx_v, ry_v = rx_ry_at((csA + zd.trough_end) / 2.0)
                _, cA, _ = self._sections_at(csA, rx_v, ry_v, tp, slope=zd.slope_zone)
                _, cB, _ = self._sections_at(
                    zd.trough_end, rx_v, ry_v, tp, slope=zd.slope_zone
                )
                count += self._build_solid(
                    cA, cB, mono_lyr, label, mark=pt_mark, with_volume=True
                )
                piece_stats["mono"] += 1
                ctx.log(
                    f"  {label} cover remainder @{csA:.3f}-{zd.trough_end:.3f}"
                    f" ({cov_rem:.3f}m) → mono"
                )

        def _eff_prev(idx: int) -> Optional[TroughZone]:
            return next(
                (zones[i] for i in range(idx, -1, -1) if not zones[i].skip), None
            )

        def _eff_next(idx: int) -> Optional[TroughZone]:
            return next(
                (zones[i] for i in range(idx, len(zones)) if not zones[i].skip), None
            )

        _MIN_HALF = 0.05  # minimum half-span (m) for 3-section bisector loft

        # pass 2: bisector monolith at each internal plan PI
        for idx, split_sta in enumerate(all_interior):
            if split_sta not in pi_set:
                continue
            zd_prev = _eff_prev(idx)
            zd_next = _eff_next(idx + 1)
            if zd_prev is None or zd_next is None:
                continue

            sta_A = zd_prev.trough_end
            sta_B = zd_next.zone_start
            if sta_B <= sta_A + 0.001:
                continue

            phi = ctx.align.deflection_at(split_sta)
            cos_half = math.cos(phi / 2.0)
            scale = 1.0 / cos_half if cos_half > 1e-6 else 1.0

            ax_bis, ay_bis = ctx.align.bisector_at(split_sta)
            rx_bis, ry_bis = -ay_bis, ax_bis

            slope_left = ctx.profile.slope_at((sta_A + split_sta) / 2.0)
            slope_right = ctx.profile.slope_at((split_sta + sta_B) / 2.0)
            # Average, not profile.slope_at(split_sta): at PI+PVI coincidence GradeAt()
            # returns the outgoing grade, making one half carry the full slope jump → twist.
            slope_mid = (slope_left + slope_right) / 2.0

            if split_sta - sta_A < _MIN_HALF or sta_B - split_sta < _MIN_HALF:
                slope_fb = ctx.profile.slope_at((sta_A + sta_B) / 2.0)
                bA_f, cA_f, _ = self._sections_at(
                    sta_A, *rx_ry_at(sta_A), tp, slope=slope_fb
                )
                bB_f, cB_f, _ = self._sections_at(
                    sta_B, *rx_ry_at(sta_B), tp, slope=slope_fb
                )
                count += self._build_solid(
                    bA_f, bB_f, mono_lyr, label, mark=lk_mark, with_volume=True
                )
                count += self._build_solid(
                    cA_f, cB_f, mono_lyr, label, mark=pt_mark, with_volume=True
                )
                piece_stats["mono"] += 1
                ctx.log(
                    f"  {label} mono PI={split_sta:.2f} fallback A→B:"
                    f" {sta_A:.3f}->{sta_B:.3f} (half<5cm)"
                )
                continue

            bA, cA, _ = self._sections_at(sta_A, *rx_ry_at(sta_A), tp, slope=slope_left)
            bPI, cPI, _ = self._sections_at(
                split_sta, rx_bis, ry_bis, tp, slope=slope_mid, scale=scale
            )
            bB, cB, _ = self._sections_at(
                sta_B, *rx_ry_at(sta_B), tp, slope=slope_right
            )

            count += self._build_solid(
                bA, bPI, mono_lyr, label, mark=lk_mark, with_volume=True
            )
            count += self._build_solid(
                cA, cPI, mono_lyr, label, mark=pt_mark, with_volume=True
            )
            count += self._build_solid(
                bPI, bB, mono_lyr, label, mark=lk_mark, with_volume=True
            )
            count += self._build_solid(
                cPI, cB, mono_lyr, label, mark=pt_mark, with_volume=True
            )

            piece_stats["mono"] += 1
            ctx.log(
                f"  {label} mono PI={split_sta:.2f}: {sta_A:.3f}->{split_sta:.3f}->{sta_B:.3f}"
                f" phi={math.degrees(phi):.1f}deg scale={scale:.3f}"
            )

        # pass 3: straight monolith at each profile PVI grade break
        # _eff_prev/next skip over micro-spans; dedup prevents building same span twice
        built_pvi_spans: set[tuple[float, float]] = set()
        for idx, split_sta in enumerate(all_interior):
            if split_sta in pi_set:
                continue
            zd_prev = _eff_prev(idx)
            zd_next = _eff_next(idx + 1)
            if zd_prev is None or zd_next is None:
                continue

            sta_A = zd_prev.trough_end
            sta_B = zd_next.zone_start
            if sta_B <= sta_A + 0.001:
                continue
            span_key = (round(sta_A, 3), round(sta_B, 3))
            if span_key in built_pvi_spans:
                continue
            built_pvi_spans.add(span_key)

            slope_left = ctx.profile.slope_at((sta_A + split_sta) / 2.0)
            slope_right = ctx.profile.slope_at((split_sta + sta_B) / 2.0)
            slope_mid = (slope_left + slope_right) / 2.0
            rx_pi, ry_pi = rx_ry_at(split_sta)

            if split_sta - sta_A < _MIN_HALF or sta_B - split_sta < _MIN_HALF:
                slope_fb = ctx.profile.slope_at((sta_A + sta_B) / 2.0)
                bA_f, cA_f, _ = self._sections_at(
                    sta_A, *rx_ry_at(sta_A), tp, slope=slope_fb
                )
                bB_f, cB_f, _ = self._sections_at(
                    sta_B, *rx_ry_at(sta_B), tp, slope=slope_fb
                )
                count += self._build_solid(
                    bA_f, bB_f, mono_lyr, label, mark=lk_mark, with_volume=True
                )
                count += self._build_solid(
                    cA_f, cB_f, mono_lyr, label, mark=pt_mark, with_volume=True
                )
                piece_stats["mono"] += 1
                ctx.log(
                    f"  {label} mono PVI={split_sta:.2f} fallback A→B:"
                    f" {sta_A:.3f}->{sta_B:.3f} slopes={slope_left:.4f}/{slope_right:.4f} (half<5cm)"
                )
                continue

            bA, cA, _ = self._sections_at(sta_A, *rx_ry_at(sta_A), tp, slope=slope_left)
            bPI, cPI, _ = self._sections_at(
                split_sta, rx_pi, ry_pi, tp, slope=slope_mid
            )
            bB, cB, _ = self._sections_at(
                sta_B, *rx_ry_at(sta_B), tp, slope=slope_right
            )

            count += self._build_solid(
                bA, bPI, mono_lyr, label, mark=lk_mark, with_volume=True
            )
            count += self._build_solid(
                cA, cPI, mono_lyr, label, mark=pt_mark, with_volume=True
            )
            count += self._build_solid(
                bPI, bB, mono_lyr, label, mark=lk_mark, with_volume=True
            )
            count += self._build_solid(
                cPI, cB, mono_lyr, label, mark=pt_mark, with_volume=True
            )
            piece_stats["mono"] += 1
            ctx.log(
                f"  {label} mono PVI={split_sta:.2f}: {sta_A:.3f}->{split_sta:.3f}->{sta_B:.3f}"
                f" slopes={slope_left:.4f}/{slope_right:.4f}"
            )

        # pass 4: end mono gap before widening
        if last_zd is not None and seg_e - last_zd.trough_end > 0.05:
            sta_A = last_zd.trough_end
            sta_B = seg_e
            slope_mid = ctx.profile.slope_at((sta_A + sta_B) / 2.0)
            bA, cA, _ = self._sections_at(sta_A, *rx_ry_at(sta_A), tp, slope=slope_mid)
            bB, cB, _ = self._sections_at(sta_B, *rx_ry_at(sta_B), tp, vertical=True)
            count += self._build_solid(
                bA, bB, mono_lyr, label, mark=lk_mark, with_volume=True
            )
            count += self._build_solid(
                cA, cB, mono_lyr, label, mark=pt_mark, with_volume=True
            )
            piece_stats["mono"] += 1
            ctx.log(f"  {label} end mono: {sta_A:.3f}->{sta_B:.3f}")

        return count, piece_stats
