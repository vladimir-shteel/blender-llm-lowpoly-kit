"""The trunk as one surface from the crotch to the neck: tight shorts, a bodysuit or bare fur
are its bands' colours, the bottom ring splits into the leg holes (joins.leg_holes) and two
columns of rings open into the armholes (joins.armholes with ARMHOLE_COLS). Garments over it start
from its sections: section_at cuts them at a height, skirt hangs a separate open shell from there
and belt puts a hoop round it."""
import math
from mathutils import Vector

from lpk.core.sections import Section, loft_rings, resample
from lpk.core.shapes import point_loft, polygon_rings

SIDES = 10                          # vertices per trunk ring, the one density of the welded family
FLAT = (2, 7)                       # the front and back centre vertices
# A fitted-jacket trunk's 8-sided armhole columns (6, 7, 0, 1 and 2, 3, 4, 5 on its 10-gon without FLAT) on the 10-gon.
ARMHOLE_COLS = {'L': (8, 9, 0, 1), 'R': (3, 4, 5, 6)}


def trunk(b, part, rings, color, round_rings=3, boxes=((0, 3.2), (1, 2.6))):
    """rings: bottom up, polygon_rings sections ((x, y, z) centre, rx, ry, 10 vertex multipliers),
    the first the crotch. rx sizes a ring along X and ry along Y (as polygon_rings' radii). Ring vertex j sits
    at 18 + 36 j degrees from +X (the model's left) toward +Y (its back): 9 and 0 are the left side, 2 the
    back centre, 4 and 5 the right side and 7 the front centre; the multipliers follow that order. The first
    `round_rings` keep their full 10-gon (the hips round under tight clothes); above them the FLAT vertices
    sit midway between their neighbours, a fitted jacket's 8-sided outline, so its armhole columns apply.
    boxes: (ring, superellipse exponent) for rings drawn as rounded rectangles of their rx, ry extents: the
    crotch and the seat, round two thighs side by side (as ellipses, their back-outer diagonals can fall
    inside the thighs). Every ring reaches its ry in front and behind: the flattened rings stretch their front
    and back halves so the flat edge stands at the section's depth. The crotch ring keeps its front and back
    centre vertices on the midline for leg_holes. A box ring ignores vertex multipliers: one that differs from
    1 on a box ring raises ValueError. color: point_loft's. Returns the loft's rings.
    Units: color palette name or fn(i, j, normal) (point_loft's). Ten vertices per ring, fixed (SIDES): the
    one density the welded family is built for, since ARMHOLE_COLS and joins.leg_holes address this ring by
    index and joins.weld_limb the holes cut from it; another density needs limbs as separate shells or a
    local form."""
    for k, _ in boxes:
        mult = rings[k][3] if len(rings[k]) > 3 else None
        if mult and any(x != 1 for x in mult):
            raise ValueError('trunk: ring %d is a box ring (boxes), which ignores vertex multipliers, and has %r; '
                             'drop them or take the ring out of boxes' % (k, list(mult)))
    pts = polygon_rings(rings, SIDES, ())
    for k, pw in boxes:
        (cx, cy, cz), rx, ry = rings[k][0], rings[k][1], rings[k][2]
        for j in range(SIDES):
            th = math.pi / SIDES + 2 * math.pi * j / SIDES
            c, s = math.cos(th), math.sin(th)
            pts[k][j] = Vector((cx + rx * math.copysign(abs(c) ** (2 / pw), c),
                                cy + ry * math.copysign(abs(s) ** (2 / pw), s), cz))
    for k, ring in enumerate(pts[round_rings:], round_rings):
        _flatten(ring, rings[k][0])
    return point_loft(b, part, pts, color)


def _flatten(ring, centre):
    # The FLAT vertices move to the midpoint of their neighbours, which lie at sin(54 deg) of the
    # section's depth; the ring's back half and front half are then stretched along Y so each flat edge
    # lands where the centre vertex stood, and the octagon keeps the section's exact depth.
    cy = centre[1]
    for j in FLAT:
        want = ring[j].y - cy
        ring[j] = (ring[j - 1] + ring[j + 1]) / 2
        have = ring[j].y - cy
        if have * want > 0:
            k = want / have
            for v in ring:
                if (v.y - cy) * want > 0:
                    v.y = cy + (v.y - cy) * k


def section_at(sections, z, name='cut'):
    """The trunk's section at height z: the Section a horizontal cut through the loft of `sections` meets,
    every value interpolated linearly between the two sections whose heights bracket z, so a skirt, a belt
    or a hem can start from the body.

    sections: Section records (lpk.core.sections) bottom up, their heights (at[2]) strictly rising, as a
    trunk's sections run. z: the height of the cut (m), from the lowest section's height to the highest's.
    name: the returned section's name. Returns a Section at (x, y, z) with half, half_neg (None where both
    neighbours take their + extent), exponent, offset and ratios interpolated (ratios resampled to the larger
    sample count of the two, a section without ratios reading as ratios of 1), its frame normal and ref left
    to the loft. Its half extents are the extents of the section the loft's rings take at that height when
    the sections are horizontal (normals along Z, a along X): Builder.loft runs straight from ring to ring,
    so a cut between two parallel rings is their linear blend. A section with a tilted normal makes the cut
    an approximation, and torso.trunk's FLAT vertices and box rings sit on or inside these extents.
    Raises ValueError for fewer than two sections, heights that do not rise, or z outside their range."""
    sections = list(sections)
    if len(sections) < 2 or not all(isinstance(s, Section) for s in sections):
        raise ValueError('section_at needs two or more Section records bottom up (got %r)' % (sections,))
    zs = [s.at[2] for s in sections]
    for k in range(len(zs) - 1):
        if zs[k + 1] <= zs[k]:
            raise ValueError('section_at: section %r (z %.4g) does not rise above %r (z %.4g): order the '
                             'sections bottom up' % (sections[k + 1].name, zs[k + 1], sections[k].name, zs[k]))
    if not zs[0] <= z <= zs[-1]:
        raise ValueError('section_at: z %.4g lies outside the sections, %.4g to %.4g m; cut inside that range'
                         % (z, zs[0], zs[-1]))
    k = max(i for i in range(len(zs) - 1) if zs[i] <= z) if z < zs[-1] else len(zs) - 2
    s0, s1 = sections[k], sections[k + 1]
    t = (z - zs[k]) / (zs[k + 1] - zs[k])
    lerp = lambda u, v: u + (v - u) * t
    neg = lambda s, i: s.half[i] if s.half_neg[i] is None else s.half_neg[i]
    half_neg = tuple(None if s0.half_neg[i] is None and s1.half_neg[i] is None else lerp(neg(s0, i), neg(s1, i))
                     for i in range(2))
    ratios = None
    if s0.ratios is not None or s1.ratios is not None:
        c = max(len(s.ratios) for s in (s0, s1) if s.ratios is not None)
        r0, r1 = (resample(s.ratios, c) if s.ratios is not None else [1.0] * c for s in (s0, s1))
        ratios = tuple(lerp(u, v) for u, v in zip(r0, r1))
    return Section(name, (lerp(s0.at[0], s1.at[0]), lerp(s0.at[1], s1.at[1]), z),
                   (lerp(s0.half[0], s1.half[0]), lerp(s0.half[1], s1.half[1])), half_neg,
                   lerp(s0.exponent, s1.exponent), (lerp(s0.offset[0], s1.offset[0]), lerp(s0.offset[1], s1.offset[1])),
                   ratios)


def _bounds(s):
    """(x min, x max, y min, y max) of a horizontal Section's exact extents, its offset applied (a along X,
    b along Y)."""
    cx, cy = s.at[0] + s.offset[0], s.at[1] + s.offset[1]
    neg = [s.half[i] if s.half_neg[i] is None else s.half_neg[i] for i in range(2)]
    return cx - neg[0], cx + s.half[0], cy - neg[1], cy + s.half[1]


def _widest(sections, z0, z1):
    """The body's bounds over the heights z0 to z1 (clamped to the sections' range): the outermost extent on
    each side among the cuts at both ends and every section between them."""
    lo, hi = sections[0].at[2], sections[-1].at[2]
    z0, z1 = sorted((min(max(z0, lo), hi), min(max(z1, lo), hi)))
    cuts = [section_at(sections, z0), section_at(sections, z1)] + [s for s in sections if z0 < s.at[2] < z1]
    b = [_bounds(s) for s in cuts]
    return min(x[0] for x in b), max(x[1] for x in b), min(x[2] for x in b), max(x[3] for x in b)


def _ring_section(name, body, bounds, z, grow):
    """A horizontal Section at z reaching `bounds` (x min, x max, y min, y max) grown by grow = (gx, gy) m on
    each side, centred where the body's cut `body` is, with its exponent and ratios."""
    cx, cy = body.at[0] + body.offset[0], body.at[1] + body.offset[1]
    x0, x1, y0, y1 = bounds
    gx, gy = grow
    return Section(name, (cx, cy, z), (x1 - cx + gx, y1 - cy + gy), (cx - x0 + gx, cy - y0 + gy),
                   body.exponent, ratios=body.ratios)


def _clamped(sections, z):
    return section_at(sections, min(max(z, sections[0].at[2]), sections[-1].at[2]))


def _pair(value, what):
    pair = (value, value) if isinstance(value, (int, float)) else tuple(value)
    if len(pair) != 2 or min(pair) < 0:
        raise ValueError('%s takes metres >= 0, one number or (along X, along Y) (got %r)' % (what, value))
    return pair


def skirt(b, part, sections, top, length, color, thick=0.012, flare=0.04, rows=2, tuck=0.006, n=SIDES,
          ref=(1.0, 0.0, 0.0)):
    """A skirt or a tunic's hem as a separate open shell over the trunk: rings from a top at height `top`
    down to a hem `length` below it, each standing `thick` off the widest the body gets between the top and
    that ring (cloth hangs from the widest point and never cuts back in over the hips), plus `flare` grown
    linearly with the drop, so the hem spreads by `flare`. With `tuck` > 0 a last ring at the top's height
    sits `tuck` inside the body: the top edge closes as a flat band that shows the cloth's thickness
    instead of an open gap.

    sections: the trunk's Section records bottom up (section_at's). top: the skirt's top height (m), inside
    their range. length: the drop to the hem (m); below the lowest section (the crotch) the body is read as
    that section, so the legs below it are not seen: widen `flare` until the hem clears the thighs in the
    front capture. thick: m. flare: m added to every extent at the hem, one number or (along X, along Y).
    rows: the bands from the hem to the top, rings evenly spaced. n: vertices per ring at the trunk's angles
    (vertex j at pi / n + 2 pi j / n from +X toward +Y), torso.SIDES to sit over a welded trunk vertex for
    vertex. color: Builder.loft's (palette name or fn(i, j, d)), band i = 0 at the hem, the tuck band last.
    Returns the rings (lists of BMVerts), the hem first, the tuck ring last when there is one.
    n * (rows + (1 if tuck else 0)) quads, both ends open.

    Limits: the faces between two rings are chords, so where the body bulges between ring heights it shows
    through: add rows until a ring sits at its widest height. A single surface: from below its inside shows
    as back faces. Not welded: weight it to the hips and the upper legs (ALLOWED = {'skirt': ['Hips',
    'UpperLeg.L', 'UpperLeg.R']}); in a wide stride or a high kick the legs pass through it, since an open
    skirt cannot follow two legs."""
    if length <= 0 or thick <= 0 or tuck < 0 or rows < 1:
        raise ValueError('skirt: length and thick must be positive, tuck >= 0 and rows >= 1 (got %r, %r, %r, %r)'
                         % (length, thick, tuck, rows))
    sections = list(sections)
    section_at(sections, top)
    fx, fy = _pair(flare, 'skirt flare')
    out = []
    for k in range(rows, -1, -1):
        f = k / rows
        z = top - length * f
        out.append(_ring_section('r%d' % k, _clamped(sections, z), _widest(sections, z, top), z,
                                 (thick + fx * f, thick + fy * f)))
    if tuck:
        body = section_at(sections, top)
        out.append(_ring_section('tuck', body, _bounds(body), top, (-tuck, -tuck)))
    rings = loft_rings(out, ref, n, axis=(0.0, 0.0, 1.0))
    return b.loft(part, rings, n, ref, color)


def belt(b, part, sections, z, width, thick, color, over=0.0, tuck=0.006, n=SIDES, ref=(1.0, 0.0, 0.0),
         buckle=None, buckle_col=None, buckle_part=None):
    """A belt as a hoop round the trunk at height z: an outer wall `width` high standing `over` + `thick` off
    the widest the body gets across that height, and flat top and bottom bands from it into the body
    (`tuck` inside the body's own section at each edge), so the belt shows its thickness from above and
    below and no gap opens between it and the body. An optional buckle box sits on its front.

    sections: the trunk's Section records bottom up (section_at's). z: the belt's middle height (m); its
    edges z +- width / 2 inside the sections' range. width, thick: m. over: m of whatever lies between the
    body and the belt, a skirt's `thick` where the belt sits on a skirt's top. n: vertices per ring at the
    trunk's angles (skirt's). color: Builder.loft's, band 0 the bottom, 1 the wall, 2 the top. buckle:
    None, or the box's half sizes (x, y, z) in m, centred on the belt's front centre (half its depth sunk
    into the belt), in `buckle_col` (else the belt's colour, which must then be a palette name) and in
    part `buckle_part` (else `part`). For a cast plate or a star buckle instead, build it at the returned
    front point (shapes.conform_plate, shapes.star_prism).
    Returns {'rings': the four rings (lists of BMVerts), inner bottom, outer bottom, outer top, inner top;
    'front': the outer wall's front centre at z (Vector, m), the point the buckle is centred on}.
    3 * n quads (and 6 faces of the buckle); the hoop's inner side stays open inside the body.

    Limits: rigid round the body; weight it to the hips and the spine (ALLOWED = {'belt': ['Hips',
    'Spine']}), or pin it to Hips in FIXED, so a bend at the waist pushes the trunk through it."""
    if width <= 0 or thick <= 0 or over < 0 or tuck < 0:
        raise ValueError('belt: width and thick must be positive, over and tuck >= 0 (got %r, %r, %r, %r)'
                         % (width, thick, over, tuck))
    sections = list(sections)
    lo, hi = z - width / 2, z + width / 2
    section_at(sections, lo), section_at(sections, hi)
    wide = _widest(sections, lo, hi)
    g = over + thick
    out = []
    for name, h, outer in (('in_bottom', lo, False), ('out_bottom', lo, True), ('out_top', hi, True),
                           ('in_top', hi, False)):
        body = section_at(sections, h)
        out.append(_ring_section(name, body, wide, h, (g, g)) if outer else
                   _ring_section(name, body, _bounds(body), h, (-tuck, -tuck)))
    rings = loft_rings(out, ref, n, axis=(0.0, 0.0, 1.0))
    R = b.loft(part, rings, n, ref, color)
    mid = section_at(sections, z)
    front = Vector((mid.at[0] + mid.offset[0], wide[2] - g, z))
    if buckle is not None:
        b.box(buckle_part or part, front, tuple(buckle), None, buckle_col or color)
    return {'rings': R, 'front': front}
