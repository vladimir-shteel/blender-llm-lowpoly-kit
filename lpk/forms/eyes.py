"""Eyes laid over a head surface."""
import math
from mathutils import Vector

from lpk.core.shapes import mark, miss
from lpk.forms.fur import tuft

X = Vector((1, 0, 0)); Y = Vector((0, 1, 0)); Z = Vector((0, 0, 1))


def socket_eyes(b, part, bvh, eye_line, eye_x, radius, iris, dark, lid, brow=None, mask=None, n=8, inset=0.45,
                lid_lift=0.006, lid_drop=0.008, aspect=0.72):
    """Volumetric eyes laid over a head facing -Y: a raised lid ring around a shallow eyeball
    dome, so the eye reads as sitting in a socket without cutting the head's topology.
    Per eye, from outside in: rim ring A on the surface, lid crest B raised by lid_lift (the
    upper half more and pulled inward by lid_drop, a heavy upper lid), inner lip C dropping
    back toward the surface, an iris ring D and a pupil apex. ~56 triangles per eye with n=8.
    radius: eye half width; aspect: height / width. inset: eye centre as a fraction of eye_x
    from the midline (lower = closer-set, more forward-looking). lid / brow colour the lid
    ring and an optional brow tuft above it; mask colours an optional dark patch that runs from
    under the eye down toward the snout (the mask of a raccoon). The patch is sized by the eye:
    a narrowed eye shrinks it to a ring, and made large, the flat patch sinks into the skull; a mask
    sized by the head belongs to the head's own face colours.
    Units: eye_line m (y, z), lid_lift m, lid_drop m. An eye whose ray misses bvh is skipped and counted in
    the builder's probe misses (shapes.miss)."""
    ey, ez = eye_line
    pid = b.pid(part)
    ph = math.pi / n
    for sx in (-1, 1):
        target = Vector((sx * eye_x * inset, ey, ez))
        out_dir = Vector((sx * 0.5, -1.0, 0.1)).normalized()
        hit, nrm, _, _ = bvh.ray_cast(target + out_dir * 0.3, -out_dir)
        if hit is None:
            miss(b, 'socket_eyes', part, target)
            continue
        t = Z.cross(nrm); t = (t if t.length > 1e-4 else X).normalized() * sx   # away from the midline
        u = nrm.cross(t).normalized() * sx                                     # up along the surface

        def ring(scale, lift, upper_lift=0.0, upper_in=0.0):
            pts, ups = [], []
            for j in range(n):
                th = ph + 2 * math.pi * j / n
                c, s = math.cos(th), math.sin(th)
                up = max(0.0, s)
                p = hit + t * (c * radius * scale) + u * (s * radius * aspect * scale - up * upper_in)
                hp, hn, _, _ = bvh.find_nearest(p)
                base = hp if hp is not None else p
                pts.append(b.vert(base + nrm * (lift + upper_lift * up), pid))
            return pts
        if mask:
            o = hit + nrm * 0.0015
            r = radius
            b.decal(part, [o + u * (r * 0.9) - t * (r * 1.3), o + u * (r * 1.0) + t * (r * 1.8),
                           o - u * (r * 0.6) + t * (r * 1.5), o - u * (r * 2.3) - t * (r * 1.2)], mask, nrm)
        A = ring(1.45, 0.001)
        B = ring(1.12, lid_lift, lid_lift, lid_drop)
        C = ring(0.98, lid_lift * 0.35, 0.0, lid_drop * 0.8)
        D = ring(0.55, lid_lift * 0.75)
        apex = b.vert(hit + nrm * (lid_lift * 0.95), pid)
        faces = []
        for R0, R1, col in ((A, B, lid), (B, C, lid), (C, D, iris)):
            for j in range(n):
                faces.append(b.face([R0[j], R0[(j + 1) % n], R1[(j + 1) % n], R1[j]], col))
        for j in range(n):
            faces.append(b.face([D[j], D[(j + 1) % n], apex], dark))
        # Oriented as one sheet: a heavy upper lid can drop the inner lip C below the iris ring D,
        # folding that band back on itself, and flipping face by face would break the winding at the fold.
        for f in faces:
            f.normal_update()
        if sum(f.normal.dot(nrm) * f.calc_area() for f in faces) < 0:
            for f in faces:
                f.normal_flip()
        if brow:
            c0 = hit + u * (radius * aspect * 1.25) - t * (radius * 0.6) + nrm * 0.002
            tuft(b, part, c0, c0 + t * (radius * 1.9) + u * (radius * 0.35) + nrm * (radius * 0.25),
                 radius * 0.32, brow, thick=radius * 0.18, front=nrm)
        mark(b, 'socket_eyes', part, 2 * radius, [hit], kind='eye')


def traced_eye(builders, part, bvh, layers, direction=Y, mirror=True, rings=3, lift=0.0015):
    """An eye traced off a front view, as flat colour layers cast onto the head: socket_eyes builds
    a round, lidded eye; drawn eyes (an almond with a heavy liner and a wing) keep their outline this
    way. layers: [(outline, colour)] back to front, outlines as model-space points in front of the
    face (views.Calib.model), each cast along `direction` with shapes.fan_decal through `rings`
    rings so it follows the surface. builders: one per layer, each a colour source of its own:
    the bake lays later sources over earlier ones, so the layers sit at the same lift instead of
    stacked a fraction of a millimetre apart (stacked, they cut into each other and into the head).
    mirror repeats every layer at -x for the other eye. Keep the outline within ~0.5 m in front of
    every surface it should land on: fan_decal casts from 0.5 m behind the point over 1 m, and a ray
    that falls short snaps to the nearest surface point (from far in front of a face, the nose tip).
    Returns the number of outline points whose ray misses `bvh` (they land wrong; 0 expected).
    With mirror=False it builds one side only."""
    from lpk.core.shapes import fan_decal
    d = Vector(direction).normalized()
    missed = 0
    width = 0.0
    for bld, (outline, col) in zip(builders, layers):
        pts = [Vector(p) for p in outline]
        missed += sum(1 for p in pts if bvh.ray_cast(p - d * 0.5, d, 1.0)[0] is None)
        fan_decal(bld, part, bvh, pts, direction, col, lift=lift, rings=rings)
        if mirror:
            fan_decal(bld, part, bvh, [Vector((-p.x, p.y, p.z)) for p in reversed(pts)], direction, col, lift=lift,
                      rings=rings)
        flat = [p - d * p.dot(d) for p in pts]
        width = max([width] + [(p - q).length for p in flat for q in flat])
    if layers:
        c = sum((Vector(p) for p in layers[0][0]), Vector()) / len(layers[0][0])
        hit = bvh.ray_cast(c - d * 0.5, d, 1.0)[0]
        if hit is not None:
            mark(builders[0], 'traced_eye', part, width, [hit], kind='eye')
            if mirror:
                mark(builders[0], 'traced_eye', part, width, [Vector((-hit.x, hit.y, hit.z))], kind='eye')
    return missed


def bevel_eye(layers, part, bvh, centre, direction, along, side, lift=0.003):
    """An almond eye cast onto a head from `direction` (from above and outside: on a long head the
    eye sits on the bevel between the top and the side, where the front and the profile views both
    see it; each view's outline cast along its own axis can land somewhere else on the head, so one
    direction serves both views: check that the front and the profile capture show the same eye).
    layers: ((length, height, tilt), colour, builder) back to front, the length along `along` (the
    head's forward axis) and the tilt raising the front corner; side flips the outline for a mirror
    pair (1 for +X).
    Units: layers ((m, m, ratio), colour, builder), centre m, side sign, lift m."""
    from lpk.core.shapes import fan_decal
    d = Vector(direction).normalized()
    u = (Vector(along) - d * Vector(along).dot(d)).normalized(); v = d.cross(u) * side
    for (ln, ht, tilt), col, bld in layers:
        pts = [centre - d * 0.1 + u * (ln / 2 * math.cos(t)) + v * (ht / 2 * math.sin(t) ** 3 + ht * 0.25 * math.sin(t)
                                                                    + tilt * ln / 2 * math.cos(t))
               for t in [k * 2 * math.pi / 10 for k in range(10)]]
        fan_decal(bld, part, bvh, pts, d, col, lift=lift, rings=2)
    if layers:
        hit = bvh.ray_cast(centre - d * 0.6, d, 1.0)[0]
        if hit is not None:
            mark(layers[0][2], 'bevel_eye', part, max(ln for (ln, _, _), _, _ in layers), [hit], kind='eye')
