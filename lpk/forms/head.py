"""Heads: the profile head lofted from profile keys, the muzzled snout head with its side-view key presets (a
blunt-muzzled mammal, a monitor lizard) and the readers that trace its keys in metres off calibrated views,
the stylised human head, face decals and shells, and hand edits of head rings."""
import math
from mathutils import Vector

from lpk.core.builder import loft_section
from lpk.core.shapes import miss, point_loft, profile_loft
from lpk.core.sections import profile_rings

X = Vector((1, 0, 0)); Y = Vector((0, 1, 0)); Z = Vector((0, 0, 1))


# Side-view keys for a muzzled mammal head, in cranium units: s in lengths (positive = back of
# the skull), top/bottom in half heights, width in half widths, then superellipse exponent.
# The top line falls steeply over the forehead, eases at the stop and runs flatter along the
# bridge to the nose. The snout keeps most of its section to a blunt nose and the jaw line
# stays low and nearly straight: a cylinder, not a cone to a point.
MUZZLE_KEYS = (
    (0.55, 0.55, -0.55, 0.45, 2.2),     # back of skull
    (0.30, 0.93, -0.85, 0.82, 2.8),
    (0.00, 1.00, -0.90, 1.00, 3.2),     # crown
    (-0.25, 0.88, -0.88, 0.98, 3.2),    # brow
    (-0.42, 0.55, -0.80, 0.85, 3.0),    # stop: the eyes sit here, below the brow line
    (-0.55, 0.32, -0.74, 0.58, 2.6),    # snout root
    (-0.75, 0.20, -0.70, 0.48, 2.5),
    (-0.92, 0.12, -0.66, 0.42, 2.4),    # nose base
    (-1.00, 0.06, -0.46, 0.34, 2.3),    # the jaw recedes under the nose
    (-1.07, 0.00, -0.24, 0.24, 2.2),    # slanted nose pad
)
# The preset's nose apex, (s, height) in the same units: just ahead of its small last key and a little
# below that key's top, so this muzzle's nose reads as a short wedge sloping back to the chin. A drawn
# nose places its own apex (snout_head's docstring).
MUZZLE_NOSE = (-1.12, -0.08)
MUZZLE_SKULL = (0.66, 0.0)              # the skull's apex behind the back key, (s, height)
MUZZLE_STOP = 4                         # the index of the key the eyes sit on

# Monitor-lizard head in the same units: a low cranium widest over the jaw muscles, eyes high
# on the sides, then a long flat-topped snout over a deep, boxy jaw that keeps its depth to a
# heavy chin (a plain tapering snout reads as a capsule).
REPTILE_KEYS = (
    (0.55, 0.50, -0.60, 0.60, 2.4),     # back of skull
    (0.30, 0.88, -0.92, 0.92, 2.8),
    (0.05, 1.00, -1.00, 1.00, 3.0),     # widest, over the jaw muscles
    (-0.15, 0.96, -0.92, 0.90, 3.0),    # eyes
    (-0.40, 0.76, -0.92, 0.80, 3.4),    # snout root
    (-0.65, 0.64, -0.92, 0.72, 3.6),
    (-0.90, 0.56, -0.90, 0.68, 3.6),    # heavy, square jaw
    (-1.10, 0.48, -0.84, 0.62, 3.4),    # nostrils over a deep chin
    (-1.22, 0.36, -0.68, 0.52, 3.0),    # blunt tip
)
REPTILE_NOSE = (-1.30, -0.12)           # the nose apex, (s, height)
REPTILE_SKULL = (0.66, -0.05)           # the skull's apex, (s, height)
REPTILE_STOP = 3                        # the index of the key the eyes sit on

# Human head as horizontal slices, the proportions of a stylised low-poly human, a preset to edit:
# rows of (height, ten points). Height in half heights (crown +1, chin -1); each slice lists
# (x, y) in half widths / half depths for the angles 0, 25, 50, 90, 140 and 180 degrees from the
# front, and is mirrored to ten points. The read comes from large planes, not from facets
# converging on a nose: a flat, near-vertical face almost as wide as the head with a clear corner
# to the sides, a steep forehead ending in a low brow over a slightly recessed eye band, the nose
# and mouth as one block, cheeks that fall back under the cheekbones, and a jaw that narrows to a
# chin set behind the mouth.
HUMAN_HEAD = (
    (0.81, ((0.00, -0.64), (0.27, -0.57), (0.48, -0.40), (0.65, 0.05), (0.40, 0.52), (0.00, 0.63))),
    (0.55, ((0.00, -0.87), (0.38, -0.79), (0.70, -0.53), (0.95, 0.06), (0.56, 0.71), (0.00, 0.86))),
    (0.33, ((0.00, -0.93), (0.44, -0.89), (0.74, -0.56), (1.00, 0.06), (0.67, 0.85), (0.00, 1.00))),   # brow top
    (0.31, ((0.00, -0.94), (0.45, -0.91), (0.73, -0.57), (0.98, 0.03), (0.71, 0.86), (0.00, 1.00))),   # brow front
    (0.20, ((0.00, -0.96), (0.45, -0.91), (0.72, -0.58), (0.92, 0.02), (0.72, 0.86), (0.00, 0.99))),
    (0.12, ((0.00, -0.92), (0.42, -0.84), (0.73, -0.56), (0.88, 0.04), (0.69, 0.84), (0.00, 0.99))),   # eye band
    (-0.12, ((0.00, -0.99), (0.43, -0.87), (0.76, -0.59), (0.85, 0.00), (0.68, 0.78), (0.00, 0.98))),  # nose, cheeks
    (-0.36, ((0.00, -0.96), (0.37, -0.86), (0.70, -0.58), (0.78, -0.06), (0.56, 0.53), (0.00, 0.73))), # mouth
    (-0.55, ((0.00, -0.94), (0.27, -0.89), (0.53, -0.72), (0.72, -0.28), (0.51, 0.07), (0.00, 0.22))), # jaw
    (-0.81, ((0.00, -0.85), (0.22, -0.80), (0.40, -0.65), (0.44, -0.40), (0.29, -0.29), (0.00, -0.22))),
)
HUMAN_CROWN = (0.0, 0.05, 1.0)          # apex (x, y, height) in the same units
HUMAN_CHIN = (0.0, -0.40, -1.0)         # apex under the last slice (x, y, height)
HUMAN_WIDTH = 0.725                     # half width / half height of the preset head
HUMAN_DEPTH = 0.74                      # half depth / half height
HUMAN_EYE = (0.43, -0.94, 0.16)         # eye centre (x, y, height)
HUMAN_NOSE_ROW = 6                      # the slice whose front-centre vertex human_head's nose pulls forward


def human_head(b, part, center, width, height, depth, color, jaw=1.0, nose=0.0024, chin=1.0):
    """Human head facing -Y from the HUMAN_HEAD slices: 200 triangles.
    width/height/depth: half sizes (HUMAN_WIDTH and HUMAN_DEPTH times the half height give the
    preset head's half width and half depth); jaw scales the width below the cheeks (1.0 = the preset);
    nose: metres the front-centre vertex of the nose slice is pulled forward. A few millimetres
    is enough to read as a nose; a separate nose wedge reads as a beak. chin < 1 raises the apex
    under the last slice toward it: a blunter, shorter chin instead of the preset's V.
    color(i, j, normal): i is the band, -1 the crown fan, 0 upper skull, 1 forehead, 2 brow top,
    3 brow front, 4 under the brow, 5 eyes to nose, 6 cheeks, 7 mouth, 8 chin, 9 the chin's
    underside; j is the column from the front centre (0 and 9 front, 1 and 8 face corners,
    2 and 7 sides, 3-6 back).
    Returns {'eye': (y, z) of the eye line, 'eye_x': eye centre x, 'front_y': face plane y,
    'pt': fn(x, y, height) from head units to world, for placing facial hair and gear}.
    Units: center m, color palette name or fn(i, j, normal) (point_loft's), chin ratio."""
    c = Vector(center); W, H, D = width, height, depth

    def pt(x, y, u):
        k = 1 + (jaw - 1) * min(1.0, max(0.0, (-0.2 - u) / 0.6))
        return c + Vector((x * W * k, y * D, u * H))
    rings = []
    for u, half in HUMAN_HEAD:
        right = [pt(x, y, u) for x, y in half]
        left = [pt(-x, y, u) for x, y in reversed(half[1:-1])]
        rings.append(right + left)
    last = HUMAN_HEAD[-1][0]
    cx, cy, cu = HUMAN_CHIN
    R = point_loft(b, part, rings, color, cap0=pt(*HUMAN_CROWN), cap1=pt(cx, cy, last + (cu - last) * chin))
    R[HUMAN_NOSE_ROW][0].co.y -= nose
    ex, ey, eu = HUMAN_EYE
    return {'eye': (c.y + ey * D, c.z + eu * H), 'eye_x': ex * W, 'front_y': c.y - D, 'pt': pt}


def face_decals(b, part, bvh, pt, shapes, lift=0.0012):
    """Facial features as flat polygons floating just off a human_head face (an eye, an iris, a
    brow, a mouth): crisp at any texel density, unlike a baked face. shapes: [(points, colour,
    extra lift)] with points as (x, height) in head units (see human_head `pt`), each projected
    onto the face from the front along +Y. Later shapes sit higher, so list them back to front.
    human_head's flat face turns into the sides at its face corners, about x = 0.43 head units (its
    second slice column): a shape spanning the corner is triangulated across the bend and tilts, so
    split it there; a point past about x = 0.66 lands on the side and flattens the decal.
    A shape with any missed ray is skipped and counted in the builder's probe misses (shapes.miss)."""
    for pts, col, dl in shapes:
        hits = []
        for x, u in pts:
            o = pt(x, -3.0, u)
            hit, nrm, _, _ = bvh.ray_cast(o, Y, 1.0)
            if hit is None:
                break
            hits.append((hit, nrm))
        if len(hits) < len(pts):
            miss(b, 'face_decals', part, o)
            continue
        normal = sum((n for _, n in hits), Vector()).normalized()
        b.decal(part, [h + n * (lift + dl) for h, n in hits], col, normal)


def face_shell(b, part, bvh, rows, thick, color, inset=0.006, tip=None):
    """A layer hugging a surface as its own volume (facial hair as on stylised low-poly humans:
    a beard or moustache shell, not paint on the face). rows: guide polylines, each a list of
    points just off the surface from one side to the other; every point snaps to the nearest
    surface point, its front copy is lifted by `thick` along the normal and its back copy sunk by
    `inset`, so each row is a closed loop and the shell shows its thickness at the edges.
    tip: apex closing the last row (a pointed goatee); otherwise the row closes on its centre.
    4 * len(row) * len(rows) triangles: each row is a ring of 2 * len(row) points, and both ends close
    with a fan.
    Returns rings (lists of BMVerts). Units: rows m, thick m, color palette name or fn(i, j, normal)
    (point_loft's), inset m, tip m."""
    rings = []
    for row in rows:
        front, back = [], []
        for g in row:
            hit, nrm, _, _ = bvh.find_nearest(Vector(g))
            front.append(hit + nrm * thick); back.append(hit - nrm * inset)
        rings.append(front + list(reversed(back)))
    centre = lambda ring: sum(ring, Vector()) / len(ring)
    return point_loft(b, part, rings, color, cap0=centre(rings[0]), cap1=tip if tip is not None else centre(rings[-1]))


# Radii and offsets use the head's units; exponent and vertex multipliers are dimensionless.
_KEY_OPTIONS = ('p', 'mult', 'ra_neg', 'ra_bneg', 'rb_neg', 'off')


def _key_options(e, w, i, h=1.0):
    if not isinstance(e, dict):
        return {'p': e}
    bad = sorted(set(e) - set(_KEY_OPTIONS))
    if bad:
        raise ValueError('snout_head: key %d holds loft options %s; a key takes %s'
                         % (i, bad, ', '.join(_KEY_OPTIONS)))
    out = dict(e)
    for name in ('ra_neg', 'ra_bneg'):
        if name in out:
            out[name] *= w
    if 'rb_neg' in out:
        out['rb_neg'] *= h
    if 'off' in out:
        da, db = out['off']
        out['off'] = (da * w, db * h)
    return out


def snout_head(b, part, center, length, width, height, color, n=10, keys=MUZZLE_KEYS, snout=1.0,
               eye_height=0.25, nose=MUZZLE_NOSE, skull=MUZZLE_SKULL, stop=MUZZLE_STOP):
    """Head facing -Y built with profile_loft from side-view keys in cranium units (a mammal
    muzzle by default; pass REPTILE_KEYS/NOSE/SKULL/STOP for a monitor-lizard head).

    keys: one per section, back to front with s falling, each (s, top, bottom, half width[, options]):
    s the section's place along the head in head lengths (`length`) from `center`, positive toward the
    back of the skull and negative toward the nose; top and bottom the side outline's heights above
    `center` in half heights (`height`), bottom negative under it; half width in half widths (`width`).
    The fifth element is the section's superellipse exponent, 2 (an ellipse) when left out, or a dict
    of Builder.loft's ring options: 'p' the exponent, 'ra_bneg' the half width of the section's lower
    half (below its mid-height), 'ra_neg' the half width on the -X side, both in half widths like the
    key's own, and 'mult' the per-vertex radius factors (they scale the top and bottom vertices too), 'rb_neg'
    the lower half height in half heights, and 'off' the centre offset (across in half widths, up in
    half heights); rb_neg and off move the section off the key's top and bottom. With length, width and
    height at 1 the keys are in metres (side_key, traced_keys), and so is every deformer's length, h and
    start; muzzle_keys builds head-unit keys from proportions. nose, skull: the apexes closing the front
    and the back, (s, height) in the keys' units. stop: index of the key the eyes sit on.
    snout scales the length in front of the stop (1.0 = default proportion). eye_height: eye
    level above the cranium centre in half heights; keep it below the stop's top line or the
    eyes climb onto the forehead and into the hair.

    Each key is a superellipse section centred at its mid-height, (top + bottom) / 2, with half height
    (top - bottom) / 2 and its half width at that mid-height, where it is widest; the loft runs straight
    between sections, so the front outline is their envelope (front_envelope).

    color(i, j, d), Builder.loft's: i the band from key i to key i + 1, counted from the back key,
    for any number of keys; j the column, from the left side (+X) up over the top, down the right side
    and back under the jaw; d the column's outward direction in world space, x across and z up, with
    no y: it never points back or forward, so a rule on d alone reaches every band. The skull's apex
    cap takes one colour, color(0, 0, d), and the nose's apex cone one, color(len(keys) - 2, 0, d):
    whatever band 0 and the last band give their column 0, never a colour of their own. With
    MUZZLE_KEYS the bands are 0-1 the
    back of the skull, 2 the crown, 3 the forehead, 4 the stop to the snout root, 5 the snout root,
    6 the snout's middle, 7 the nose base and 8 the nose pad; traced keys have bands of their own.
    Returns {'rings', 'eye': (y, z) of the eye line at the stop, 'eye_x': half width there, 'pt': fn(s,
    height, x=0) from head units to world, snout's stretch applied in front of the stop, for placing
    decal outlines and gear in the keys' units}.
    Units: eye_height head units (half heights)."""
    c = Vector(center); L, w, h = length, width, height
    s_stop = keys[stop][0]
    along = lambda s: s if s >= s_stop else s_stop + (s - s_stop) * snout
    loft_keys = []
    for i, k in enumerate(keys):
        opts = (_key_options(k[4], w, i, h),) if len(k) > 4 else ()
        loft_keys.append((-along(k[0]) * L, k[1] * h, k[2] * h, k[3] * w) + opts)   # axis is -Y
    s_n = s_stop + (nose[0] - s_stop) * snout
    nose_p = c + Vector((0, s_n * L, nose[1] * h))           # s and world Y share sign: negative = front
    skull_p = c + Vector((0, skull[0] * L, skull[1] * h))
    R = profile_loft(b, part, c, (0, -1, 0), (0, 0, 1), loft_keys, n, color, cap0=skull_p, cap1=nose_p)
    k = keys[stop]

    def pt(s, height, x=0.0):
        return c + Vector((x * w, along(s) * L, height * h))
    return {'rings': R, 'eye': (c.y + k[0] * L, c.z + eye_height * h), 'eye_x': k[3] * w, 'pt': pt}


def _band_colours(color, names):
    """profile_head's colour as Builder.loft takes it: a palette name or fn(i, j, d) as given; a dict
    {key name: palette name} as fn(i, j, d) giving band i the colour of the last key it names at or
    behind key i."""
    if not isinstance(color, dict):
        return color
    unknown = sorted(set(color) - set(names))
    if unknown:
        raise ValueError('profile_head: colours name %s, which are not keys of the profile; its keys: %s'
                         % (', '.join(map(repr, unknown)), ', '.join(names)))
    if names[0] not in color:
        raise ValueError('profile_head: colours by key need the first key %r: every band takes the colour of the '
                         'last key named at or behind it' % names[0])
    if names[-1] in color:
        raise ValueError('profile_head: the last key %r starts no band; the nose takes the colour of the band '
                         'before it' % names[-1])
    bands, current = [], None
    for name in names[:-1]:
        current = color.get(name, current)
        bands.append(current)
    return lambda i, j, d: bands[i]


def profile_head(b, part, origin, keys, n, color, nose, skull, stop=None, eye_height=None, *, axis=(0.0, -1.0, 0.0),
                 up=(0.0, 0.0, 1.0)):
    """A head facing -Y lofted from profile keys at their exact extents (lpk.core.sections.profile_rings at n
    sides, as a 'profile' block lays them), closed on the skull's apex behind the first key and the nose's
    apex ahead of the last. Passing the keys of the model's head block keeps the build on the blocks.

    origin: the point the keys are measured from (m). keys: lpk.core.sections.ProfileKey records ordered
    from the back of the skull to the nose, s along `axis` (toward the front), top and bottom along `up`,
    all in metres from origin. axis, up: the profile's direction and up; a head runs along (0, -1, 0) with
    up (0, 0, 1), and any other values are refused. nose, skull: the apexes, (s, height) in metres about
    the origin, s positive toward the back (+Y), as head.side_point reads them about that origin: the
    skull's lies behind the first key, the nose's ahead of the last; how far each sits past its key sets
    how pointed that end reads. color: a palette name, Builder.loft's fn(i, j, d) (i the band from key i to
    key i + 1, counted from the back key), or {key name: palette name}, each band taking the colour of the
    last key named at or behind its first key (the first key named; the last key starts no band). Each
    apex cap takes the colour of its end band. stop, eye_height: the name of the key the eyes sit on and
    the eye line's height above the origin in metres, given together, for the returned 'eye' and 'eye_x'.

    Returns {'rings': the rings from the back key to the nose key as Builder.loft returns them, 'keys':
    the sections as lofted, as snout_head keys in metres about the origin ((s, top, bottom, half width,
    loft options), s positive toward the back: the kernel radii that reach the keys' exact extents),
    which head.front_envelope (with the origin as its centre), head.wedge_muzzle and
    head.profile_key_deviation (length and h 1) take, 'names': the key names in order, 'stop': the
    stop's index or None, 'pt': fn(s, height, x=0) from metres about the origin, s positive toward the
    back, to world, and with stop 'eye': (y, z) of the eye line at the stop key and 'eye_x': that key's
    half width}. Raises ValueError for another axis or up, keys profile_rings refuses, an apex on the
    wrong side of its end key, a stop that is no key or one given without eye_height, and colours by key
    that name no key, leave the first key out or name the last."""
    if max(abs(float(a) - e) for a, e in zip(tuple(axis) + tuple(up), (0.0, -1.0, 0.0, 0.0, 0.0, 1.0))) > 1e-9:
        raise ValueError('profile_head: the profile runs along %r with up %r; a head runs along (0, -1, 0) with '
                         'up (0, 0, 1): loft another axis with shapes.profile_loft' % (tuple(axis), tuple(up)))
    rings = profile_rings(origin, axis, up, keys, n)
    origin = tuple(float(x) for x in origin)
    names = [k.name for k in keys]
    if skull[0] <= -keys[0].s:
        raise ValueError('profile_head: the skull apex (s %r) must lie behind the first key %r (s %r toward the '
                         'back)' % (skull[0], names[0], -keys[0].s))
    if nose[0] >= -keys[-1].s:
        raise ValueError('profile_head: the nose apex (s %r) must lie ahead of the last key %r (s %r toward the '
                         'back)' % (nose[0], names[-1], -keys[-1].s))
    if stop is not None and stop not in names:
        raise ValueError('profile_head: stop %r is no key of the profile; its keys: %s' % (stop, ', '.join(names)))
    if (stop is None) != (eye_height is None):
        raise ValueError('profile_head: give stop and eye_height together')
    paint = _band_colours(color, names)
    c = Vector(origin)
    skull_p = c + Vector((0.0, skull[0], skull[1]))
    nose_p = c + Vector((0.0, nose[0], nose[1]))
    R = b.loft(part, rings, n, rings[0][3]['ref'], paint, cap0=skull_p, cap1=nose_p)
    own = []
    for (centre, ra, rb, options), k in zip(rings, keys):
        mid = centre[2] - origin[2]
        opts = {name: options[name] for name in ('p', 'ra_neg', 'rb_neg', 'ra_bneg') if name in options}
        own.append((-k.s, mid + rb, mid - rb, ra, opts))

    def pt(s, height, x=0.0):
        return c + Vector((x, s, height))
    out = {'rings': R, 'keys': own, 'names': names, 'stop': None if stop is None else names.index(stop), 'pt': pt}
    if stop is not None:
        k = keys[out['stop']]
        out.update(eye=(c.y - k.s, c.z + eye_height), eye_x=k.half_width)
    return out


def profile_key_deviation(keys, height=None, width=None, read_mpp=None):
    """Per inner key of a profile (MUZZLE_KEYS and the like): how far its top, bottom and half
    width sit off the straight line between its neighbours, in the keys' units. A key at zero on all
    three lies on its neighbours' line and carries no shape; one near zero carries little.

    height, width: the head's half height and half width in metres, as snout_head takes them: with
    both, each entry also holds the largest deviation in metres, the top and bottom scaled by height and
    the half width by width (the keys' own spacing along the head, as at snout 1). read_mpp: metres per
    screen pixel at the declared read size, the body's height over the on-screen height in pixels the brief
    declares (lpk.stages.review.play_size's 'mpp'): each entry then also holds that deviation in screen
    pixels. Raises ValueError for
    only one of height and width, read_mpp without them, or a value that is not a positive number.
    Returns [(key index, largest deviation in key units)] for the inner keys; with height and width (key
    index, deviation in key units, metres), and with read_mpp too, the screen pixels after them."""
    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0
    if (height is None) != (width is None):
        raise ValueError('profile_key_deviation: give both height and width (metres), or neither')
    if read_mpp is not None and height is None:
        raise ValueError('profile_key_deviation: read_mpp reads the metres, so it needs height and width')
    bad = [n for n, v in (('height', height), ('width', width), ('read_mpp', read_mpp)) if v is not None and not num(v)]
    if bad:
        raise ValueError('profile_key_deviation: %s must be positive numbers' % ', '.join(bad))
    out = []
    for i in range(1, len(keys) - 1):
        a, b, c = keys[i - 1], keys[i], keys[i + 1]
        t = (b[0] - a[0]) / (c[0] - a[0])
        d = [abs(b[j] - (a[j] + t * (c[j] - a[j]))) for j in (1, 2, 3)]
        if height is None:
            out.append((i, max(d)))
            continue
        m = max(d[0] * height, d[1] * height, d[2] * width)
        out.append((i, max(d), round(m, 6)) + ((round(m / read_mpp, 2),) if read_mpp is not None else ()))
    return out


def muzzle_keys(eye, nose, chin_z, mouth_z, cranium_w, muzzle_w, nose_w, back_s=0.55, brow_top=0.85,
                p_cranium=3.0, p_muzzle=2.2, bridge=None, stop_w=0.85):
    """snout_head keys, nose apex and stop index built from measurements instead of a preset, for a
    muzzle the presets do not draw (MUZZLE_KEYS keeps most of its section to a blunt nose). All in
    snout_head units: s in head lengths (negative = forward), heights in half heights from the
    head centre, widths in half widths. eye, nose: (s, height) of the eye centre and the nose tip;
    chin_z: the underside of the jaw under the cranium; mouth_z: the jaw's underside at the front;
    cranium_w: the skull's widest; stop_w: the section under the eyes, as a fraction of it (1.0 for a
    face as wide at the eyes as the skull); muzzle_w: the snout root under the eyes; nose_w: the nose.
    The muzzle runs five keys from the stop (the eye's s) to the nose, its sides from muzzle_w to
    nose_w. Its top line eases from the stop down to the nose; bridge=(root top, nose top) instead
    runs it straight between those heights after a stop step under the eyes (a straight profile, on
    which the eased line can read as a drooping muzzle).
    Returns (keys: ten snout_head keys, each (s, top, bottom, half width, exponent), back to front; nose:
    (s, height); stop index: 4). Units: head units throughout, but p_cranium and p_muzzle, superellipse
    exponents."""
    es, ez = eye; ns, nz = nose
    stop_top = ez + 0.32
    keys = [(back_s, 0.55, -0.45, 0.55, 2.2), (back_s * 0.55, 0.93, chin_z * 0.70, cranium_w * 0.86, 2.8),
            (0.0, 1.0, chin_z * 0.85, cranium_w, p_cranium), (es * 0.6, brow_top, chin_z * 0.95, cranium_w, p_cranium),
            (es, stop_top, chin_z, cranium_w * stop_w, p_cranium * 0.93)]
    for t in (0.2, 0.45, 0.72, 0.9, 1.0):
        if bridge:
            top = bridge[0] + (bridge[1] - bridge[0]) * (t - 0.2) / 0.8
        else:
            top = stop_top + (nz + 0.07 - stop_top) * (1 - (1 - t) ** 1.6)   # drops faster near the stop
        keys.append((es + (ns - es) * t, top, chin_z + (mouth_z - chin_z) * t, muzzle_w + (nose_w - muzzle_w) * t,
                     p_muzzle))
    return tuple(keys), (ns - 0.05, nz), 4


def _crossings(poly, at, axis):
    """Where a closed pixel polygon crosses the line through `at` on `axis` (0: the column x = at, giving
    rows; 1: the row y = at, giving columns)."""
    pts = [(float(p[0]), float(p[1])) for p in poly]
    o = 1 - axis
    out = []
    for p, q in zip(pts, pts[1:] + pts[:1]):
        a, b = p[axis], q[axis]
        if a == b:
            if a == at:
                out += [p[o], q[o]]
        elif min(a, b) <= at <= max(a, b):
            out.append(p[o] + (at - a) / (b - a) * (q[o] - p[o]))
    return out


def _row(cal, z):
    # Every calibration mode maps rows to heights affinely, so two rows fix the inverse.
    z0, z1 = cal.z(0.0), cal.z(1.0)
    return (z - z0) / (z1 - z0)


def side_key(side, center, px, top_py, bottom_py, half_width, opts=None):
    """One snout_head key in metres about the head centre, traced off a calibrated side view: px is the
    side view's column at the key's place along the head, top_py and bottom_py the side outline's top
    and bottom rows at that column, half_width the section's half width at its mid-height in metres
    (front_half_width reads it off a front outline). center: the head centre snout_head takes, in
    model metres. side: the side view's calibration, which places a column along the head through the
    view's zero_px and facing (side_y) and a row through its heights. opts: the key's exponent or loft
    options, as snout_head takes them, in metres here. Give snout_head the keys with length, width and
    height at 1, and its nose and skull from side_point. Returns (s, top, bottom, half width), with
    opts as a fifth element when given.
    Units: top_py side-view pixels (a row), bottom_py side-view pixels (a row)."""
    c = Vector(center)
    key = (side.side_y(px) - c.y, side.z(top_py) - c.z, side.z(bottom_py) - c.z, half_width)
    return key + ((opts,) if opts is not None else ())


def side_point(side, center, px, py):
    """A side-view pixel as (s, height) in metres about the head centre: snout_head's nose and skull
    apexes, and the points of its returned `pt`, when the keys are in metres (side_key). side, center:
    as side_key takes them.
    Units: px side-view pixels, py side-view pixels."""
    c = Vector(center)
    return side.side_y(px) - c.y, side.z(py) - c.z


def front_half_width(front, outline, z):
    """Half the width of a closed front-view outline at the model height z, in metres: its outermost
    crossings of the row at that height, through the view's calibration. outline: a views.json trace's
    'px' on the front view, of the part alone (a head without its ears, hair or ruff, whose width the
    front would add to it). Raises ValueError when that row misses the outline.
    Returns half the outline's width at height z, in metres."""
    py = _row(front, z)
    xs = _crossings(outline, py, 1)
    if not xs:
        raise ValueError('front_half_width: the outline does not reach row %.1f (z = %.4f m)' % (py, z))
    return front.m(max(xs) - min(xs)) / 2


def traced_keys(side, center, outline, columns, opts=None, front=None, front_outline=None, half_widths=None):
    """snout_head keys in metres about the head centre, read off a side outline and a front outline:
    one key per side-view column of `columns`, back to front (the outline's turning points: the back
    of the skull, the crown, the eye plane, the face plane, the muzzle root, the nose base). Each key's
    top and bottom are the side outline's topmost and bottommost crossings of its column; its half
    width is front_half_width of the front outline at the key's mid-height. The columns and the
    exponents are the caller's: nothing here chooses them.

    side, center: as side_key takes them. outline: the head's side outline, a views.json trace's 'px'
    on the side view. opts: one per key, the key's exponent or loft options (snout_head's fifth
    element, in metres), or None for an ellipse; None for all ellipses. front, front_outline: the front
    view's calibration and the head's front outline alone (no ears, hair or ruff). half_widths: one per
    key, None to read the front outline, an outline of its own in front-view pixels (a muzzle drawn
    inside the face, which the head's outline hides), or a half width in metres; None for the front
    outline everywhere. With an exponent other than 2 a key's half width is its superellipse's extent,
    which the section's polygon does not quite reach (Builder.loft), so the built front runs a little
    inside a width read here.

    Returns {'keys': [(s, top, bottom, half width[, opts])], 'reads': one per key {'px': its column,
    'top_py', 'bottom_py': the side rows read there, 'mid_z': its mid-height in model metres,
    'front_py': the front row read for its half width (None for a width given in metres), 'half_width':
    metres}}. Raises ValueError for a column the outline does not cross, columns that do not run back
    to front (s falling), a per-key list of another length than columns, and a width to read without a
    front calibration or a front outline."""
    n = len(columns)
    for name, v in (('opts', opts), ('half_widths', half_widths)):
        if v is not None and len(v) != n:
            raise ValueError('traced_keys: %s holds %d entries for %d columns' % (name, len(v), n))
    keys, reads = [], []
    for i, px in enumerate(columns):
        ys = _crossings(outline, px, 0)
        if not ys:
            raise ValueError('traced_keys: the side outline does not cross column %s (key %d)' % (px, i))
        top_py, bottom_py = min(ys), max(ys)
        mid_z = (side.z(top_py) + side.z(bottom_py)) / 2
        hw = half_widths[i] if half_widths is not None else None
        front_py = None
        if not isinstance(hw, (int, float)):
            poly = front_outline if hw is None else hw
            if front is None or poly is None:
                raise ValueError('traced_keys: key %d reads its half width off a front outline: give front and '
                                 'front_outline, or its half width in metres' % i)
            front_py = _row(front, mid_z)
            hw = front_half_width(front, poly, mid_z)
        keys.append(side_key(side, center, px, top_py, bottom_py, hw, opts[i] if opts is not None else None))
        reads.append({'px': px, 'top_py': round(top_py, 2), 'bottom_py': round(bottom_py, 2),
                      'mid_z': round(mid_z, 5), 'front_py': None if front_py is None else round(front_py, 2),
                      'half_width': round(hw, 5)})
    back = [i for i in range(1, n) if keys[i][0] >= keys[i - 1][0]]
    if back:
        raise ValueError('traced_keys: the columns must run from the back of the head to the front; key %d '
                         '(column %s) is not ahead of key %d' % (back[0], columns[back[0]], back[0] - 1))
    return {'keys': keys, 'reads': reads}


def front_envelope(keys, center, n, front, outline, nose=None, skull=None):
    """The front outline that snout_head keys in metres make, set against a drawn front outline row by
    row, before anything is built. Each key is the section Builder.loft lays
    (lpk.core.builder.loft_section: n sides, its exponent and loft options), centred at its mid-height;
    the loft runs straight between neighbouring sections and on to the apexes. The keys' half width at
    a height is half the span of every ring edge, band edge and apex edge crossing it: the outline of
    the mesh's edges before triangulation, which bounds its faces wherever a face's front projection
    is convex. Deformers run after the loft (taper_below, wedge_muzzle) are not in it.

    keys, center, n, nose, skull: as snout_head takes them with length, width, height and snout at 1
    (nose and skull optional: without them the ends add nothing). front, outline: the front view's
    calibration and the head's front outline alone (no ears, hair or ruff), a views.json trace's 'px'.

    Returns {'rows': one per front-view row the outline spans, top to bottom, {'py': the row, 'traced':
    half the outline's width there in metres, 'keys': half the keys' width there in metres (None where
    no section reaches the row), 'px': keys less traced in front-view pixels (positive: the keys are
    wider; None without keys), 'from': what sets the keys' width there: a key index for a section's
    own edge, [i, i + 1] for the band between two keys, 'nose' or 'skull' for an apex cone}, 'largest':
    the row of the largest |px|, None when no row compares}.
    Units: center m."""
    c = Vector(center)
    rings = []
    for i, k in enumerate(keys):
        mid = (k[1] + k[2]) / 2
        opts = _key_options(k[4], 1.0, i) if len(k) > 4 else None
        da, db = (opts or {}).get('off', (0.0, 0.0))
        rings.append([(c.x + da + x, c.z + mid + db + y)
                      for x, y in loft_section(k[3], (k[1] - k[2]) / 2, n, opts)])
    segs = []
    for i, ring in enumerate(rings):
        segs += [(p, q, i) for p, q in zip(ring, ring[1:] + ring[:1])]
        if i + 1 < len(rings):
            segs += [(p, q, [i, i + 1]) for p, q in zip(ring, rings[i + 1])]
    for apex, ring, name in ((nose, rings[-1], 'nose'), (skull, rings[0], 'skull')):
        if apex is not None:
            segs += [(p, (c.x, c.z + apex[1]), name) for p in ring]
    pys = [p[1] for p in outline]
    rows = []
    for py in range(math.ceil(min(pys)), math.floor(max(pys)) + 1):
        xs = _crossings(outline, py, 1)
        if not xs:
            continue
        z = front.z(py)
        traced = front.m(max(xs) - min(xs)) / 2
        hits = []
        for (x0, z0), (x1, z1), src in segs:
            if z0 == z1:
                if z0 == z:
                    hits += [(x0, src), (x1, src)]
            elif min(z0, z1) <= z <= max(z0, z1):
                hits.append((x0 + (z - z0) / (z1 - z0) * (x1 - x0), src))
        if not hits:
            rows.append({'py': py, 'traced': round(traced, 5), 'keys': None, 'px': None, 'from': None})
            continue
        lo, hi = min(hits, key=lambda h: h[0]), max(hits, key=lambda h: h[0])
        built = (hi[0] - lo[0]) / 2
        wide = hi if hi[0] - c.x >= c.x - lo[0] else lo
        rows.append({'py': py, 'traced': round(traced, 5), 'keys': round(built, 5),
                     'px': round((built - traced) / front.m(1.0), 1), 'from': wide[1]})
    rated = [r for r in rows if r['px'] is not None]
    return {'rows': rows, 'largest': max(rated, key=lambda r: abs(r['px'])) if rated else None}


def taper_below(b, part, centre, h, k, depth=0.9, start=None):
    """Narrow a head's lower part toward the chin: below `start` (a height; the head centre by
    default) x shrinks by up to k at `depth` half heights under the centre. Every vertex of the part
    below `start` narrows, the muzzle included: a start above the cheek line narrows the face at the
    eyes and can leave the eyes' outer corners off it.
    Units: centre m, h m (half height), k ratio, depth head units (half heights), start m (height)."""
    pid = b.pid(part)
    c = Vector(centre)
    z0 = c.z if start is None else start
    bottom = c.z - h * depth
    for v in b.bm.verts:
        if v[b.vpart] == pid and v.co.z < z0:
            f = min(1.0, (z0 - v.co.z) / max(z0 - bottom, 1e-6))
            v.co.x = c.x + (v.co.x - c.x) * (1 - k * f)


def wedge_muzzle(b, part, centre, length, h, keys, stop, k=0.75):
    """Turn snout_head's round muzzle sections into wedges: in front of the stop key every vertex
    above its section's middle moves toward the midline by up to k at the section's top, so the
    bridge narrows to a ridge over a flat-bottomed jaw and the nose reads as a triangle from the
    front. The default k is a starting value: on a narrow muzzle it can narrow the root and the middle
    past the drawing. On a head with stored hand edits a change of k moves the edited vertices too: the
    edits are offsets on unchanged topology, so no conflict stops the build.
    Units: centre m, length m (one head length), h m (half height), keys head units (snout_head's keys),
    stop index into keys, k ratio."""
    pid = b.pid(part)
    c = Vector(centre)
    ks = [kk for kk in keys[stop:]]                       # s decreasing toward the nose
    for v in b.bm.verts:
        if v[b.vpart] != pid:
            continue
        s = (v.co.y - c.y) / length
        if s > ks[0][0]:
            continue
        j = next((i for i in range(len(ks) - 1) if ks[i + 1][0] <= s), len(ks) - 2)
        a, e = ks[j], ks[j + 1]
        t = min(1.0, max(0.0, (s - a[0]) / (e[0] - a[0])))
        top = a[1] + (e[1] - a[1]) * t; bot = a[2] + (e[2] - a[2]) * t
        mid, half = c.z + h * (top + bot) / 2, h * (top - bot) / 2
        f = max(0.0, min(1.0, (v.co.z - mid) / max(half, 1e-6)))
        fade = min(1.0, (ks[0][0] - s) / max(ks[0][0] - ks[1][0], 1e-6))   # no step at the stop
        v.co.x = c.x + (v.co.x - c.x) * (1 - k * f * fade)


def lift_muzzle(b, part, y0, y1, dz):
    """Raise a muzzle's front by dz at y1 (the nose tip), fading to nothing at y0 (in front of the
    eyes), linear in y: straightens a drooping profile while keeping the keys and the part's topology,
    so stored hand edits still apply. Run it inside the head's
    part scope, before the scope's exit replays the stored edits (lpk.core.edits.apply), which must see
    the final form.
    Units: y0 m, y1 m, dz m."""
    pid = b.pid(part)
    for v in b.bm.verts:
        if v[b.vpart] == pid and v.co.y < y0:
            v.co.z += dz * min(1.0, (y0 - v.co.y) / (y0 - y1))
