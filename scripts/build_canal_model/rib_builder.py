from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Optional

from Autodesk.AutoCAD.Geometry import Point3d

from .acad_helpers import add_solid, loft_solid, tag_rib
from .config import RIBS

_RIB_BASKET_DIM = "3x0.3x0.3"

if TYPE_CHECKING:
    from .context import BuildContext


class RibBuilder:
    """Places transverse rib Solid3d solids across the canal bottom."""

    def __init__(
        self,
        ctx: BuildContext,
        canal_name: str = "",
        psd_rib: Any = None,
        gsi_baskets: Optional[dict[str, str]] = None,
    ) -> None:
        self.ctx = ctx
        self._canal = canal_name
        self._psd_rib = psd_rib
        self._rib_dim = (gsi_baskets or {}).get(_RIB_BASKET_DIM, _RIB_BASKET_DIM)
        self.errors: list[str] = []

    def _make_solid(
        self,
        x: float,
        y: float,
        elev: float,
        ang: float,
        lat1: float,
        lat2: float,
        layer: str,
        slope: float = 0.0,
    ) -> None:
        """Loft a single rib rectangle between lateral offsets lat1 and lat2."""
        ctx = self.ctx
        ax_r, ay_r = math.cos(ang), math.sin(ang)
        rx_v, ry_v = -math.sin(ang), math.cos(ang)
        half = RIBS.size / 2.0
        mag = math.sqrt(1.0 + slope * slope)
        ux = -slope * ry_v / mag
        uy = slope * rx_v / mag
        uz = 1.0 / mag

        dz = slope * half  # elevation offset at ±half along canal axis

        def rect_at(lat: float) -> list[Any]:
            cx2 = x + rx_v * lat
            cy2 = y + ry_v * lat
            return [
                Point3d(cx2 - ax_r * half, cy2 - ay_r * half, elev - dz),
                Point3d(cx2 + ax_r * half, cy2 + ay_r * half, elev + dz),
                Point3d(
                    cx2 + ax_r * half + ux * RIBS.size,
                    cy2 + ay_r * half + uy * RIBS.size,
                    elev + dz + uz * RIBS.size,
                ),
                Point3d(
                    cx2 - ax_r * half + ux * RIBS.size,
                    cy2 - ay_r * half + uy * RIBS.size,
                    elev - dz + uz * RIBS.size,
                ),
            ]

        solid = loft_solid(rect_at(lat1), rect_at(lat2), ctx)
        add_solid(solid, layer, ctx)
        if self._psd_rib is not None:
            vol = 0.0
            try:
                vol = float(solid.MassProperties.Volume)
            except Exception:
                pass
            tag_rib(
                solid,
                self._psd_rib,
                ctx.tx,
                canal=self._canal,
                basket_dim=self._rib_dim,
                basket_count=1,
                volume=vol,
            )

    def _place_one(
        self,
        rib_sta: float,
        lat_a: float,
        lat_b: float,
        label: str,
        layer: str,
    ) -> int:
        """Place one rib solid at rib_sta; returns 1 on success, 0 on error."""
        ctx = self.ctx
        rx2, ry2 = ctx.align.xy_at(rib_sta)
        r_elev = ctx.profile.elevation_at(rib_sta)
        r_ang = ctx.align.angle_at(rib_sta)
        r_slope = ctx.profile.slope_at(rib_sta)
        try:
            self._make_solid(
                rx2, ry2, r_elev, r_ang, lat_a, lat_b, layer, slope=r_slope
            )
            return 1
        except Exception as e:
            err = f"rib [{label}] at sta={rib_sta:.2f}: {e}"
            self.errors.append(err)
            self.ctx.log(err, "ERROR")
            return 0

    def place(
        self,
        zone_start: float,
        zone_end: float,
        bottom_w: float,
        label: str,
        layer: str,
        stagger: bool = False,
        split: bool = True,
    ) -> int:
        """Place ribs from zone_end back to zone_start.

        split=False  → one solid per station spanning the full bottom_w (regular segments)
        split=True   → two solids with RIBS.gap in the middle (default, legacy)
        stagger=True → alternating n_a/n_b rows (widening flat zone)
        """
        count = 0
        rib_sta = zone_end - RIBS.size / 2.0

        if stagger:
            n_a = max(2, int((bottom_w + RIBS.gap) / (RIBS.max_len + RIBS.gap)))
            rib_len = max(
                RIBS.min_len, min(RIBS.max_len, (bottom_w - (n_a - 1) * RIBS.gap) / n_a)
            )
            n_b = n_a - 1

            def lateral_positions(n: int) -> list[tuple[float, float]]:
                total_span = n * rib_len + (n - 1) * RIBS.gap
                start = -total_span / 2.0
                pitch = rib_len + RIBS.gap
                return [
                    (start + i * pitch, start + i * pitch + rib_len) for i in range(n)
                ]

            pos_a = lateral_positions(n_a)
            pos_b = lateral_positions(n_b)
            is_a = True
            while rib_sta >= zone_start - 1e-6:
                for lat_a, lat_b in pos_a if is_a else pos_b:
                    count += self._place_one(rib_sta, lat_a, lat_b, label, layer)
                slope_r = self.ctx.profile.slope_at(rib_sta)
                mag_r = math.sqrt(1.0 + slope_r * slope_r)
                rib_sta -= RIBS.step / mag_r
                is_a = not is_a
        elif not split:
            half_w = bottom_w / 2.0
            while rib_sta >= zone_start - 1e-6:
                count += self._place_one(rib_sta, -half_w, half_w, label, layer)
                slope_r = self.ctx.profile.slope_at(rib_sta)
                mag_r = math.sqrt(1.0 + slope_r * slope_r)
                rib_sta -= RIBS.step / mag_r
        else:
            half_gap = RIBS.gap / 2.0
            rib_length = (bottom_w - RIBS.gap) / 2.0
            while rib_sta >= zone_start - 1e-6:
                count += self._place_one(
                    rib_sta, half_gap, half_gap + rib_length, label, layer
                )
                count += self._place_one(
                    rib_sta, -half_gap, -(half_gap + rib_length), label, layer
                )
                slope_r = self.ctx.profile.slope_at(rib_sta)
                mag_r = math.sqrt(1.0 + slope_r * slope_r)
                rib_sta -= RIBS.step / mag_r

        return count
