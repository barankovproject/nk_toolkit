from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from Autodesk.AutoCAD.Geometry import Plane as AcadPlane, Point3d, Vector3d

if TYPE_CHECKING:
    from civil.alignment import AlignmentWrapper
    from civil.profile import ProfileWrapper


def section_pts(
    cx: float,
    cy: float,
    cz: float,
    rx: float,
    ry: float,
    ax: float,
    ay: float,
    slope: float,
    bx: float,
    by: float,
    bz: float,
    bottom_w: float,
    d: float,
    m: float,
    t: float,
) -> list[Any]:
    """Return 9 Point3d cross-section vertices for a gabion canal (P7→P0→…→P7 order).

    When slope != 0 the cross-section lies in the plane perpendicular to the 3D
    canal tangent.  The depth unit vector in that plane is
        U = (-(slope/mag)*ax, -(slope/mag)*ay, 1/mag),  mag = sqrt(1+slope^2)
    so that cuts are perpendicular to flow.  Pass slope=0 to get a purely
    vertical cross-section (for plan-view diagrams and JSON export).
    """
    horiz = m * d
    w_top = t * math.sqrt(1.0 + m * m)
    half = bottom_w / 2.0

    mag = math.sqrt(1.0 + slope * slope)
    ux = -(slope / mag) * ax
    uy = -(slope / mag) * ay
    uz = 1.0 / mag

    def c(lat: float, vz: float) -> Point3d:
        lx = cx + rx * lat + ux * vz
        ly = cy + ry * lat + uy * vz
        lz = cz + uz * vz
        return Point3d(lx + bx, ly + by, lz + bz)

    return [
        c(-half - horiz, +d),
        c(-half, 0.0),
        c(0.0, 0.0),
        c(+half, 0.0),
        c(+half + horiz, +d),
        c(+half + horiz + w_top, +d),
        c(+half + horiz + w_top - m * (d + t), -t),
        c(-half - horiz - w_top + m * (d + t), -t),
        c(-half - horiz - w_top, +d),
    ]


def trough_section_pts(
    cx: float,
    cy: float,
    cz: float,
    rx: float,
    ry: float,
    tp: dict[str, Any],
    ux: float = 0.0,
    uy: float = 0.0,
    uz: float = 1.0,
) -> tuple[list[Any], list[Any], list[Any]]:
    """Return (body, cover, prep) point lists for a ЛК trough cross-section."""
    hw = float(tp["outer_w"]) / 2.0
    ihw_top = float(tp["inner_top_w"]) / 2.0
    ihw_bot = float(tp["inner_bot_w"]) / 2.0
    oh = float(tp["outer_h"])
    bw = float(tp["bot_wall"])
    ct = float(tp["cover_t"])
    ov = float(tp["prep_overhang"])
    pt = float(tp["prep_t"])
    ch = float(tp["chamfer"])

    z_bot = -bw
    z_top = oh - bw

    def p(lat: float, vz: float) -> Point3d:
        return Point3d(cx + rx * lat + ux * vz, cy + ry * lat + uy * vz, cz + uz * vz)

    body = [
        p(-hw, z_top),
        p(-ihw_top, z_top),
        p(-(ihw_bot + ch), ch),
        p(-ihw_bot, 0.0),
        p(+ihw_bot, 0.0),
        p(+(ihw_bot + ch), ch),
        p(+ihw_top, z_top),
        p(+hw, z_top),
        p(+hw, z_bot),
        p(-hw, z_bot),
    ]
    cover = [
        p(-hw, z_top),
        p(+hw, z_top),
        p(+hw, z_top + ct),
        p(-hw, z_top + ct),
    ]
    prep = [
        p(-(hw + ov), z_bot),
        p(+(hw + ov), z_bot),
        p(+(hw + ov), z_bot - pt),
        p(-(hw + ov), z_bot - pt),
    ]
    return body, cover, prep


def slope_uvw(slope: float, rx: float, ry: float) -> tuple[float, float, float]:
    """Convert profile slope + cross-axis (rx,ry) to trough_section_pts up-vector (ux,uy,uz)."""
    mag = math.sqrt(1.0 + slope * slope)
    return -slope / mag * ry, slope / mag * rx, 1.0 / mag


def compute_virtual_arc(
    pi_sta: float,
    R: float,
    align_w: AlignmentWrapper,
    eps: float = 0.3,
) -> dict[str, Any]:
    """Compute virtual circular arc that replaces a sharp PI with a smooth turn.

    The arc has radius R, is tangent to both incoming and outgoing alignment arms,
    and is centered on the inner side of the turn. Returns:
        phi      — signed deflection (rad)
        ang_in   — incoming tangent angle (rad)
        ang_out  — outgoing tangent angle (rad)
        R        — arc radius
        L        — tangent length PI→PC = PI→PT = R*tan(|phi|/2)
        pc_sta   — virtual PC station = pi_sta − L
        pt_sta   — virtual PT station = pi_sta + L
        center   — arc center XY (cx, cy)
    """
    ang_in = align_w.angle_at(pi_sta - eps)
    ang_out = align_w.angle_at(pi_sta + eps)
    phi = ang_out - ang_in
    while phi > math.pi:
        phi -= 2.0 * math.pi
    while phi < -math.pi:
        phi += 2.0 * math.pi

    L = R * math.tan(abs(phi) / 2.0)
    pc_sta = pi_sta - L
    pt_sta = pi_sta + L

    pi_x, pi_y = align_w.xy_at(pi_sta)
    pc_x = pi_x - L * math.cos(ang_in)
    pc_y = pi_y - L * math.sin(ang_in)

    # Arc center = PC + R · perpendicular_LEFT(ang_in) for CCW turn (phi>0),
    # mirrored for CW turn. Unified via sign(phi).
    sgn = 1.0 if phi >= 0 else -1.0
    center_x = pc_x + R * sgn * (-math.sin(ang_in))
    center_y = pc_y + R * sgn * math.cos(ang_in)

    return {
        "phi": phi,
        "ang_in": ang_in,
        "ang_out": ang_out,
        "R": R,
        "L": L,
        "pc_sta": pc_sta,
        "pt_sta": pt_sta,
        "center": (center_x, center_y),
    }


def arc_pt_dir(
    arc_info: dict[str, Any], sta: float
) -> tuple[float, float, float, float]:
    """Return (x, y, ax, ay) — XY position and unit tangent direction at station sta
    along a virtual arc described by compute_virtual_arc()."""
    phi = arc_info["phi"]
    ang_in = arc_info["ang_in"]
    R = arc_info["R"]
    pc_sta = arc_info["pc_sta"]
    pt_sta = arc_info["pt_sta"]
    cx, cy = arc_info["center"]

    span = pt_sta - pc_sta
    t_param = phi * (sta - pc_sta) / span if span > 1e-9 else 0.0

    ang = ang_in + t_param
    sgn = 1.0 if phi >= 0 else -1.0

    x = cx + R * sgn * math.sin(ang)
    y = cy + R * sgn * (-math.cos(ang))
    return x, y, math.cos(ang), math.sin(ang)


def make_cut_plane(
    align_w: AlignmentWrapper, profile_w: ProfileWrapper, sta: float
) -> AcadPlane:
    """Return an AcadPlane perpendicular to the profile tangent at station sta."""
    x, y = align_w.xy_at(sta)
    z = profile_w.elevation_at(sta)
    ang = align_w.angle_at(sta)
    ax_v, ay_v = math.cos(ang), math.sin(ang)
    slope = profile_w.slope_at(sta)
    mag = math.sqrt(1.0 + slope * slope)
    return AcadPlane(Point3d(x, y, z), Vector3d(ax_v / mag, ay_v / mag, slope / mag))
