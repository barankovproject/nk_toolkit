import math

from Autodesk.AutoCAD.Geometry import Point3d


def get_xy(align, sta):
    ac = align.GetPointAtDist(sta)
    return float(ac.X), float(ac.Y)


def get_xy_angle(align, sta, sta_end, delta=0.01):
    s0 = max(align.StartingStation, sta - delta)
    s1 = min(sta_end, sta + delta)
    ac0 = align.GetPointAtDist(s0)
    ac1 = align.GetPointAtDist(s1)
    return math.atan2(float(ac1.Y) - float(ac0.Y), float(ac1.X) - float(ac0.X))


def section_pts(cx, cy, cz, rx, ry, bx, by, bz, bottom_w, d, m, t):
    """Return 9 Point3d cross-section vertices for gabion view plan drawing.

    Uses outward normal offsets for gabion wall thickness (slope=0).
    Different from canal_model.geometry.section_pts which uses slope correction.
    """
    horiz = m * d
    sl = math.sqrt(d**2 + horiz**2)
    n_bot = (0.0, -1.0)
    n_left = (-d / sl, -horiz / sl)
    n_rgt = (+d / sl, -horiz / sl)

    def avg_norm(n1, n2):
        ax, az = n1[0] + n2[0], n1[1] + n2[1]
        mag = math.sqrt(ax**2 + az**2)
        return (ax / mag, az / mag) if mag > 1e-9 else (ax, az)

    n_p2 = avg_norm(n_left, n_bot)
    n_p3 = avg_norm(n_bot, n_rgt)
    half = bottom_w / 2.0

    def c(co, vz, nx=0.0, nz=0.0, off=False):
        lat = co + nx * t if off else co
        vz_total = vz + nz * t if off else vz
        return Point3d(cx + rx * lat + bx, cy + ry * lat + by, cz + vz_total + bz)

    return [
        c(-half - horiz, +d),
        c(-half, 0.0),
        c(0.0, 0.0),
        c(+half, 0.0),
        c(+half + horiz, +d),
        c(+half + horiz, +d, n_rgt[0], n_rgt[1], True),
        c(+half, 0.0, n_p3[0], n_p3[1], True),
        c(-half, 0.0, n_p2[0], n_p2[1], True),
        c(-half - horiz, +d, n_left[0], n_left[1], True),
    ]
