"""The section kernel: the arithmetic of loft sections, the frames they lie in, and the rings that draw a loft
or a profile at their exact extents.

Units and frames. Lengths and points are metres in Blender space (Z up, the model faces -Y, `.L` is +X);
directions are 3-tuples the kernel normalizes. A section's frame has a normal (the section's own, else a fixed
axis, else the path direction through the centres of its neighbours), `a` (the section's own reference, else
at the first section the loft's reference, else the previous section's `a` parallel-transported onto this
normal; always projected off the normal) and `b = normal x a`. The n vertices of a section run from a toward
b, vertex j at pi / n + 2 pi j / n from a.

Half sizes are extents. A Section's `half` is its extent along +a and +b and `half_neg` its extent along -a
and -b, exactly, at every side count, exponent, ratio set and asymmetry: section_radii evaluates the unit
section with section_factors at the chosen side count and divides the requested extents by the unit
section's extents. A ProfileKey's top, bottom and half widths are exact extents the same way.

Kernels. section_factors and section_points are the section arithmetic Builder.loft lays its vertices with,
loft_frames the frame transport, ring_points one ring's vertex positions; loft_rings and profile_rings give
the rings of a loft of Sections and of a profile of ProfileKeys in Builder.loft's ring format, each ring
carrying its own frame, so Builder.loft lays exactly these frames.

Standard library only: the module imports on the host and inside Blender."""
import collections
import contextlib
import dataclasses
import math
import numbers

Vec3 = tuple[float, float, float]

# Numeric-noise tolerances of the frame kernel on unit vectors: a direction whose part transverse to a
# normal is at most DEGENERATE of its length is parallel to it; a path step whose component against a normal
# exceeds DEGENERATE of its length runs backward, and one whose component along both its normals exceeds it
# advances; consecutive normals whose cosine is below -1 + REVERSING turn back on themselves.
DEGENERATE = 1e-9
# The tolerance on the cosine of consecutive normals below which a frame turns back (see above).
REVERSING = 1e-10


class SectionError(ValueError):
    """A section, frame or ring the kernel refuses; the message names the value and the fix."""


# --- small helpers ---------------------------------------------------------------------------------------

def _dot(u, v):
    return u[0] * v[0] + u[1] * v[1] + u[2] * v[2]


def _cross(u, v):
    return (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])


def _norm(u):
    return math.sqrt(_dot(u, u))


def _sub(u, v):
    return (u[0] - v[0], u[1] - v[1], u[2] - v[2])


def _lerp(u, v, t):
    return tuple(x + (y - x) * t for x, y in zip(u, v))


def _unit(v, message):
    length = _norm(v)
    if length < 1e-12:
        raise SectionError(message)
    return (v[0] / length, v[1] / length, v[2] / length)


def _fmt(v):
    return '(%s)' % ', '.join('%.6g' % x for x in v)


def _listing(names):
    return ', '.join(names) if names else 'none'


@contextlib.contextmanager
def _context(prefix):
    """Prefix the message of a SectionError raised inside with what was being evaluated."""
    try:
        yield
    except SectionError as e:
        raise type(e)('%s: %s' % (prefix, e)) from None


def _name(value, what):
    if not isinstance(value, str) or not value or value != value.strip() or ':' in value:
        raise SectionError('%s must be a non-empty name without surrounding spaces or ":" (got %r)' % (what, value))
    return value


def _number(value, what):
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise SectionError('%s must be a number (got %r)' % (what, value))
    x = float(value)
    if not math.isfinite(x):
        raise SectionError('%s must be finite (got %r)' % (what, value))
    return x + 0.0


def _positive(value, what):
    x = _number(value, what)
    if x <= 0:
        raise SectionError('%s must be positive (got %r)' % (what, value))
    return x


def _items(value, n, what):
    if isinstance(value, (str, bytes, dict)):
        raise SectionError('%s must be %d values (got %r)' % (what, n, value))
    try:
        items = tuple(value)
    except TypeError:
        raise SectionError('%s must be %d values (got %r)' % (what, n, value)) from None
    if len(items) != n:
        raise SectionError('%s must be %d values (got %r)' % (what, n, value))
    return items


def _count(value, least, what):
    if isinstance(value, bool) or not isinstance(value, int) or value < least:
        raise SectionError('%s must be an integer of at least %d (got %r)' % (what, least, value))
    return value


def _vec(value, what):
    return tuple(_number(v, what) for v in _items(value, 3, what))


def _direction(value, what):
    v = _vec(value, what)
    length = _norm(v)
    if length < 1e-12:
        raise SectionError('%s must be a nonzero direction (got %r)' % (what, value))
    return (v[0] / length + 0.0, v[1] / length + 0.0, v[2] / length + 0.0)


# --- records ---------------------------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class Section:
    """One named cross-section of a loft.

    name: unique within its loft, without ':'. at: the path point of the section, m. half: its extents along
    +a and +b, m (exact at every side count). half_neg: its extents along -a and -b, m, when asymmetric (None
    takes the + extent). exponent: 2 an ellipse, larger values a rounded box (superellipse exponent, > 0).
    offset: the section's centre shift from `at` along a and b, m (the path still runs through `at`). ratios:
    periodic radius ratios (three or more, positive), sample k at pi / c + 2 pi k / c from a for c samples,
    resampled linearly for each side count. normal, ref: an explicit frame normal and reference for this
    section, kept through subdivision. Values are coerced to floats and directions normalized; a field the
    kernel cannot use raises SectionError."""
    name: str
    at: Vec3
    half: tuple[float, float]
    half_neg: tuple[float | None, float | None] = (None, None)
    exponent: float = 2.0
    offset: tuple[float, float] = (0.0, 0.0)
    ratios: tuple[float, ...] | None = None
    normal: Vec3 | None = None
    ref: Vec3 | None = None

    def __post_init__(self):
        put = object.__setattr__
        put(self, 'name', _name(self.name, 'a Section name'))
        what = 'Section %r' % self.name
        put(self, 'at', _vec(self.at, what + ' at'))
        put(self, 'half', tuple(_positive(v, what + ' half') for v in _items(self.half, 2, what + ' half')))
        put(self, 'half_neg', tuple(None if v is None else _positive(v, what + ' half_neg')
                                    for v in _items(self.half_neg, 2, what + ' half_neg')))
        put(self, 'exponent', _positive(self.exponent, what + ' exponent'))
        put(self, 'offset', tuple(_number(v, what + ' offset') for v in _items(self.offset, 2, what + ' offset')))
        if self.ratios is not None:
            if isinstance(self.ratios, (str, bytes, dict)):
                raise SectionError('%s ratios must be a tuple of numbers (got %r)' % (what, self.ratios))
            ratios = tuple(_positive(v, what + ' ratios') for v in self.ratios)
            if len(ratios) < 3:
                raise SectionError('%s ratios need three or more samples (got %d)' % (what, len(ratios)))
            put(self, 'ratios', ratios)
        if self.normal is not None:
            put(self, 'normal', _direction(self.normal, what + ' normal'))
        if self.ref is not None:
            put(self, 'ref', _direction(self.ref, what + ' ref'))


@dataclasses.dataclass(frozen=True)
class ProfileKey:
    """One named key of a profile, at its own section perpendicular to the profile's axis.

    s: distance along the axis from the origin, m. top, bottom: the section's top and bottom along `up` from
    the origin, m (top > bottom; exact extents). half_width: the half width across, m, of the section's
    upper half (exact). exponent: as Section.exponent. half_width_lower: the half width of the section's
    lower half (below its mid-height), m, or None for half_width."""
    name: str
    s: float
    top: float
    bottom: float
    half_width: float
    exponent: float = 2.0
    half_width_lower: float | None = None

    def __post_init__(self):
        put = object.__setattr__
        put(self, 'name', _name(self.name, 'a ProfileKey name'))
        what = 'ProfileKey %r' % self.name
        put(self, 's', _number(self.s, what + ' s'))
        put(self, 'top', _number(self.top, what + ' top'))
        put(self, 'bottom', _number(self.bottom, what + ' bottom'))
        if self.top <= self.bottom:
            raise SectionError('%s top must be above its bottom (got top %r, bottom %r)'
                               % (what, self.top, self.bottom))
        put(self, 'half_width', _positive(self.half_width, what + ' half_width'))
        put(self, 'exponent', _positive(self.exponent, what + ' exponent'))
        if self.half_width_lower is not None:
            put(self, 'half_width_lower', _positive(self.half_width_lower, what + ' half_width_lower'))


def _unique(names, what):
    for i, v in enumerate(names):
        if v in names[:i]:
            raise SectionError('%s names %r twice' % (what, v))


def _check_bands(names, values):
    """Refuse two consecutive sections that coincide entirely: the band between them has no area."""
    for i in range(len(values) - 1):
        if values[i] == values[i + 1]:
            raise SectionError('sections %r and %r coincide: the band between them has no area; move one or '
                               'change its size' % (names[i], names[i + 1]))


def _check_sections(sections):
    """`sections` as a tuple of Section records after the checks a loft needs: a list of two or more
    Sections with unique names, no two consecutive ones identical."""
    if isinstance(sections, (str, bytes, dict)) or not isinstance(sections, (list, tuple)):
        raise SectionError('sections must be a list of Section records (got %r)' % (sections,))
    sections = tuple(sections)
    for s in sections:
        if not isinstance(s, Section):
            raise SectionError('sections must be Section records (got %r)' % (s,))
    if len(sections) < 2:
        raise SectionError('a loft needs two or more sections (got %d)' % len(sections))
    names = [s.name for s in sections]
    _unique(names, 'the section list')
    _check_bands(names, [dataclasses.astuple(s)[1:] for s in sections])
    return sections


def _check_profile(origin, axis, up, keys):
    """(origin, axis, up, keys) of a profile after its checks: origin a point, axis and up unit directions with
    up made transverse to axis, keys a tuple of two or more ProfileKeys with unique names, ordered along the
    axis, advancing, no two consecutive ones identical."""
    origin = _vec(origin, 'origin')
    axis = _direction(axis, 'axis')
    up = _direction(up, 'up')
    try:
        up = transverse(up, axis)
    except SectionError:
        raise SectionError('up %s is parallel to axis %s: give an up across the axis'
                           % (_fmt(up), _fmt(axis))) from None
    if isinstance(keys, (str, bytes, dict)) or not isinstance(keys, (list, tuple)):
        raise SectionError('keys must be a list of ProfileKey records (got %r)' % (keys,))
    keys = tuple(keys)
    for k in keys:
        if not isinstance(k, ProfileKey):
            raise SectionError('keys must be ProfileKey records (got %r)' % (k,))
    if len(keys) < 2:
        raise SectionError('a profile needs two or more keys (got %d)' % len(keys))
    names = [k.name for k in keys]
    _unique(names, 'the key list')
    for k0, k1 in zip(keys, keys[1:]):
        if k1.s < k0.s:
            raise SectionError('key %r lies behind key %r along the axis (s %r < %r): order the keys along the '
                               'axis' % (k1.name, k0.name, k1.s, k0.s))
    _check_bands(names, [dataclasses.astuple(k)[1:] for k in keys])
    if keys[0].s == keys[-1].s:
        raise SectionError('the keys never advance along the axis (every s is %r)' % keys[0].s)
    return origin, axis, up, keys


# --- the section and frame kernel ------------------------------------------------------------------------

# (cos, sin) at 0, pi / 2, pi and 3 pi / 2.
_AXES = ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0))


def section_factors(ra, rb, sides, options=None):
    """The vertices of one loft section as (x, y, k) per vertex, in vertex order: the vertex sits at
    (a * x + b * y) * k * mult[j] from the section's centre (metres when ra and rb are), x along a, y along b.

    ra, rb: the radii along a and b. sides: the vertex count (>= 3). options (Builder.loft's names): 'p' the
    superellipse exponent (2 ellipse), 'ra_neg' / 'rb_neg' the radius on the -a / -b side, 'ra_bneg' the a
    radius of the vertices of the -b half (sin < 0), on both a sides, where ra and ra_neg then hold for the
    +b half only. Vertex j sits at pi / n + 2 pi j / n from a toward b. With p == 2 the factor k is
    1 / cos(pi / n): ra and rb are apothems (distances to the flat sides); otherwise k is 1 and the vertex
    lies on the superellipse of radii ra and rb. A vertex on an axis of the frame (an odd n puts one on -a,
    n = 2 mod 4 puts one on +b and one on -b) takes exact zero and unit components: the superellipse power
    |c| ** (2 / p) would otherwise lift the floating-point residue of cos and sin there (about 1e-16) to a
    visible offset for large exponents (0.15 of the radius at p = 40). The factors stay apart so that a
    caller multiplying in single precision rounds as Builder.loft does."""
    o = options or {}
    n = sides
    sc = 1.0 / math.cos(math.pi / n)
    ph = math.pi / n
    p = o.get('p', 2.0)
    ra_n = o.get('ra_neg', ra)
    rb_n = o.get('rb_neg', rb)
    ra_l = o.get('ra_bneg')
    out = []
    for j in range(n):
        th = ph + 2 * math.pi * j / n
        quarter, rest = divmod(2 * (1 + 2 * j), n)
        c, s = _AXES[quarter % 4] if rest == 0 else (math.cos(th), math.sin(th))
        if p == 2.0:
            kf = sc
        else:
            c = math.copysign(abs(c) ** (2.0 / p), c)
            s = math.copysign(abs(s) ** (2.0 / p), s)
            kf = 1.0
        x = c * (ra if c >= 0 else ra_n) if ra_l is None or s >= 0 else c * ra_l
        y = s * (rb if s >= 0 else rb_n)
        out.append((x, y, kf))
    return out


def section_points(ra, rb, sides, options=None):
    """The `sides` vertices of one section as (x, y) offsets from its centre (metres when ra and rb are), x
    along a, y along b, in vertex order: section_factors with options['mult'] (per-vertex radius
    multipliers, one per side) applied. Raises SectionError when 'mult' has another length."""
    mult = (options or {}).get('mult') or [1.0] * sides
    if len(mult) != sides:
        raise SectionError('mult needs one multiplier per side: %d for %d sides' % (len(mult), sides))
    return [(x * k * m, y * k * m) for (x, y, k), m in zip(section_factors(ra, rb, sides, options), mult)]


def resample(ratios, sides):
    """Periodic ratios resampled to `sides` vertices: sample k of c samples sits at pi / c + 2 pi k / c from
    a, and each vertex takes the linear interpolation between its two neighbouring samples. Returns a list of
    `sides` floats; `sides == len(ratios)` returns the ratios."""
    count = len(ratios)
    out = []
    for i in range(sides):
        position = ((math.pi / sides + 2 * math.pi * i / sides - math.pi / count) * count / (2 * math.pi)) % count
        j = math.floor(position)
        t = position - j
        j %= count
        out.append(ratios[j] + (ratios[(j + 1) % count] - ratios[j]) * t)
    return out


def transverse(a, normal):
    """The direction `a` with its component along the unit `normal` removed, normalized (a unit 3-tuple).
    Raises SectionError when `a` is parallel to `normal` (its transverse part at most DEGENERATE of its
    length)."""
    along = _dot(a, normal)
    v = (a[0] - along * normal[0], a[1] - along * normal[1], a[2] - along * normal[2])
    length = _norm(v)
    if length <= DEGENERATE * _norm(a):
        raise SectionError('the frame reference %s is parallel to the normal %s: give a reference across the '
                           'path' % (_fmt(a), _fmt(normal)))
    return (v[0] / length, v[1] / length, v[2] / length)


def transport(a, before, after):
    """Parallel transport of the transverse unit `a` from the unit normal `before` to the unit normal
    `after`: the shortest rotation taking `before` to `after` applied to `a`, then made transverse to
    `after`. Raises SectionError when the normals reverse (cosine below -1 + REVERSING): no rotation is the
    shortest one."""
    cosine = max(-1.0, min(1.0, _dot(before, after)))
    if cosine < -1 + REVERSING:
        raise SectionError('consecutive frame normals %s and %s reverse: give the section its own normal and ref'
                           % (_fmt(before), _fmt(after)))
    v = _cross(before, after)
    sine = _norm(v)
    if sine < 1e-12:
        return transverse(a, after)
    axis = (v[0] / sine, v[1] / sine, v[2] / sine)
    turn = _cross(axis, a)
    along = _dot(axis, a)
    return transverse(tuple(x * cosine + y * sine + z * along * (1 - cosine) for x, y, z in zip(a, turn, axis)),
                      after)


def loft_frames(centres, ref, *, axis=None, normals=None, refs=None, names=None):
    """The frame of every section of a loft: a list of (normal, a), unit 3-tuples; b = normal x a.

    centres: the path points of the sections, in order (metres, two or more). ref: the direction `a` starts
    from at the first section. axis: a fixed normal for every section, or None for the path direction
    through each section's neighbours (the end sections use their one neighbour). normals, refs: per-section
    overrides (lists with None for the rule): a section's own normal, and its own reference, which replaces
    the transported `a`. names: section names for the messages.

    Raises SectionError for fewer than two sections, a section without a path direction (its neighbours share
    a centre), a reference parallel to its normal, consecutive normals that reverse, a step between two
    sections that runs backward against either of their normals (the tube would turn inside out), and a path
    that never advances along its normals (every section in one plane)."""
    k = len(centres)
    label = list(names) if names is not None else [str(i) for i in range(k)]
    if k < 2:
        raise SectionError('a loft needs two or more sections (got %d)' % k)
    normals = list(normals) if normals is not None else [None] * k
    refs = list(refs) if refs is not None else [None] * k
    out_n = []
    for i in range(k):
        n = normals[i] or axis or _sub(centres[min(i + 1, k - 1)], centres[max(i - 1, 0)])
        out_n.append(_unit(n, 'section %r has no path direction: its neighbours share a centre; move them apart '
                              'or give the section a normal' % label[i]))
    advances = False
    for i in range(k - 1):
        if _dot(out_n[i], out_n[i + 1]) < -1 + REVERSING:
            raise SectionError('the normals of sections %r and %r reverse: a tube cannot turn back on itself '
                               'between two sections; add a section in the turn' % (label[i], label[i + 1]))
        step = _sub(centres[i + 1], centres[i])
        length = _norm(step)
        if length == 0:
            continue
        forward = (_dot(step, out_n[i]), _dot(step, out_n[i + 1]))
        if min(forward) < -DEGENERATE * length:
            raise SectionError('the path from section %r to %r runs backward against their normals: order the '
                               'sections along the path, or give normals that follow it' % (label[i], label[i + 1]))
        advances = advances or min(forward) > DEGENERATE * length
    if not advances:
        raise SectionError('the sections never advance along their normals (%s): they lie in one plane'
                           % _listing(label))
    out = []
    for i in range(k):
        with _context('section %r' % label[i]):
            if refs[i] is not None:
                a = transverse(refs[i], out_n[i])
            elif i == 0:
                a = transverse(ref, out_n[0])
            else:
                a = transport(out[-1][1], out_n[i - 1], out_n[i])
        out.append((out_n[i], a))
    return out


def _radii(ha, hna, hb, hnb, exponent, mult, sides, lower=None):
    """(ra, rb, options) for the section kernel that give the extents ha, hna (along +a, -a), hb, hnb (+b,
    -b) and, with `lower`, the extent of the -b half along a."""
    _count(sides, 3, 'sides')
    unit = {'p': exponent}
    if lower is not None:
        unit['ra_bneg'] = 1.0
    if mult is not None:
        unit['mult'] = mult
    points = section_points(1.0, 1.0, sides, unit)
    upper = [x for x, y in points if lower is None or y >= 0]
    extents = {'+a': [x for x in upper if x >= 0], '-a': [-x for x in upper if x < 0],
               '+b': [y for _, y in points if y >= 0], '-b': [-y for _, y in points if y < 0]}
    if lower is not None:
        extents['lower'] = [abs(x) for x, y in points if y < 0]
    for side, values in extents.items():
        if not values or max(values) <= 0:
            raise SectionError('a %d-sided section has no vertex on its %s side' % (sides, side))
    options = {'p': exponent, 'ra_neg': hna / max(extents['-a']), 'rb_neg': hnb / max(extents['-b'])}
    if lower is not None:
        options['ra_bneg'] = lower / max(extents['lower'])
    if mult is not None:
        options['mult'] = list(mult)
    return ha / max(extents['+a']), hb / max(extents['+b']), options


def section_radii(section, sides):
    """The kernel radii that draw the Section `section` with its exact extents at `sides`: (ra, rb, options),
    options holding 'p', 'ra_neg', 'rb_neg' and, with ratios, 'mult' (the resampled ratios).
    section_points(ra, rb, sides, options) then reaches half[0] along +a, half_neg[0] (or half[0]) along -a,
    half[1] along +b and half_neg[1] (or half[1]) along -b. The section's offset is a ring option of
    loft_rings."""
    _count(sides, 3, 'sides')
    mult = resample(section.ratios, sides) if section.ratios is not None else None
    hna = section.half[0] if section.half_neg[0] is None else section.half_neg[0]
    hnb = section.half[1] if section.half_neg[1] is None else section.half_neg[1]
    return _radii(section.half[0], hna, section.half[1], hnb, section.exponent, mult, sides)


# An evaluated section: path point (m), unit normal and a, extents (m) along +a, -a, +b, -b, the a extent of
# the -b half (or None), exponent, offset (m along a and b) and ratios as (ratios, ratios, t): the
# interpolation at t between two ratio sets (None: no ratios).
_Sample = collections.namedtuple('_Sample', 'centre normal a ha hna hb hnb lower exponent offset ratios')


def _loft_samples(sections, ref, axis):
    """The evaluated sections of a loft of checked Sections, `ref` and `axis` as loft_frames takes them."""
    frames = loft_frames([s.at for s in sections], ref, axis=axis, normals=[s.normal for s in sections],
                         refs=[s.ref for s in sections], names=[s.name for s in sections])
    return tuple(_Sample(s.at, n, a, s.half[0], s.half[0] if s.half_neg[0] is None else s.half_neg[0],
                         s.half[1], s.half[1] if s.half_neg[1] is None else s.half_neg[1], None, s.exponent,
                         s.offset, (s.ratios, None, 0.0))
                 for s, (n, a) in zip(sections, frames))


def _profile_samples(origin, axis, up, keys):
    """The evaluated sections of a checked profile (_check_profile's values)."""
    across = _unit(_cross(up, axis), 'up is parallel to axis')
    out = []
    for k in keys:
        mid, h = (k.top + k.bottom) / 2, (k.top - k.bottom) / 2
        centre = tuple(origin[i] + axis[i] * k.s + up[i] * mid for i in range(3))
        out.append(_Sample(centre, axis, across, k.half_width, k.half_width, h, h, k.half_width_lower,
                           k.exponent, (0.0, 0.0), (None, None, 0.0)))
    return tuple(out)


def _between(s0, s1, t):
    """The section at t (0..1) between two evaluated sections: values interpolated linearly, the normal
    interpolated and normalized, `a` transported from s0 and turned by t of the angle to s1's transported
    `a`. t == 0 returns s0."""
    if t == 0:
        return s0
    normal = _unit(_lerp(s0.normal, s1.normal, t), 'the normals between two sections cancel')
    ref = transport(s0.a, s0.normal, normal)
    target = transport(s1.a, s1.normal, normal)
    angle = math.atan2(_dot(normal, _cross(ref, target)), _dot(ref, target)) * t
    rotated = _cross(normal, ref)
    a = tuple(x * math.cos(angle) + y * math.sin(angle) for x, y in zip(ref, rotated))
    scalar = lambda u, v: u + (v - u) * t
    if s0.lower is None and s1.lower is None:
        lower = None
    else:
        lower = scalar(s0.ha if s0.lower is None else s0.lower, s1.ha if s1.lower is None else s1.lower)
    return _Sample(_lerp(s0.centre, s1.centre, t), normal, a, scalar(s0.ha, s1.ha), scalar(s0.hna, s1.hna),
                   scalar(s0.hb, s1.hb), scalar(s0.hnb, s1.hnb), lower, scalar(s0.exponent, s1.exponent),
                   _lerp(s0.offset, s1.offset, t), (s0.ratios[0], s1.ratios[0], t))


def _ring(s, sides):
    r0, r1, t = s.ratios
    mult = None
    if r0 is not None or r1 is not None:
        m0 = resample(r0, sides) if r0 is not None else [1.0] * sides
        if t == 0:
            mult = m0
        else:
            m1 = resample(r1, sides) if r1 is not None else [1.0] * sides
            mult = [x + (y - x) * t for x, y in zip(m0, m1)]
    ra, rb, options = _radii(s.ha, s.hna, s.hb, s.hnb, s.exponent, mult, sides, s.lower)
    if s.offset != (0.0, 0.0):
        options['off'] = s.offset
    options['axis'] = s.normal
    options['ref'] = s.a
    return (s.centre, ra, rb, options)


def _rings(samples, sides, divisions):
    _count(sides, 3, 'sides')
    _count(divisions, 1, 'divisions')
    out = []
    for k in range(len(samples) - 1):
        for i in range(divisions):
            out.append(_ring(_between(samples[k], samples[k + 1], i / divisions), sides))
    out.append(_ring(samples[-1], sides))
    return out


def loft_rings(sections, ref, sides, *, axis=None, divisions=1):
    """The rings that draw a loft through `sections` at `sides` vertices per ring, with `divisions` rings per
    interval between two sections (the first one at the section): a list of (centre, ra, rb, options) in
    Builder.loft's ring format.

    sections: two or more Section records in path order, unique names. ref: the direction `a` starts from at
    the first section (projected off its normal). axis: a fixed normal for every section (parallel sections),
    or None for the path direction. centre is the path point (m); ra, rb and options come from the exact
    extents (section_radii); options also hold 'off' (a nonzero offset) and the ring's frame as 'axis' (its
    normal) and 'ref' (its a), so Builder.loft lays these rings with exactly these frames. Intermediate rings
    interpolate every section value linearly and their frames as the sections' (normal interpolated, a
    transported and turned), so the section rings stay where the sections are. Raises SectionError for
    sections that are not two or more Sections with unique names, two consecutive identical sections, a zero
    ref or axis, sides below 3, divisions below 1, and whatever loft_frames refuses."""
    sections = _check_sections(sections)
    ref = _direction(ref, 'ref')
    axis = None if axis is None else _direction(axis, 'axis')
    return _rings(_loft_samples(sections, ref, axis), sides, divisions)


def profile_rings(origin, axis, up, keys, sides, *, divisions=1):
    """The rings that draw a profile at `sides` vertices per ring, with `divisions` rings per interval
    between two keys: a list of (centre, ra, rb, options) in Builder.loft's ring format, as loft_rings gives
    them.

    origin: the point the keys are measured from (m). axis: the direction the keys run along; every section
    is perpendicular to it. up: the direction top and bottom are measured along (made transverse to axis).
    keys: two or more ProfileKey records ordered along the axis, unique names. A key's section is centred at
    its mid-height, origin + axis * s + up * (top + bottom) / 2, and reaches its top, bottom and half widths
    exactly; its a axis is up x axis (across) and its b axis up. Raises SectionError for a zero axis or up, an
    up along the axis, keys that are not two or more ProfileKeys with unique names in axis order, keys that
    never advance or two consecutive identical keys, sides below 3 and divisions below 1."""
    origin, axis, up, keys = _check_profile(origin, axis, up, keys)
    return _rings(_profile_samples(origin, axis, up, keys), sides, divisions)


def ring_points(centre, normal, a, ra, rb, sides, options=None):
    """The `sides` vertex positions (m) of one ring with path point `centre`, unit `normal` and unit
    transverse `a`: the centre moved by options['off'] (da, db) along a and b = normal x a, plus each vertex
    of section_factors times its 'mult' entry, in Builder.loft's order of operations (in double precision).
    Raises SectionError when 'mult' has another length than `sides`."""
    options = options or {}
    b = _cross(normal, a)
    da, db = options.get('off', (0.0, 0.0))
    c = tuple(centre[i] + a[i] * da + b[i] * db for i in range(3))
    mult = options.get('mult') or [1.0] * sides
    if len(mult) != sides:
        raise SectionError('mult needs one multiplier per side: %d for %d sides' % (len(mult), sides))
    return [tuple(c[i] + (a[i] * x + b[i] * y) * k * m for i in range(3))
            for (x, y, k), m in zip(section_factors(ra, rb, sides, options), mult)]
