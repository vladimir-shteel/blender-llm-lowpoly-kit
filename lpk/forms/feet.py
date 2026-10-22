"""Feet: paws and boots."""
import math
from mathutils import Vector

from lpk.core.builder import loft_points


X = Vector((1, 0, 0)); Y = Vector((0, 1, 0)); Z = Vector((0, 0, 1))


def _part_verts(b, part):
    """The set of the vertices `part` holds now, for _ground_new."""
    pid = b.pid(part)
    return {v for v in b.bm.verts if v[b.vpart] == pid}


def _ground_new(b, part, old):
    """Move the vertices of `part` that are not in `old` straight up or down so that the lowest of them
    sits on the floor, z = 0, and return the shift in metres: a form grounds what it built and leaves
    what the part held before where it was."""
    pid = b.pid(part)
    new = [v for v in b.bm.verts if v[b.vpart] == pid and v not in old]
    dz = -min(v.co.z for v in new)
    for v in new:
        v.co.z += dz
    return dz


def platform_boot(b, part, x, sx, ankle_z, col, sole_col, length=0.30, width=0.062, sole_h=0.055, heel_y=0.07,
                  sole_top_col=None, sole_w=1.0):
    """Platform boot, toe toward -Y: a boxy sole slab (its sides take sole_col, a rim band) and
    a rounded upper from the ankle over the instep to a blunt toe apex resting on the slab.
    sx: +1 left foot, -1 right foot. sole_w widens the slab past the upper. The ankle is taken at
    y = 0: heel_y is the sole's back end behind it and length runs from there to the toe. The sole
    overhangs at the heel: the upper's first rings sit 6 and 7.5 cm in front of heel_y whatever heel_y
    is and lean forward from the ankle, so the upper's back reaches heel_y only near the ankle and
    stands about 3 to 4.5 cm in front of the sole's end at the sole's top (the vertex positions for
    ankle_z 0.12 to 0.08 m, the rest at the defaults).
    The boot stands on the floor: the heights are laid out with the sole's nominal bottom at z = 0, and
    the slab's lowest vertices, its superellipse corners, stand above that bottom (4.4 mm at the
    defaults), so once built the boot moves straight down until its lowest vertex sits on z = 0
    (Builder.ground_part's rule on the boot's own vertices; what the part held before stays). ankle_z
    moves with it.
    Units: x m, sx sign, length m, width m (half size), sole_h m, heel_y m, sole_w ratio."""
    old = _part_verts(b, part)
    toe_y = heel_y - length
    top = sole_top_col or col

    def sole_c(i, j, d):
        return top if abs(d.z) > 0.7 else sole_col
    sw = width * sole_w
    b.loft(part, [((x, heel_y, sole_h / 2), sole_h / 2, sw * 0.92, {'p': 4}),          # a = Z: height first
                  ((x + sx * 0.004, heel_y - length * 0.55, sole_h / 2), sole_h / 2, sw * 1.05, {'p': 4}),
                  ((x + sx * 0.008, toe_y, sole_h / 2), sole_h / 2, sw * 0.95, {'p': 4})],
           4, Vector((0, 0, 1)), sole_c, cap0='flat', cap1='flat', col0=sole_col, col1=sole_col)
    z0 = sole_h - 0.004
    b.loft(part, [((x, heel_y - 0.06, ankle_z + 0.06), width * 0.85, width * 0.85),
                  ((x, heel_y - 0.075, z0 + 0.06), width * 0.95, width * 0.95),
                  ((x + sx * 0.004, heel_y - length * 0.55, z0 + 0.035), width * 0.98, 0.04),
                  ((x + sx * 0.008, toe_y + 0.035, z0 + 0.022), width * 0.85, 0.024)],
           6, X, col, cap0='flat', cap1=(x + sx * 0.008, toe_y + 0.004, z0 + 0.01))
    _ground_new(b, part, old)


def _work_boot_lofts(x, top_z, length, width, sole_h, heel_y, shaft_r, cuff, band_h):
    """work_boot's three lofts as laid out, its sole's nominal bottom at z = 0: [(rings, sides, ref,
    keywords)] for the sole slab, the shaft and the foot upper, the keywords those of Builder.loft besides
    the colours (the caps, the axis). Units as work_boot's."""
    toe_y = heel_y - length
    z0 = sole_h - 0.014
    box = {'p': 3}
    return [([((x, heel_y + 0.004, sole_h / 2), sole_h / 2, width * 1.04, {'p': 4}),     # a = Z: height first
              ((x, heel_y - length * 0.55, sole_h / 2), sole_h / 2, width * 1.1, {'p': 4}),
              ((x, toe_y + 0.01, sole_h / 2), sole_h / 2, width * 0.98, {'p': 4})],
             4, Z, {'cap0': 'flat', 'cap1': 'flat'}),
            ([((x, 0.008, top_z), shaft_r * cuff, shaft_r * cuff),
              ((x, 0.008, top_z - band_h), shaft_r, shaft_r),
              ((x, 0.012, z0 + 0.1), shaft_r * 0.94, shaft_r * 0.98)],
             6, X, {'cap0': 'flat'}),
            ([((x, heel_y - 0.004, z0 + 0.06), 0.06, width * 0.86, box),                 # a = Z: height first
              ((x, heel_y - 0.055, z0 + 0.085), 0.085, width * 0.98, box),
              ((x, heel_y - length * 0.52, z0 + 0.06), 0.06, width * 1.0, box),
              ((x, toe_y + 0.03, z0 + 0.042), 0.042, width * 0.95, box)],
             8, Z, {'cap0': (x, heel_y + 0.008, z0 + 0.06), 'cap1': 'flat', 'axis': -Y})]


def _work_boot_points(x, length, sole_h, heel_y, lofts, dz):
    """work_boot_points' points of the boot laid out by `lofts` (_work_boot_lofts), moved up by `dz` (m)."""
    toe_y = heel_y - length
    top = sole_h + dz
    shaft, upper = lofts[1][0], lofts[2]
    lift = lambda p: (p[0], p[1], p[2] + dz)
    return {'ankle': lift(shaft[-1][0]), 'top': lift(shaft[0][0]), 'heel': lift(upper[3]['cap0']),
            'ball': (x, heel_y - length * 0.62, top), 'toe': (x, toe_y + 0.02, top), 'ground': dz}


def work_boot_points(x, top_z, length=0.27, width=0.06, sole_h=0.035, heel_y=0.065, shaft_r=0.062, cuff=1.04,
                     band_h=0.04):
    """The points of the work_boot these arguments build, without building it: what a rig binds the foot
    to. Returns {'ankle': the centre of the shaft's lowest ring, over the ankle (y = 0); 'top': the centre
    of the shaft's top ring; 'heel': the heel counter's apex; 'ball', 'toe': the ball and toe points on the
    top of the sole that work_boot returns; 'ground': the shift (m) that stands the boot on the floor}, each
    point an (x, y, z) tuple in metres, moved with that shift. The shift comes from the ring vertices
    Builder.loft lays (lpk.core.builder.loft_points) in double precision, the built boot's from its stored
    single-precision vertices: the two agree to float32 rounding. Units as work_boot's."""
    lofts = _work_boot_lofts(x, top_z, length, width, sole_h, heel_y, shaft_r, cuff, band_h)
    low = []
    for rings, n, ref, kw in lofts:
        low.extend(p[2] for ring in loft_points(rings, n, ref, kw.get('axis'))[1] for p in ring)
        low.extend(c[2] for c in (kw.get('cap0'), kw.get('cap1')) if isinstance(c, tuple))
    return _work_boot_points(x, length, sole_h, heel_y, lofts, -min(low))


def work_boot(b, part, x, top_z, col, sole_col, tread_col, band_col=None, length=0.27, width=0.06, sole_h=0.035,
              heel_y=0.065, shaft_r=0.062, cap_col=None, cuff=1.04, band_h=0.04):
    """Heavy lace-up boot to mid-calf, toe toward -Y: a lug sole slab (sides sole_col, tread
    underneath), a six-sided shaft from `top_z` down to the sole with an optional band at its top
    (a strap), and a boxy foot upper from the heel counter over the instep to a flat toe cap in
    cap_col (None: sole_col, the rand wrapping the toe). The upper sinks into the sole so it meets it
    at its full width: a narrower bottom would leave a shelf of sole showing round it. The shaft sits over
    the ankle (y = 0), the heel counter behind it. ~110 triangles.
    cuff: the shaft's top ring over shaft_r, the flare of its top (1.0 for a straight shaft); band_h:
    the height of the shaft's top band, from its top ring down to the next, the band band_col paints.
    The boot stands on the floor: the heights are laid out with the sole's nominal bottom at z = 0, and
    the slab's lowest vertices, its superellipse corners, stand above that bottom (2.8 mm at the
    defaults), so once built the boot moves straight down until its lowest vertex sits on z = 0
    (Builder.ground_part's rule on the boot's own vertices; what the part held before stays). top_z
    moves with it. Returns the ball and toe points on the top of the sole, moved with the boot.
    work_boot_points gives these points and the ankle, shaft top and heel without building, for a rig
    whose bones are placed before the build.
    Units: x m, top_z m, length m, width m (half size), sole_h m, heel_y m, shaft_r m, cuff ratio, band_h
    m. No side parameter: the boot is symmetric about its own x."""
    old = _part_verts(b, part)
    lofts = _work_boot_lofts(x, top_z, length, width, sole_h, heel_y, shaft_r, cuff, band_h)
    (sole, n_sole, ref_sole, kw_sole), (shaft, n_shaft, ref_shaft, kw_shaft), (upper, n_up, ref_up, kw_up) = lofts

    def sole_c(i, j, d):
        return tread_col if d.z < -0.7 else sole_col
    b.loft(part, sole, n_sole, ref_sole, sole_c, col0=sole_col, col1=sole_col, **kw_sole)
    b.loft(part, shaft, n_shaft, ref_shaft, lambda i, j, d: band_col if (band_col and i == 0) else col, col0=col,
           **kw_shaft)
    b.loft(part, upper, n_up, ref_up, col, col1=cap_col or sole_col, **kw_up)
    k = _work_boot_points(x, length, sole_h, heel_y, lofts, _ground_new(b, part, old))
    return Vector(k['ball']), Vector(k['toe'])


def strap_paw(b, part, x, sx, ankle_z, col, claw_col, length=0.25, width=0.066, toes=4, digit_sides=3):
    """Long hind paw from a raised ankle down to the ground, toes pointing -Y: a fur column under the
    trouser cuff, one strap ring, an instep and clawed toes that stay geometry for the silhouette.
    sx: +1 left foot, -1 right foot. Returns the rings above, at and below the strap (point lists)
    for lpk.core.shapes.ring_band, which paints the strap. Its ankle column, its heights and its toes'
    sections are fixed in metres; `width` and `length` scale the instep, the ball and the toes' spread
    and reach: compare the paw with the drawing before styling round it. The toes are paw_toes with
    those fixed sections. The ankle is taken at y = 0 and the column drops straight to the instep:
    Builder.move_part sets the paw under an ankle elsewhere. The returned points are copies taken
    where the paw was built and stay there when the part moves: add the move_part offset, and the
    shift Builder.ground_part returns, to every point before passing them to ring_band, or the band
    is built where the paw was.
    Units: x m, sx sign, ankle_z m."""
    ball = -0.03 - length * 0.42
    toe = length * 0.30
    strap_z = min(0.12, ankle_z * 0.45)
    R = b.loft(part, [((x, 0.020, ankle_z + 0.02), 0.046, 0.046), ((x, -0.002, strap_z), 0.057, 0.056),
                      ((x, -0.035, 0.045), width * 0.9, 0.045), ((x + sx * 0.004, ball, 0.024), width, 0.024)],
               6, X, col, cap1='flat', col1=col)
    paw_toes(b, part, (x + sx * 0.004, ball, 0.020), (x + sx * 0.004, ball - toe, 0.013),
             ((0.015, 0.015), (0.012, 0.010)), width * 1.6 / toes, 0.035, col, claw_col, toes=toes,
             digit_sides=digit_sides)
    return [[v.co.copy() for v in r] for r in R[:3]]


def paw_toes(b, part, ball, tip, sections, spacing, claw_len, col, claw_col, toes=4, digit_sides=3, claw_z=0.0):
    """A mammal's clawed digits in a row across X, pointing -Y: each digit a loft from its ring at the
    ball to its ring at the tip, closing on an apex claw in claw_col. ball and tip: (x, y, z), the
    centres of the middle of the row at the ball and at the tip; digit k sits (k - (toes - 1) / 2) *
    spacing along X from both, so spacing is the distance between neighbouring digits' centre lines.
    sections: ((half width, half height) of a digit's ring at the ball, (half width, half height) at
    the tip), the digit's own thickness, given because the animal sets it. Both values are
    Builder.loft's radii, apothems (the distances from the ring's centre to its flat sides), not the
    half extents of the built digit: compare the built digit with the drawing's toes rather than
    passing the drawn half width and half height as they are. With an even digit_sides a digit spans
    two half widths across X, one each side of its centre line. With an odd one a flat side faces +X
    and a corner -X: the digit reaches one half width toward +X and 1 / cos(pi / digit_sides) half
    widths toward -X; with three sides that is two, so the digit spans three half widths, two of
    them toward -X, and its lowest vertex, a corner 60 degrees below +X, sits about 1.7 half heights
    below its centre. Neighbours overlap, and read as one mass, once a digit's span across X passes
    spacing: a half width over half of spacing with an even digit_sides, over a third of it with
    three sides. claw_len: how far each claw's apex reaches past the tip ring toward -Y; claw_z: the
    apex's height (0 puts the claw's point on the floor). The ball ring stays open: bury it in the
    instep, or in the leg's end on a digitigrade leg. A ring's lowest vertex can sit further below its
    centre than its half height, so the digits can dip under a claw on the floor: ground the toes'
    part with Builder.ground_part where the floor row lists it. Returns each digit's rings, from -X
    to +X.
    Units: claw_len m, claw_z m. No side parameter: the row is symmetric about its middle; with an odd
    digit_sides a digit is not symmetric about its own centre line, so build one foot and copy it with
    Builder.mirror_part."""
    bx, by, bz = ball
    tx, ty, tz = tip
    (w0, h0), (w1, h1) = sections
    m = (toes - 1) / 2
    rings = []
    for k in range(toes):
        dx = (k - m) * spacing
        rings.append(b.loft(part, [((bx + dx, by, bz), w0, h0), ((tx + dx, ty, tz), w1, h1)], digit_sides, X, col,
                            cap1=(tx + dx, ty - claw_len, claw_z), col1=claw_col))
    return rings


def mitt_paw(b, part, heel, toe, width, height, col, claw_col, claws=4, claw_len=0.035, n=8):
    """A puffy paw standing on the floor (a furry mammal's paw): a rounded mitt from `heel` to `toe`
    (floor points; the leg's last ring goes in from above at the heel), half `width` across and
    `height` tall, flat underneath, highest a third along and lowering to the toes, with `claws`
    peeking out at the front. Returns the rings.
    The form leaves the paw where the floor points put it, and its lowest vertex is not on their
    height: the mitt's rings are superellipses whose bottom vertices stand a few millimetres above it,
    and the claws, whose sections are fixed in metres, dip under it on a paw lower than about 0.13 m.
    Builder.ground_part(part) after the paw (and before Builder.mirror_part) puts the part's lowest
    vertex on the floor.
    Units: heel m, toe m, width m (half size), claw_len m."""
    from lpk.forms.fur import tuft
    heel, toe = Vector(heel), Vector(toe)
    fwd = Vector((toe.x - heel.x, toe.y - heel.y, 0)).normalized()
    side = fwd.cross(Vector((0, 0, 1))).normalized()
    L = (toe - heel).length
    secs = ((0.0, 0.70, 0.75), (0.30, 0.95, 1.0), (0.70, 1.0, 0.78), (1.0, 0.80, 0.5))
    rings = [(heel + fwd * (L * f) + Vector((0, 0, height * hk * 0.5)), height * hk * 0.5, width * wk, {'p': 2.6})
             for f, wk, hk in secs]
    R = b.loft(part, rings, n, Vector((0, 0, 1)), col, cap0=heel - fwd * 0.02 + Vector((0, 0, height * 0.35)),
               cap1=toe + fwd * 0.02 + Vector((0, 0, height * 0.18)))
    m = (claws - 1) / 2
    for k in range(claws):
        base = toe - fwd * 0.005 + side * ((k - m) * width * 1.4 / claws) + Vector((0, 0, height * 0.14))
        tuft(b, part, base, base + fwd * claw_len - Vector((0, 0, height * 0.12)), 0.014, claw_col, thick=0.009,
             front=Vector((0, 0, 1)), seal=True)
    return R


def talon_toes(b, part, ball, sx, toes, col, claw_col, tip_col=None, scale=1.0, claw_len=0.17, claw_bend=0.42):
    """Bird- or raptor-like toes fanning from the ball of a digitigrade foot, each a three-sided loft
    through a knuckle dipping toward the floor, closed flat and carrying a curved `talon` (a large
    digitigrade foot; a toe at 180 degrees adds a back toe). toes: (angle from straight ahead in
    degrees, toward the foot's outside for sx = 1, toe length); scale: the sections and dips (1.0 at
    the size the notes name). Toes lean toward the floor, so place the ball a toe radius above it.
    28 triangles a toe: 13 for the toe's loft and flat end, 15 for its talon.
    Units: ball m, scale ratio, claw_len m, claw_bend rad. Scale 1.0 and claw_len are sized for a figure
    about 2.7 m tall, not the figure of about 1.7 to 2.1 m the other defaults are sized for; for another
    figure set scale and claw_len each from its own toes and claws, not by one body-height ratio, and
    compare the foot with the drawing."""
    from lpk.forms.hands import talon
    for ang, ln in toes:
        a = math.radians(ang) * sx
        fwd = Vector((math.sin(a), -math.cos(a), 0))
        base = ball + fwd * (0.01 * scale)
        k1 = base + fwd * (ln * 0.55) - Z * (0.012 * scale)
        tip = k1 + fwd * (ln * 0.45) - Z * (0.008 * scale)
        b.loft(part, [(base, 0.026 * scale, 0.024 * scale), (k1, 0.021 * scale, 0.018 * scale),
                      (tip, 0.016 * scale, 0.014 * scale)], 3, -Z, col, cap1='flat')
        talon(b, part, tip - fwd * (0.006 * scale), (fwd - Z * 0.05).normalized(), -Z, claw_len, 0.017 * scale,
              0.024 * scale, claw_col, tip_col=tip_col, bend=claw_bend)
