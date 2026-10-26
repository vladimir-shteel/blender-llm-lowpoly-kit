"""Hard-surface forms: chamfered prisms and boxes, plates, hinge pins, hubs, slots and a mechanical hand.
Flat caps, cut corners and flat facets read as manufactured next to an organic body, so none of these closes
on an apex or takes radius noise.

A frame `axes` is three orthonormal directions (x, y, z) in world space: a section lies in the x-y plane and a
prism runs along z. Faces are turned outward by a point inside the volume, so the handedness of the frame
does not matter."""
import math
from mathutils import Vector

# The sides of a chamfered section in vertex order, counter-clockwise from +x seen from +z: the main faces at
# even indices, the cut corners between them at odd ones. A section without cut corners has the main faces
# alone (PLAIN_SIDES).
SIDES = ('+x', '+x+y', '+y', '-x+y', '-x', '-x-y', '-y', '+x-y')
PLAIN_SIDES = SIDES[0::2]
CORNERS = SIDES[1::2]
WORLD = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
# A plane facing the model's front: x across (+X), y up (+Z), z out of the face toward the viewer (-Y).
FRONT = ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, -1.0, 0.0))


def chamfer_section(half_x, half_y, cut):
    """The vertices of a rectangle with its corners cut, as (x, y) in metres in SIDES order: from the lower
    end of the +x side up, over the top to -x and back along the bottom. half_x, half_y: half sizes, m.
    cut: how far each corner is cut along both axes, m; 0 or less gives the four corners of the plain
    rectangle (PLAIN_SIDES). Raises ValueError for a cut that reaches the middle of a side."""
    x, y, k = half_x, half_y, cut
    if k <= 0:
        return [(x, -y), (x, y), (-x, y), (-x, -y)]
    if k >= min(x, y):
        raise ValueError('a corner cut of %.4f m reaches the middle of a %.4f x %.4f m section: cut less'
                         % (k, 2 * x, 2 * y))
    return [(x, -y + k), (x, y - k), (x - k, y), (-x + k, y), (-x, y - k), (-x, -y + k), (-x + k, -y), (x - k, -y)]


def _frame(axes):
    return tuple(Vector(a) for a in (axes if axes is not None else WORLD))


def _station(s):
    o = s[4] if len(s) > 4 else {}
    return s[0], s[1], s[2], s[3], o.get('offset', (0.0, 0.0)), o.get('scale', (1.0, 1.0))


def chamfer_loft(b, part, origin, axes, stations, colour, col0, col1):
    """A prism through chamfered sections along the frame's z, closed by a flat cap at each end.

    b: the Builder. part: the part's name. origin: the point z = 0 of the axis, world metres. axes: the frame
    (module docstring), None for the world axes. stations: [(z, half_x, half_y, cut[, opts])] in metres,
    chamfer_section's arguments after z; z never decreases. opts: 'offset' (dx, dy), the section's centre off
    the axis in metres; 'scale' (sx, sy), factors on the section's vertices (a section narrowing
    unevenly). Two stations at one z make a step: its face looks toward the nearer end when the next
    section is larger and toward the farther end when it is smaller. Every station has cut corners, or
    none has. colour: a palette name, or fn(band, side) for the faces from station `band` to the next, side
    a SIDES name. col0, col1: the colours of the caps at the first and the last station, n-gons the finish
    triangulates. Returns the vertex rings, one per station.

    Triangles: 2 per side per band (4 or 8 sides) plus 2 or 6 per cap. Raises ValueError for decreasing z or
    stations that mix plain and cut sections."""
    zs = [s[0] for s in stations]
    if len(stations) < 2 or any(b2 < a for a, b2 in zip(zs, zs[1:])):
        raise ValueError('chamfer_loft needs two or more stations in non-decreasing z (got %r)' % (zs,))
    if len({s[3] > 0 for s in stations}) > 1:
        raise ValueError('chamfer_loft stations mix plain and cut sections: give every station a cut, or none')
    pid = b.pid(part)
    o = Vector(origin)
    ax, ay, az = _frame(axes)
    st = [_station(s) for s in stations]
    rings = [[b.vert(o + ax * (x * sx + dx) + ay * (y * sy + dy) + az * z, pid)
              for x, y in chamfer_section(hx, hy, cut)]
             for z, hx, hy, cut, (dx, dy), (sx, sy) in st]
    n = len(rings[0])
    names = SIDES if n == 8 else PLAIN_SIDES

    def axis_point(i, z):
        dx, dy = st[i][4]
        return o + ax * dx + ay * dy + az * z

    def size(i):
        return st[i][1] * st[i][5][0] * st[i][2] * st[i][5][1]

    for i in range(len(rings) - 1):
        z0, z1 = st[i][0], st[i + 1][0]
        if z1 > z0:
            hint = (axis_point(i, z0) + axis_point(i + 1, z1)) / 2
        else:
            hint = axis_point(i, z0 + (1.0 if size(i + 1) > size(i) else -1.0))
        for j in range(n):
            b.face([rings[i][j], rings[i][(j + 1) % n], rings[i + 1][(j + 1) % n], rings[i + 1][j]],
                   colour(i, names[j]) if callable(colour) else colour, hint)
    b.face(list(reversed(rings[0])), col0, axis_point(0, st[0][0] + 1.0))
    b.face(rings[-1], col1, axis_point(len(st) - 1, st[-1][0] - 1.0))
    return rings


def chamfer_box(b, part, center, half, axes, col, col0=None, col1=None, corner=0.0, edge=0.0, taper=None):
    """A box with its four edges along z cut by `corner` and both end rims bevelled by `edge`.

    b: the Builder. part: the part's name. center: world centre, m. half: (x, y, z) half sizes, m. axes: the
    frame (module docstring), None for the world axes. col: a palette name, or fn(band, side) as
    chamfer_loft takes it: band 0 the sides, or with `edge` band 0 the -z bevel, 1 the sides and 2 the +z
    bevel. col0, col1: the -z and +z caps; they default to `col` when it is a name and are required when it
    is a function. corner, edge: metres; the bevel's end section is inset by `edge` and keeps a smaller cut.
    taper: (sx, sy), the section's scale at +z, linear along z (a housing narrowing toward a joint); None
    keeps a prism. Returns chamfer_loft's rings.

    12 triangles, 28 with cut corners; the bevels add 16 or 32. Raises ValueError for a callable `col`
    without both cap colours."""
    if callable(col) and (col0 is None or col1 is None):
        raise ValueError('chamfer_box with a colour function needs col0 and col1 for the caps')
    hx, hy, hz = half

    def station(z, inset):
        k = max(corner - inset * 0.4, corner * 0.3) if corner > 0 else 0.0
        t = (z + hz) / (2 * hz)
        scale = (1 + (taper[0] - 1) * t, 1 + (taper[1] - 1) * t) if taper else (1.0, 1.0)
        return z, hx - inset, hy - inset, k, {'scale': scale}
    zs = [(-hz, edge), (-hz + edge, 0.0), (hz - edge, 0.0), (hz, edge)] if edge > 0 else [(-hz, 0.0), (hz, 0.0)]
    return chamfer_loft(b, part, center, axes, [station(z, inset) for z, inset in zs], col,
                        col if col0 is None else col0, col if col1 is None else col1)


def segment_plate(b, part, a, c, out, half_w, half_t, col, col0=None, col1=None, lift=0.0, slide=0.0, corner=0.0,
                  edge=0.0, taper=None):
    """A housing, plate or frame member along a segment (a limb's, a strut's): a chamfer_box from a to c whose
    '+y' faces look toward `out`.

    a, c: the segment's ends, world metres. out: the plate's outer direction, made perpendicular to the
    segment. half_w: half the width across (x = out x axis), m. half_t: half the thickness along out, m.
    lift, slide: the centre's offset along out and across, m. col, col0, col1, corner, edge, taper: as
    chamfer_box takes them, '+y' being the outer face, '-y' the face against the segment, col0 the cap at a.
    Returns (centre, across, out, axis), the plate's centre and its frame."""
    a = Vector(a); c = Vector(c); z = (c - a).normalized()
    y = Vector(out); y = (y - z * y.dot(z)).normalized(); x = y.cross(z)
    cen = (a + c) / 2 + y * lift + x * slide
    chamfer_box(b, part, cen, (half_w, half_t, (c - a).length / 2), (x, y, z), col, col0, col1, corner=corner,
                edge=edge, taper=taper)
    return cen, x, y, z


def standoff_plate(b, part, outline, origin, depth, colour, side_colour=None, axes=FRONT):
    """A flat plate standing off a face: a convex outline in the frame's x-y plane through `origin`, raised
    along the frame's z by `depth`, its back left open and buried in what it stands on.

    outline: [(x, y)] in metres in the plane, convex, wound either way. origin: a point of the buried plane,
    world metres. depth: how far the plate stands off, m. colour: the front's palette name. side_colour: the
    walls', default `colour`. axes: the frame, z pointing out of the face; FRONT for a plate on the model's
    front. Returns the front face's vertices.

    Triangles: 2 per outline edge plus the front's n - 2."""
    pid = b.pid(part)
    o = Vector(origin)
    ax, ay, az = _frame(axes)
    cx = sum(p[0] for p in outline) / len(outline)
    cy = sum(p[1] for p in outline) / len(outline)
    hint = o + ax * cx + ay * cy + az * (depth / 2)
    back = [b.vert(o + ax * x + ay * y, pid) for x, y in outline]
    front = [b.vert(o + ax * x + ay * y + az * depth, pid) for x, y in outline]
    n = len(outline)
    for j in range(n):
        b.face([back[j], back[(j + 1) % n], front[(j + 1) % n], front[j]], side_colour or colour, hint)
    b.face(front, colour, hint)
    return front


def slot(b, part, centre, along, length, width, colour, origin, axes=FRONT):
    """A slot, a groove or a light as one flat rectangle in the frame's x-y plane through `origin`, facing
    the frame's z. Put the plane a few millimetres off the face it marks.

    centre: (x, y) in metres in the plane. along: (dx, dy), the long axis, any length. length, width: metres.
    colour: a palette name. axes: the frame; FRONT for a slot on the model's front. Two triangles."""
    dx, dy = along
    n = (dx * dx + dy * dy) ** 0.5
    ux, uy = dx / n * length / 2, dy / n * length / 2
    vx, vy = -dy / n * width / 2, dx / n * width / 2
    cx, cy = centre
    o = Vector(origin)
    ax, ay, az = _frame(axes)
    pts = [o + ax * x + ay * y for x, y in ((cx - ux - vx, cy - uy - vy), (cx + ux - vx, cy + uy - vy),
                                            (cx + ux + vx, cy + uy + vy), (cx - ux + vx, cy - uy + vy))]
    b.decal(part, pts, colour, az)


def hinge(b, part, a, c, r, col, cap_col=None, n=6):
    """A hinge pin, a roller or an axle: an n-sided cylinder from a to c (world metres) of radius r (m) with
    flat ends in cap_col (default `col`). Returns Builder.loft's rings. 4n - 4 triangles."""
    a = Vector(a); c = Vector(c); d = (c - a).normalized()
    ref = Vector((0, 0, 1)) if abs(d.z) < 0.9 else Vector((1, 0, 0))
    return b.loft(part, [(a, r, r), (c, r, r)], n, ref, col, cap0='flat', cap1='flat',
                  col0=cap_col or col, col1=cap_col or col)


def hub(b, part, center, axis, r, depth, col, face_col=None, inner=0.6, n=8):
    """A round joint hub, an axle housing on a mechanical joint: an n-sided drum from `center` (its back,
    buried in the member) out along `axis` by `depth`, its flat face carrying a concentric disc of face_col
    (radius inner * r) floating just off it, so the hub reads as a rim round an axle cap.

    center: world metres. axis: any length. r: the drum's apothem, m. depth: m. 3n - 2 triangles, 4n - 4 with
    the disc; the back stays open."""
    o = Vector(center); ax = Vector(axis).normalized()
    ref = Vector((0, 0, 1)) if abs(ax.z) < 0.9 else Vector((1, 0, 0))
    u = (ref - ax * ref.dot(ax)).normalized(); v = ax.cross(u)
    pid = b.pid(part)
    ph = math.pi / n
    sc = r / math.cos(ph)
    pts = [u * (math.cos(ph + 2 * math.pi * j / n) * sc) + v * (math.sin(ph + 2 * math.pi * j / n) * sc)
           for j in range(n)]
    back = [b.vert(o + p, pid) for p in pts]
    front = [b.vert(o + ax * depth + p, pid) for p in pts]
    mid = o + ax * (depth / 2)
    for j in range(n):
        b.face([back[j], back[(j + 1) % n], front[(j + 1) % n], front[j]], col, mid)
    b.face(front, col, mid)
    if face_col:
        b.decal(part, [o + ax * (depth + 0.0012) + p * inner for p in pts], face_col, ax)


def mech_hand(b, part, wrist, d, out, across, palm_len, finger_len, half_w, col, finger_col, back_col=None,
              knuckle_col=None, thick=0.55, fingers=4, curl=0.3, pinch=0.68, gap=0.004, finger_t=0.8):
    """A mechanical hand: a chamfered palm housing (its back toward `out` in back_col, an armour plate) and
    digits as four-sided lofts pinched at the middle joint, so each finger reads as two segments on a hinge;
    the fingers curl toward -out and the thumb sits on the -across side.

    wrist: world metres. d: the wrist-to-fingertip direction. out: the back of the hand. across: toward the
    little finger. palm_len, finger_len: measured lengths, m (the outer fingers are 0.86 of finger_len, the
    thumb 0.8). half_w: half the palm's breadth, m. thick: palm thickness / breadth. gap: the space between
    neighbouring fingers, m. finger_t: finger thickness / palm thickness. curl: the share of a finger's
    second half turned toward -out. pinch: the middle joint's section / the base's.

    28 + 18 * (fingers + 1) triangles."""
    wrist = Vector(wrist); d = Vector(d).normalized(); out = Vector(out).normalized()
    across = Vector(across).normalized()
    t = half_w * thick

    def palm_col(band, side):
        return (back_col or col) if side == '+y' else col
    segment_plate(b, part, wrist - d * 0.004, wrist + d * palm_len, out, half_w, t, palm_col, col, col,
                  corner=t * 0.35)
    fw = half_w / fingers - gap / 2
    m = (fingers - 1) / 2
    kc = knuckle_col or finger_col

    def digit(base, dk, ln, w, th, curl_k):
        k1 = base + dk * (ln * 0.5) - out * (ln * curl_k * 0.25)
        tip = k1 + (dk * (1 - curl_k) - out * curl_k).normalized() * (ln * 0.5)
        b.loft(part, [(base, th, w), (k1, th * pinch, w * pinch), (tip, th * 0.85, w * 0.9)], 4, out,   # ra along out
               lambda i, j, dv: finger_col if i == 0 else kc, cap1='flat', col1=kc)
    for k in range(fingers):
        ln = finger_len * (0.86 if k in (0, fingers - 1) else 1.0)
        base = wrist + d * (palm_len - 0.006) + across * ((k - m) * (fw * 2 + gap)) - out * (t * 0.15)
        digit(base, d, ln, fw, t * finger_t, curl)
    tb = wrist + d * (palm_len * 0.35) - across * (half_w * 0.9) - out * (t * 0.2)
    digit(tb, (d * 0.75 - across * 0.66).normalized(), finger_len * 0.8, fw * 1.15, t * finger_t, curl * 0.6)
