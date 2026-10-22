"""Hair: a cap over the skull, loose strands, buns and spiky locks, and a long beard hanging below the chin."""
import math
from mathutils import Vector

from lpk.core.shapes import miss, point_loft
from lpk.forms.fur import tuft

X = Vector((1, 0, 0)); Y = Vector((0, 1, 0)); Z = Vector((0, 0, 1))


def _dir(phi, elev):
    """Unit direction from a head centre: phi is the azimuth from the front (-Y) toward the
    character's left (+X), elev the elevation above the centre's horizon."""
    return Vector((math.cos(elev) * math.sin(phi), -math.cos(elev) * math.cos(phi), math.sin(elev)))


def hair_cap(b, part, bvh, center, line, thick, color, n=12, rows=4, tuck=0.008, symmetric=False):
    """Hair as a shell over the skull, so the hairline shows the hair's thickness instead of a
    colour boundary painted on the head. Rings run from the crown down to a hairline given by
    line(phi) -> elevation (radians, see _dir); each vertex is raycast from `center` onto `bvh`
    (the head) and lifted radially by thick(phi, f), f from 0 at the crown to 1 at the hairline.
    A last ring under the hairline is sunk `tuck` into the head, which closes the edge.
    symmetric: False casts every vertex, so a head whose triangulated faces differ between its sides
    gives a cap up to a few millimetres off mirror; True casts the +X half (phi from 0 to pi, the
    midline vertices set to x = 0) and mirrors it through x = 0, and covered() reads line on the +X
    side for both: an exact mirror image, for a centre on the midline (x = 0; ValueError otherwise).
    n * (2 * rows + 1) triangles. Returns covered(p): True where a point lies above the hairline
    with a margin, for removing the head faces the cap hides.
    n: the cap's columns; a hairline running diagonally across them follows them only as finely as they
    are spaced. The vertices land on the head and the faces run as chords between them, so over a
    faceted head a thin cap can let the head's own vertices through near its edge, which more columns
    and rows alone need not cover. Anything rising out of the head above the tuck ring (an ear tip)
    pierces the cap from inside.
    Units: center m, color palette name or fn(i, j, normal) (point_loft's), tuck m. A ray that misses bvh
    puts its vertex 0.1 m out from the centre and is counted in the builder's probe misses (shapes.miss)."""
    c = Vector(center)
    if symmetric and abs(c.x) > 1e-6:
        raise ValueError('hair_cap(symmetric=True) mirrors through x = 0: the centre must lie on it, x is %r' % c.x)

    def surf(phi, elev):
        d = _dir(phi, elev)
        hit, _, _, _ = bvh.ray_cast(c + d * 0.5, -d)
        if hit is None:
            miss(b, 'hair_cap', part, c + d * 0.5)
            return c + d * 0.1, d
        return hit, d

    def cast(ring, j, point):
        """point(phi) -> the vertex of column j, or its mirror when symmetric puts it on the -X half."""
        if symmetric and 2 * j > n:
            q = ring[n - j]
            return Vector((-q.x, q.y, q.z))
        p = point(phis[j])
        if symmetric and 2 * j in (0, n):
            p.x = 0.0
        return p
    phis = [2 * math.pi * j / n for j in range(n)]
    rings = []
    for k in range(1, rows + 1):
        f = k / rows

        def lifted(phi):
            p, d = surf(phi, math.pi / 2 + (line(phi) - math.pi / 2) * f)
            return p + d * thick(phi, f)
        ring = []
        for j in range(n):
            ring.append(cast(ring, j, lifted))
        rings.append(ring)

    def sunk(phi):
        p, d = surf(phi, line(phi) - 0.06)
        return p - d * tuck
    edge = []
    for j in range(n):
        edge.append(cast(edge, j, sunk))
    rings.append(edge)
    top, d = surf(0.0, math.pi / 2)
    apex = top + d * thick(0.0, 0.0)
    if symmetric:
        apex.x = 0.0
    point_loft(b, part, rings, color, cap0=apex)

    def covered(p, margin=math.radians(6)):
        v = Vector(p) - c
        phi = math.atan2(abs(v.x) if symmetric else v.x, -v.y)
        return math.asin(max(-1.0, min(1.0, v.z / v.length))) > line(phi) + margin
    return covered


def remove_covered(b, part, covered):
    """Delete the faces of `part` whose vertices are all covered (hidden under a shell), and the vertices and
    edges no other face holds.
    Returns the number of faces deleted. Units: covered fn(point) -> bool. Run it once the shell over the
    covered part is built, with the covered part as `part`."""
    import bmesh
    pid = b.pid(part)
    faces = [f for f in b.bm.faces if f.verts[0][b.vpart] == pid and all(covered(v.co) for v in f.verts)]
    bmesh.ops.delete(b.bm, geom=faces, context='FACES')
    return len(faces)


def hair_strand(b, part, bvh, path, width, thick, col, tip_col=None, lift=0.004, sink=0.01,
                taper=(1.0, 0.85, 0.6, 0.4)):
    """Loose lock of hair: a flat diamond section of `width` x `thick` (half sizes) along a curved
    `path` (root first, the last point is the tip apex), tapering by `taper` per ring. The root is
    pulled onto `bvh` (the head and hair cap) and sunk by `sink`; every other point is pushed out
    of it by `lift`, so a lock drapes over the head instead of cutting into it.
    Each section lies flat against the nearest surface at its own point; a loft frame transported
    from the root stands the lock on edge where the path turns over a curved head.
    The root and the lift snap to the nearest surface point, so give points already on the surface
    (cast them first): from a point far in front of a face the nearest surface point can lie well
    aside of the intended one and slide the lock. A lock lying flat on a temple is seen edge-on from
    the front: give it the lift and the thickness to show there, and check it in the front capture.
    8 * (len(path) - 2) + 4 triangles.
    Returns rings (lists of BMVerts). Units: lift m, sink m, taper ratio per ring."""
    pts = [Vector(p) for p in path]
    hit, nrm, _, _ = bvh.find_nearest(pts[0])
    pts[0] = hit - nrm * sink
    for i in range(1, len(pts)):
        h_, n_, _, dist = bvh.find_nearest(pts[i])
        if h_ is not None and ((pts[i] - h_).dot(n_) < 0 or dist < lift):
            pts[i] = h_ + n_ * lift
    rings = []
    last = len(pts) - 1
    for i, p in enumerate(pts[:-1]):
        t = (pts[min(i + 1, last)] - pts[max(i - 1, 0)]).normalized()
        _, n_, _, _ = bvh.find_nearest(p)
        n_ = (n_ - t * n_.dot(t)).normalized()
        a = t.cross(n_)
        k = taper[min(i, len(taper) - 1)]
        rings.append([p + a * (width * k), p + n_ * (thick * k), p - a * (width * k), p - n_ * (thick * k)])
    tip = len(rings) - 1
    return point_loft(b, part, rings, lambda i, j, d: (tip_col or col) if i >= tip else col, cap1=pts[-1])


def hair_bun(b, part, base, axis, r, col, tip_col=None, n=8, seed=3, wisps=()):
    """Messy bun: a lumpy ball along `axis` from `base` (buried in the hair cap), radius r, closing
    on an apex, with wisps [(direction, length)] sticking out of it as flattened tufts. Wisps pointing
    up read as cat ears: point them sideways and back.
    Units: axis direction."""
    from lpk.core.shapes import jitter_rings
    a = Vector(axis).normalized(); o = Vector(base)
    ref = X if abs(a.dot(X)) < 0.9 else Y
    rings = [(o - a * (r * 0.3), r * 0.6, r * 0.55), (o + a * (r * 0.35), r, r * 0.92),
             (o + a * (r * 0.95), r * 0.82, r * 0.78)]
    rings = jitter_rings(rings, n, 0.12, seed=seed, skip=(0,))
    b.loft(part, rings, n, ref, col, cap1=o + a * (r * 1.4))
    centre = o + a * (r * 0.4)
    for d, length in wisps:
        d = Vector(d).normalized()
        root = centre + d * (r * 0.6)
        tuft(b, part, root, root + d * length, r * 0.3, col, tip_col=tip_col, thick=r * 0.12, front=a.cross(d), n=3)


def _faces_of(rings):
    """The faces that use a vertex of `rings`, each once, in the order the rings reach them: all the
    faces of a loft that shares no vertex with other geometry."""
    seen, faces = set(), []
    for ring in rings:
        for v in ring:
            for f in v.link_faces:
                if f not in seen:
                    seen.add(f)
                    faces.append(f)
    return faces


def hair_locks(b, part, bvh, locks, col, tip_col=None, n=4, sink=0.012, mirror=False):
    """Spiky locks rooted on the scalp. Each lock is (x, y, (dx, dy, dz), width, lit): its root is
    found by casting straight down at (x, y) onto `bvh` (the head) and buried by `sink`, and it
    grows by the offset, so locks follow any change of the head shape instead of floating.
    lit locks get `tip_col` on the end cone.
    mirror: False casts every lock, so on a head whose faces triangulate differently on its two sides
    a lock and its twin at -x land at different heights and come out off mirror (mirror.geometry
    lists them). True builds the -X side as the mirror image of the +X side, as hair_cap's
    symmetric=True does: `locks` then lists the locks at x >= 0 only. A lock at x > 0 is cast and
    built, then copied through x = 0 with its faces reversed, an exact mirror image for any n (the
    copy Builder.mirror_part makes); a lock whose ray misses skips its twin too. A lock on the
    midline (x = 0) is built once, its root set on x = 0, and is its own mirror image when its offset
    has no x and n is even: an odd n lays one corner of the section on one side. With mirror, a lock
    at x < 0, or a midline lock with an x in its offset or an odd n, raises ValueError before anything
    is built.
    Units: locks (m, m, (m, m, m), m half size, bool), sink m. A lock whose downward ray (cast from z = 10
    m) misses bvh is skipped and counted in the builder's probe misses (shapes.miss)."""
    locks = list(locks)                         # the mirror checks read it before the build loop does
    if mirror:
        neg = [k for k, lock in enumerate(locks) if lock[0] < -1e-6]
        if neg:
            raise ValueError('hair_locks(mirror=True) builds the -X locks as mirror images of the +X ones: list '
                             'only the locks at x >= 0; locks %s are at x < 0' % neg)
        mid = [k for k, lock in enumerate(locks) if abs(lock[0]) <= 1e-6 and (abs(lock[2][0]) > 1e-6 or n % 2)]
        if mid:
            raise ValueError('hair_locks(mirror=True): a midline lock is its own mirror image only with no x in its '
                             'offset and an even n; locks %s on the midline break that (n = %d)' % (mid, n))
    for x, y, off, w, lit in locks:
        hit, _, _, _ = bvh.ray_cast(Vector((x, y, 10.0)), -Z)
        if hit is None:
            miss(b, 'hair_locks', part, (x, y, 10.0))
            continue
        base = hit - Z * sink
        if mirror and abs(x) <= 1e-6:
            base.x = 0.0
        R = tuft(b, part, base, base + Vector(off), w, col, tip_col=tip_col if lit else None, n=n, neck=0.55)
        if mirror and x > 1e-6:
            b._mirror_faces(_faces_of(R), b.pid(part))


def hair_mantle(b, part, path, widths, depths, col, tip_col=None, spike_len=0.11, spike_w=0.22, n=8, seal=True):
    """Long hair falling down the back: a wide, thin loft along `path` from a root buried in
    the cap, sections flattened across X (half widths `widths`, half depths `depths`), closing on a
    low apex, with a spiky end of tufts round the last ring (spike_w: tuft width / last width), their
    bases sealed: the thin end does not bury them.
    Returns rings (lists of BMVerts). Units: spike_len m, spike_w ratio."""
    from lpk.forms.fur import fur_fringe
    rings = [(p, wd, dp, {'p': 2.4}) for p, wd, dp in zip(path, widths, depths)]
    end = Vector(path[-1]) - Z * spike_len * 0.5
    R = b.loft(part, rings, n, X, col, cap1=end, col1=tip_col or col)
    fur_fringe(b, part, R[-1], (0, 0, -1), spike_len, widths[-1] * spike_w, col, tip_col=tip_col, out=0.25, step=1,
               seal=seal)
    return R


# The least area (m^2) a triangle of long_beard may have: below it a face reads as collapsed.
BEARD_MIN_AREA = 1e-8
# The depth a beard section keeps at its side edges, as a share of its centre depth, so its front and back
# never meet there.
BEARD_EDGE = 0.35


def _area(a, c, d):
    return (c - a).cross(d - a).length / 2


def _check_faces(rings, start, apex, what):
    """Raise ValueError naming the ring and column of the first band, start fan or apex triangle whose area
    falls below BEARD_MIN_AREA, a band quad for either diagonal a triangulation can take."""
    n = len(rings[0])
    for j in range(n):
        if _area(rings[0][j], rings[0][(j + 1) % n], start) < BEARD_MIN_AREA:
            raise ValueError('%s: the root row collapses at column %d: spread its rays (span, line) or lower '
                             'cols' % (what, j))
    for i in range(len(rings) - 1):
        for j in range(n):
            a, c, d, e = rings[i][j], rings[i][(j + 1) % n], rings[i + 1][(j + 1) % n], rings[i + 1][j]
            if min(_area(a, c, d), _area(a, d, e), _area(a, c, e), _area(c, d, e)) < BEARD_MIN_AREA:
                raise ValueError('%s: the face between rings %d and %d at column %d collapses (points %s); move '
                                 'the stations apart or widen the section' % (what, i, i + 1, j, [tuple(a), tuple(d)]))
    for j in range(n):
        if _area(rings[-1][j], rings[-1][(j + 1) % n], apex) < BEARD_MIN_AREA:
            raise ValueError('%s: the end cone collapses at column %d: move the tip off the last station' % (what, j))


def long_beard(b, part, bvh, center, line, tip, width, depth, color, stations=((0.25, 1.0), (0.6, 0.8), (0.85, 0.45)),
               cols=5, span=1.2, thick=0.01, inset=0.006, fork=None, tip_col=None, symmetric=False):
    """A long beard hanging below the chin: a root row along the jaw on the head, as head.face_shell lays its
    rows, then flat sections hanging in the air down and forward to `tip`, tapering, closing on the tip as a
    point or splitting into two locks.

    The root row: `cols` rays from `center` (the head centre) at azimuths from -span to +span (radians from
    the front, -Y, toward the model's left, +X, as hair_cap's directions) and the elevation line(phi)
    (radians below the centre's horizon negative; a number for one height all round) hit `bvh` (the head);
    each hit lifted `thick` along the surface normal makes the beard's front edge and sunk `inset` its back,
    so the row is a closed loop that shows the beard's thickness where it leaves the face; it closes on a
    fan to its centroid inside the head, which seals the thin gap between its front edge and the skin (as
    face_shell's rows close). A ray that misses
    puts its point 0.1 m out from the centre and is counted in the builder's probe misses (shapes.miss).
    The hanging part: each station (f, k) is a section on the line from the root's front midline point (the
    cast at azimuth 0) to `tip`, f of the way along it, half width `width` * k across X and half depth
    `depth` * k along Y; its front bulges toward -Y and its edges keep BEARD_EDGE of the depth. A small last
    k and a tip well past it make a point; a large last k close to the tip a blunt, rounded end. fork: None,
    or the half distance (m) across X between two tips: the mass then closes blunt just under its last
    station and two locks (fur.tuft) grow from inside it to tip +- fork * X, a split beard. symmetric: cast
    the +X half only and mirror it through x = 0 (as hair_cap), for a centre and a tip on the midline
    (ValueError otherwise). color: point_loft's, band i = 0 from the root row; the fork's locks take the end
    cone's colour (color(len(stations), 0, -Y) when color is a function), tip_col their tips.
    Returns the rings (lists of BMVerts), the root row first, 2 * cols points each (the front from -X to +X,
    then the back from +X to -X). 4 * cols * len(stations) + 4 * cols triangles, plus 4 * 3 per fork lock.

    Limits: every band and end triangle is checked, and one under BEARD_MIN_AREA raises ValueError naming
    its ring: stations that fall back onto the root, or a tip on the last station. The hanging part ignores
    the chest: a tip behind the chest's front passes through it."""
    c, tip = Vector(center), Vector(tip)
    if cols < 2 or not stations or width <= 0 or depth <= 0 or thick <= 0 or inset < 0:
        raise ValueError('long_beard: cols >= 2, one or more stations, positive width, depth and thick, inset >= 0 '
                         '(got %r, %r, %r, %r, %r, %r)' % (cols, stations, width, depth, thick, inset))
    fs = [f for f, _ in stations]
    if any(not 0 < f < 1 for f in fs) or fs != sorted(set(fs)) or any(k <= 0 for _, k in stations):
        raise ValueError('long_beard: stations need rising fractions f strictly between 0 and 1 and positive sizes '
                         '(got %r)' % (stations,))
    if symmetric and (abs(c.x) > 1e-6 or abs(tip.x) > 1e-6):
        raise ValueError('long_beard(symmetric=True) mirrors through x = 0: the centre and the tip must lie on it '
                         '(x %r, %r)' % (c.x, tip.x))
    elev = line if callable(line) else (lambda phi: line)

    def surf(phi):
        d = _dir(phi, elev(phi))
        hit, nrm, _, _ = bvh.ray_cast(c + d * 0.5, -d)
        if hit is None:
            miss(b, 'long_beard', part, c + d * 0.5)
            return c + d * 0.1, d
        return hit, nrm
    front, back = [], []
    for j in range(cols):
        if symmetric and 2 * j < cols - 1:
            front.append(None); back.append(None)
            continue
        p, nrm = surf(span * (2 * j / (cols - 1) - 1))
        f_, b_ = p + nrm * thick, p - nrm * inset
        if symmetric and 2 * j == cols - 1:
            f_.x = b_.x = 0.0
        front.append(f_); back.append(b_)
    if symmetric:
        for j in range(cols):
            if front[j] is None:
                q, r = front[cols - 1 - j], back[cols - 1 - j]
                front[j], back[j] = Vector((-q.x, q.y, q.z)), Vector((-r.x, r.y, r.z))
    rings = [front + list(reversed(back))]
    p, nrm = surf(0.0)
    root = p + nrm * thick
    if symmetric:
        root.x = 0.0
    us = [2 * j / (cols - 1) - 1 for j in range(cols)]
    for f, k in stations:
        o = root + (tip - root) * f
        w, dp = width * k, depth * k
        bulge = [BEARD_EDGE + (1 - BEARD_EDGE) * (1 - u * u) for u in us]
        ring = [Vector((o.x + w * u, o.y - dp * g, o.z)) for u, g in zip(us, bulge)]
        ring += [Vector((o.x + w * u, o.y + dp * g, o.z)) for u, g in reversed(list(zip(us, bulge)))]
        rings.append(ring)
    last_f, last_k = stations[-1]
    end = rings[-1]
    mid = sum(end, Vector()) / len(end)
    apex = tip if fork is None else mid + (tip - root).normalized() * (depth * last_k)
    start = sum(rings[0], Vector()) / len(rings[0])
    _check_faces(rings, start, apex, 'long_beard')
    R = point_loft(b, part, rings, color, cap0=start, cap1=apex)
    if fork is not None:
        prev_f = stations[-2][0] if len(stations) > 1 else 0.0
        base_c = root + (tip - root) * ((prev_f + last_f) / 2)
        lock_col = color if not callable(color) else color(len(rings) - 1, 0, Vector((0.0, -1.0, 0.0)))
        for sx in (-1.0, 1.0):
            base = base_c + X * (sx * width * last_k * 0.45)
            tuft(b, part, base, tip + X * (sx * fork), width * last_k * 0.4, lock_col, tip_col=tip_col,
                 thick=depth * last_k * 0.35, front=Y, n=4)
    return R
