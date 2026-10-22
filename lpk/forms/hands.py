"""Hands: chunky, slender and taloned hands, and the mitten with a split index finger."""
import math
from mathutils import Vector

from lpk.core.shapes import mark


X = Vector((1, 0, 0)); Y = Vector((0, 1, 0)); Z = Vector((0, 0, 1))


def chunky_hand(b, part, wrist, d, out, across, col, claw_col, palm_len, finger_len, half_w, thick=0.45,
                fingers=4, curl=0.35, digit_sides=3, finger_w=1.0, spread=0.0, claw=0.25):
    """Broad, thick hand with short closed fingers and claws, for stylised characters whose
    concept hands read as one heavy mass rather than spread digits.
    d: wrist-to-fingertip direction; out: back of the hand (fingers curl toward -out);
    across: palm width direction, thumb on its negative side. palm_len, finger_len: measured
    lengths; half_w: half the palm breadth; thick: palm thickness / breadth.
    finger_w < 1 thins the fingers so they separate, spread fans them across the palm, and
    claw is the claw length as a fraction of the finger length (long talons above ~0.4).
    Units: finger_len m, half_w m, thick ratio (palm thickness / breadth), finger_w ratio. The arguments
    wrist, d, out and across must be mathutils Vectors: they are not converted."""
    t = half_w * thick
    b.loft(part, [(wrist - d * 0.01, half_w * 0.78, t * 0.9, {'p': 2.6}),
                  (wrist + d * palm_len * 0.55, half_w, t * 1.05, {'p': 2.8}),
                  (wrist + d * palm_len, half_w * 0.98, t * 0.85, {'p': 2.8})],
           4, across, col, cap1='flat')
    fw = half_w / fingers                              # adjacent fingers just touch
    m = (fingers - 1) / 2
    for k in range(fingers):
        ln = finger_len * (0.86 if k in (0, fingers - 1) else 1.0)
        dk = (d + across * (spread * (k - m))).normalized()
        base = wrist + d * (palm_len - 0.004) + across * ((k - m) * fw * 2)
        mid = base + dk * (ln * 0.5) - out * (ln * curl * 0.35)
        tip = mid + (dk * 0.75 - out * curl).normalized() * (ln * 0.4)
        apex = tip + (dk * 0.5 - out * 0.8).normalized() * (ln * claw)
        w = fw * finger_w
        b.loft(part, [(base, w * 1.05, t * 0.75), (mid, w, t * 0.7), (tip, w * 0.8, t * 0.55)],
               digit_sides, across, col, cap1=apex, col1=claw_col)
    tb = wrist + d * (palm_len * 0.30) - across * (half_w * 0.85)          # thumb
    tm = tb + d * (finger_len * 0.45) - across * (half_w * 0.35) - out * (t * 0.3)
    tt = tm + d * (finger_len * 0.30) - out * (t * 0.4)
    w = fw * finger_w
    b.loft(part, [(tb, w * 1.2, t * 0.8), (tm, w * 1.05, t * 0.7), (tt, w * 0.85, t * 0.55)], digit_sides,
           across, col, cap1=tt + d * (finger_len * claw * 0.6) - out * (t * 0.5), col1=claw_col)


def slender_hand(b, part, wrist, d, out, across, col, nail_col, palm_len, finger_len, half_w, thick=0.42,
                 fingers=3, curl=0.22, finger_w=0.26, spread=0.12, nail=0.16, thumb=0.62, palm_sides=6):
    """Long, thin hand with few long jointed fingers ending in pointed nails (a Grey's hand), for
    concepts whose hands read by their length rather than their mass.
    d: wrist-to-fingertip direction; out: back of the hand (fingers curl toward -out); across: palm
    width direction, thumb on its negative side. palm_len, finger_len: measured lengths (the middle
    finger); half_w: half the palm breadth; thick: palm thickness / breadth; finger_w: finger half
    width / half_w. Each finger is a four-sided loft through two joints that narrows to a tip ring
    and closes on a nail apex `nail` x its length past it; the curl grows toward the tip. The fingers
    fan by `spread`; the thumb sits low on the -across side, angled out, `thumb` x the finger length.
    5 * palm_sides - 2 + 28 * (fingers + 1) triangles, the palm's flat end included.
    Units: finger_len m, half_w m, thick ratio (palm thickness / breadth), finger_w ratio, spread ratio,
    nail ratio. Curl is the bend in radians added at each joint, times 0.5, 1 and 1.5."""
    wrist = Vector(wrist); d = Vector(d).normalized(); out = Vector(out).normalized()
    across = Vector(across).normalized()
    t = half_w * thick
    b.loft(part, [(wrist - d * 0.012, half_w * 0.62, t * 0.85), (wrist + d * (palm_len * 0.5), half_w * 0.95, t),
                  (wrist + d * palm_len, half_w * 0.88, t * 0.78)], palm_sides, across, col, cap1='flat')
    w = half_w * finger_w
    m = (fingers - 1) / 2

    def digit(base, dk, ln, w_, side):
        pts = [base]
        seg = (0.40, 0.32, 0.28)                 # proximal, middle, distal share of the length
        bend = 0.0
        for k, f in enumerate(seg):
            bend += curl * (k + 1) * 0.5
            dirk = (dk * math.cos(bend) - out * math.sin(bend)).normalized()
            pts.append(pts[-1] + dirk * (ln * f * (1 - nail)))
        apex = pts[-1] + dirk * (ln * nail)
        rings = [(pts[0], w_, w_ * 0.9), (pts[1], w_ * 0.86, w_ * 0.8), (pts[2], w_ * 0.78, w_ * 0.72),
                 (pts[3], w_ * 0.6, w_ * 0.55)]
        b.loft(part, rings, 4, side, col, cap1=apex, col1=nail_col)
    for k in range(fingers):
        u = (k - m) / max(m, 1)                     # -1 on the thumb side, +1 on the outer edge
        ln = finger_len * (1.0 - 0.07 * abs(u) - 0.04 * max(u, 0))
        dk = (d + across * (spread * u)).normalized()
        base = wrist + d * (palm_len - 0.006) + across * (u * half_w * 0.62)
        digit(base, dk, ln, w, across)
    tb = wrist + d * (palm_len * 0.32) - across * (half_w * 0.72) - out * (t * 0.25)
    digit(tb, (d * 0.72 - across * 0.62 - out * 0.3).normalized(), finger_len * thumb, w * 1.1, across)


def talon(b, part, base, d, curl, length, width, depth, col, tip_col=None, bend=0.9, n=3, tip=0.25):
    """Long curved claw (a talon or a hooked nail) from `base`, leaving along d and bending toward `curl`
    through `bend` radians over its length on a circular arc. width runs across the curl plane, depth
    within it; the section narrows through a middle ring and a tip ring at 1 - tip, and the last
    `tip` of the length is the apex cone in tip_col (a pink-tipped claw). With three sides the
    section's point faces `curl`, so the inner edge reads as the blade. Base left open to be buried.
    n * 4 + n triangles.
    Returns rings (lists of BMVerts). Units: width m (half size), depth m (half size), tip ratio."""
    base = Vector(base); d = Vector(d).normalized()
    c = Vector(curl); c = (c - d * c.dot(d)).normalized()
    r = length / bend if bend > 1e-4 else None

    def at(t):
        if r is None:
            return base + d * (length * t)
        a = bend * t
        return base + d * (r * math.sin(a)) + c * (r * (1 - math.cos(a)))
    rings = [(at(0.0), depth, width), (at(0.45), depth * 0.72, width * 0.7), (at(1 - tip), depth * 0.42, width * 0.4)]
    return b.loft(part, rings, n, -c, col, cap1=at(1.0), col1=tip_col or col)


def talon_hand(b, part, wrist, d, out, across, col, claw_col, tip_col, palm_len, finger_len, claw_len, half_w,
               thick=0.42, fingers=4, curl=0.3, spread=0.16, finger_w=0.3, claw_bend=1.0, thumb=0.75, digit_sides=3,
               claw_curl=None):
    """Long hand ending in curved talons (a clawed monster's hand): a four-sided palm, `fingers` digits as
    lofts through a knuckle that curl toward -out, each closed flat and carrying a `talon` that keeps
    bending toward the palm, and a thumb low on the -across side angled away from the fingers.
    d: wrist-to-fingertip direction; out: back of the hand; palm_len, finger_len: measured lengths to the
    knuckles and to the end of the fingers (without the claw); claw_len: measured claw length; half_w:
    half the palm breadth; finger_w: finger half width / half_w. claw_curl: the direction the talons bend
    toward (default -out, into the palm); a share of -across hooks them toward the thumb side, so they also
    curve in the plane of the fanned fingers.
    18 + (fingers + 1) * (10 * digit_sides - 2) triangles (158 with four fingers): per digit its loft, its
    flat end and its talon.
    Units: finger_len m, thick ratio (palm thickness / breadth), curl ratio, spread ratio, claw_bend rad."""
    wrist = Vector(wrist); d = Vector(d).normalized(); out = Vector(out).normalized()
    across = Vector(across).normalized()
    t = half_w * thick
    b.loft(part, [(wrist - d * 0.02, half_w * 0.72, t * 0.9), (wrist + d * (palm_len * 0.55), half_w, t),
                  (wrist + d * palm_len, half_w * 0.94, t * 0.8)], 4, across, col, cap1='flat')
    w = half_w * finger_w
    m = (fingers - 1) / 2
    curl_dir = Vector(claw_curl) if claw_curl is not None else -out

    def digit(base, dk, ln, w_, th):
        k1 = base + dk * (ln * 0.5) - out * (ln * curl * 0.3)
        fd = (dk * (1 - curl) - out * curl).normalized()
        tip = k1 + fd * (ln * 0.5)
        b.loft(part, [(base, w_, th), (k1, w_ * 0.85, th * 0.82), (tip, w_ * 0.68, th * 0.62)], digit_sides, across,
               col, cap1='flat')
        talon(b, part, tip - fd * 0.008, fd, curl_dir, claw_len * (ln / finger_len), w_ * 0.62, th * 0.75, claw_col,
              tip_col=tip_col, bend=claw_bend, n=digit_sides)
    for k in range(fingers):
        u = (k - m) / max(m, 1)
        ln = finger_len * (1.0 - 0.1 * abs(u))
        dk = (d + across * (spread * u)).normalized()
        base = wrist + d * (palm_len - 0.012) + across * (u * half_w * 0.7)
        digit(base, dk, ln, w, t * 0.62)
    tb = wrist + d * (palm_len * 0.35) - across * (half_w * 0.8)
    digit(tb, (d * 0.65 - across * 0.6 - out * 0.25).normalized(), finger_len * thumb, w * 1.1, t * 0.6)


def fist_points(wrist, d, out, across, palm_len, finger_len, half_w, thick=0.45, curl=0.2, index_w=0.28, slit_w=0.07):
    """Key points of fist_mitten, also its bone ends: knuckle, finger mid, tip and apex; the
    thumb's base, middle, tip and apex; and the centres and half widths of the index finger (thumb
    side, -across) and of the three-finger block at the finger middle and the tip
    ('mid_index', 'tip_block', ...), their knuckle points and apexes.
    Returns {'t', 'knuckle', 'mid', 'tip', 'apex', 'thumb': four points, 'mid_index', 'mid_block',
    'tip_index', 'tip_block': (centre, half width), 'knuckle_index', 'knuckle_block', 'apex_index',
    'apex_block'}. Units: wrist m, d unit direction, out unit direction, across unit direction, palm_len m,
    finger_len m, half_w m, thick ratio (palm thickness / breadth), curl ratio, index_w ratio, slit_w
    ratio. The arguments wrist, d, out and across must be mathutils Vectors: they are not converted."""
    t = half_w * thick
    knuckle = wrist + d * palm_len
    mid = knuckle + d * (finger_len * 0.5) - out * (finger_len * curl * 0.35)
    tip = mid + (d * 0.75 - out * curl).normalized() * (finger_len * 0.4)
    apex = tip + (d * 0.5 - out * 0.8).normalized() * (finger_len * 0.12)
    tb = wrist + d * (palm_len * 0.28) - across * (half_w * 0.95)
    tm = tb + d * (finger_len * 0.45) - across * (half_w * 0.30) - out * (t * 0.3)
    tt = tm + d * (finger_len * 0.30) - out * (t * 0.4)
    k = dict(t=t, knuckle=knuckle, mid=mid, tip=tip, apex=apex,
             thumb=(tb, tm, tt, tt + d * (finger_len * 0.12) - out * (t * 0.3)))
    for key, scale in (('mid', 0.95), ('tip', 0.82)):
        W = half_w * scale * 0.78                       # corner offset of the superellipse sections
        i0, i1 = -W, -W + 2 * W * index_w
        b0 = -W + 2 * W * (index_w + slit_w)
        k[key + '_index'] = (k[key] + across * ((i0 + i1) / 2), (i1 - i0) / 2)
        k[key + '_block'] = (k[key] + across * ((b0 + W) / 2), (W - b0) / 2)
    for f in ('index', 'block'):
        k['knuckle_' + f] = knuckle + across * (k['mid_' + f][0] - mid).dot(across)
        k['apex_' + f] = k['tip_' + f][0] + (d * 0.5 - out * 0.8).normalized() * (finger_len * 0.12)
    return k


def fist_mitten(b, part, wrist, d, out, across, col, palm_len, finger_len, half_w, thick=0.45, curl=0.2,
                index_w=0.28, slit_w=0.07, claws=None, finger_col=None):
    """Mitten fist after a reference mitten hand: one shell from the wrist over the palm to the
    knuckles, where it splits into the index finger (thumb side, index_w of the width) and a block
    of the other three, with a slit (slit_w) over the outer half of the fingers and a floor face at
    its root; four sides throughout. The thumb grows out of the palm's thumb-side face in two
    segments, so the hand stays one surface. claws=(colour, length as a fraction of finger_len)
    adds three-sided claw pyramids on the index, along the block's tip and on the thumb. Finger
    gaps are painted (mitten_finger_lines). finger_col colours the fingers from the knuckles and the
    thumb (a fingerless glove). Takes the chunky_hand frame and lengths; bones (from
    fist_points): Hand to the knuckles, Index, Middle (the block), Thumb. 87 triangles with claws.
    thick: the palm's thickness over its breadth (its half thickness over half_w), a ratio, not
    metres. The wrist end is open: a rounded-box section (superellipse exponent 2.6) centred 1 cm
    before `wrist`, half_w * 0.78 across (its half width) and thick * half_w * 0.9 from the back to
    the palm (its half thickness). End the arm's last ring inside it, flattened along `out`, or the
    forearm shows at the opening.
    Returns the fist_points dict. Units: d unit direction, out unit direction, palm_len m, curl ratio,
    index_w ratio, slit_w ratio. The arguments wrist, d, out and across must be mathutils Vectors: they are
    not converted."""
    import bmesh
    fc = finger_col or col
    k = fist_points(wrist, d, out, across, palm_len, finger_len, half_w, thick, curl, index_w, slit_w)
    t = k['t']
    R = b.loft(part, [(wrist - d * 0.01, half_w * 0.78, t * 0.9, {'p': 2.6}),
                      (wrist + d * palm_len * 0.55, half_w, t * 1.05, {'p': 2.8}),
                      (k['knuckle'], half_w * 0.98, t * 0.9, {'p': 2.8})],
               4, across, col)
    pid = b.pid(part)
    rel = lambda v: ((v.co - k['knuckle']).dot(across), (v.co - k['knuckle']).dot(out))
    back = [v for v in R[-1] if rel(v)[1] > 0]
    palm = [v for v in R[-1] if rel(v)[1] < 0]
    A, B = min(back, key=lambda v: rel(v)[0]), max(back, key=lambda v: rel(v)[0])
    D, C = min(palm, key=lambda v: rel(v)[0]), max(palm, key=lambda v: rel(v)[0])

    def ring(centre, hw, hh, fd):
        # Corners: thumb-back, outer-back, outer-palm, thumb-palm, square to the finger direction fd.
        up = (out - fd * out.dot(fd)).normalized()
        a = (across - fd * across.dot(fd)).normalized()
        return [b.vert(centre + a * sa * hw + up * su * hh, pid) for sa, su in ((-1, 1), (1, 1), (1, -1), (-1, -1))]
    dm = (k['mid'] - k['knuckle']).normalized()
    dt = (k['tip'] - k['mid']).normalized()
    hm, ht = t * 0.75 * 0.78, t * 0.55 * 0.78
    Mi = ring(k['mid_index'][0], k['mid_index'][1], hm, dm)
    Mb = ring(k['mid_block'][0], k['mid_block'][1], hm, dm)
    hint = (k['knuckle'] + k['mid']) / 2
    # The knuckle ring's back and palm edges fan over the slit to both fingers' first rings.
    A1, S1, S4, D1 = Mi
    S2, B1, C1, S3 = Mb
    for f in ([A, B, S2, S1], [A, S1, A1], [B, B1, S2],
              [D, S4, S3, C], [D, D1, S4], [C, S3, C1],
              [A, A1, D1, D], [B, C, C1, B1]):
        b.face(f, fc, hint=hint)
    b.face([S1, S2, S3, S4], fc, hint=k['knuckle'])               # slit floor
    for name, M in (('index', Mi), ('block', Mb)):
        c, hw = k['tip_' + name]
        T = ring(c, hw * 0.9, ht, dt)
        h2 = (k['mid_' + name][0] + c) / 2
        for j in range(4):
            b.face([M[j], M[(j + 1) % 4], T[(j + 1) % 4], T[j]], fc, hint=h2)
        ap = b.vert(k['apex_' + name], pid)
        for j in range(4):
            b.face([T[j], T[(j + 1) % 4], ap], fc, hint=c)
    ring01 = set(R[0]) | set(R[1])
    cands = [f for f in b.bm.faces if all(v in ring01 for v in f.verts) and len(f.verts) == 4]
    face = max(cands, key=lambda f: (f.calc_center_median() - wrist).dot(-across))
    quad = list(face.verts)
    c0 = face.calc_center_median()
    n0 = (c0 - (wrist + d * (palm_len * 0.27))).normalized()
    bmesh.ops.delete(b.bm, geom=[face], context='FACES_ONLY')
    # Thumb sections keep the face's corner layout and turn from the face normal toward each
    # segment's direction, so the first segment grows out of the palm without a twist.
    u = d - n0 * d.dot(n0); u.normalize(); v = n0.cross(u)
    offs = [q.co - c0 for q in quad]
    mu = max(abs(o.dot(u)) for o in offs); mv = max(abs(o.dot(v)) for o in offs)
    unit = [(o.dot(u) / mu, o.dot(v) / mv) for o in offs]
    tb, tm, tt, tapex = k['thumb']
    fw = half_w / 4
    rings = [quad]
    for centre, prev, hu, hv in ((tm, c0, fw * 1.15, t * 0.62), (tt, tm, fw * 0.85, t * 0.45)):
        rot = n0.rotation_difference((centre - prev).normalized())
        ru, rv = rot @ u, rot @ v
        rings.append([b.vert(centre + ru * (a * hu) + rv * (cc * hv), pid) for a, cc in unit])
    cents = [c0, tm, tt]
    for i in range(2):
        P0, P1 = rings[i], rings[i + 1]
        hh = (cents[i] + cents[i + 1]) / 2
        for j in range(4):
            b.face([P0[j], P0[(j + 1) % 4], P1[(j + 1) % 4], P1[j]], fc, hint=hh)
    ap = b.vert(tapex, pid)
    for j in range(4):
        b.face([rings[2][j], rings[2][(j + 1) % 4], ap], fc, hint=tt)
    if claws:
        ccol, clen = claws
        L = finger_len * clen
        down = (d * 0.55 - out * 0.85).normalized()
        roots = [(k['apex_index'], k['tip_index'][1] * 0.65, down)]
        cb, hwb = k['tip_block']
        for s in (-2 / 3, 0.0, 2 / 3):                     # the three fingers' centres
            roots.append((cb + across * (hwb * s) + (k['apex_block'] - cb) * 0.7, hwb * 0.33, down))
        roots.append((tapex, fw * 0.6, ((tapex - tt).normalized() - out * 0.5).normalized()))   # along the thumb
        for root, r, dirc in roots:
            e1 = (across - dirc * across.dot(dirc)).normalized(); e2 = dirc.cross(e1)
            base = [root - dirc * (L * 0.15) + e1 * (r * math.cos(a)) + e2 * (r * 0.8 * math.sin(a))
                    for a in (math.radians(90), math.radians(210), math.radians(330))]
            b.pyramid(part, base, root + dirc * L, ccol)
    return k


def mitten_finger_lines(b, part, wrist, d, out, across, col, palm_len, finger_len, half_w, thick=0.45, curl=0.2,
                        index_w=0.28, slit_w=0.07, width=0.006, lift=0.003, steps=4):
    """Colour source for fist_mitten: lines on the back and the palm side where the fingers part,
    the slit's line from the knuckles to the slit's root and two lines between the block's three
    fingers from the knuckles to the tip. Each point is a ray hit on a scratch copy of the mitten,
    lifted by `lift`, `steps` points per span. `width` times the hand's texels per metre must reach one
    texel, or the lines bake as dashes (lpk.stages.texture.MIN_LINE_TEXELS): a texel boost on the hand
    part raises the density.
    Units: wrist m, d unit direction, out unit direction, across unit direction, palm_len m, finger_len m,
    half_w m, thick ratio (palm thickness / breadth), curl ratio, index_w ratio, slit_w ratio. The
    arguments wrist, d, out and across must be mathutils Vectors: they are not converted; it casts onto a
    scratch fist_mitten built from the same arguments."""
    from mathutils.bvhtree import BVHTree
    from lpk.core.builder import Builder
    tmp = Builder(b.palette)
    k = fist_mitten(tmp, 'm', wrist, d, out, across, col, palm_len, finger_len, half_w, thick, curl, index_w, slit_w)
    bvh = BVHTree.FromBMesh(tmp.bm)
    tmp.bm.free()
    pid = b.pid(part)
    secs = [(k['knuckle'], half_w * 0.98 * 0.78), (k['mid'], half_w * 0.95 * 0.78), (k['tip'], half_w * 0.82 * 0.78)]
    b0 = -1 + 2 * (index_w + slit_w)
    lines = [(-1 + 2 * (index_w + slit_w / 2), 1)] + [(b0 + (1 - b0) * f, 2) for f in (1 / 3, 2 / 3)]
    for x, last in lines:                              # across position (-1 thumb side .. 1), last section
        samples = []
        for i in range(last):
            (c0, w0), (c1, w1) = secs[i], secs[i + 1]
            for j in range(steps + (1 if i == last - 1 else 0)):
                f = j / steps
                samples.append((c0.lerp(c1, f), w0 + (w1 - w0) * f, (c1 - c0).normalized()))
        for side in (1, -1):                           # back, palm
            rows = []
            for c, w, fd in samples:
                up = (out - fd * out.dot(fd)).normalized() * side
                a = (across - fd * across.dot(fd)).normalized()
                row = []
                for o in (-width / 2, width / 2):
                    hit, nrm, _, _ = bvh.ray_cast(c + a * (x * w + o) + up * 0.05, -up, 0.1)
                    row.append(None if hit is None else b.vert(hit + nrm * lift, pid))
                rows.append(row)
            for r0, r1 in zip(rows, rows[1:]):
                if all(r0) and all(r1):
                    b.face([r0[0], r0[1], r1[1], r1[0]], col, hint=k['knuckle'])
            centres = [(r[0].co + r[1].co) / 2 for r in rows if all(r)]
            if centres:
                mark(b, 'mitten_finger_lines', part, width, centres)
