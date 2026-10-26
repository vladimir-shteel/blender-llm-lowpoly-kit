"""Host tests of the shapes the forms take and give (no Blender needed: bpy, bmesh and mathutils are replaced
by stand-ins while the modules are imported, and a recording builder stands in for Builder): snout_head's
keys with and without their exponent or loft options and the head-unit mapping it returns, profile_head's
loft of plain profile keys at the kernel's exact extents, its apexes and colours by key, Builder.loft's
sections with and without the lower half width, the readers
from traced views to metre keys and the front envelope the keys make, the colour sources that read a loft's
rings as BMVerts or as points, straight_tail's loft along its direction, and on the stand-ins of
blender_stand_ins the garments over a trunk's sections (torso.section_at, skirt, belt), hair.long_beard and the
hard-surface forms (sections, steps, facing, colours by band and side, triangle counts).

python tests/test_forms.py"""
import importlib
import math
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from blender_stand_ins import BVHTree, Vector as _Vector, stand_ins as _blender_stand_ins  # noqa: E402


with _blender_stand_ins():
    builder = importlib.import_module('lpk.core.builder')
    views = importlib.import_module('lpk.core.views')
    shapes = importlib.import_module('lpk.core.shapes')
    head = importlib.import_module('lpk.forms.head')
    tails = importlib.import_module('lpk.forms.tails')
    sections = importlib.import_module('lpk.core.sections')


class _Recorder:
    """Records what a form asks of its builder: the vertices it makes, the faces with their colours, and
    the arguments of each Builder.loft call (which returns no rings)."""

    def __init__(self):
        self.parts, self.verts, self.faces, self.lofts = [], [], [], []

    def pid(self, name):
        if name not in self.parts:
            self.parts.append(name)
        return self.parts.index(name)

    def vert(self, co, pid):
        v = types.SimpleNamespace(co=_Vector(co), part=pid)
        self.verts.append(v)
        return v

    def face(self, verts, col, hint=None):
        self.faces.append(([self.verts.index(v) for v in verts], col))

    def loft(self, part, rings, n, ref, color, **kw):
        self.lofts.append({'part': part, 'rings': rings, 'n': n, 'ref': ref, 'color': color, **kw})
        return ['rings of %s' % part]


def _keys(rings):
    return [tuple(r[1:]) for r in rings]


def test_snout_head_takes_keys_with_or_without_their_exponent():
    full = head.MUZZLE_KEYS
    plain = tuple(k[:4] for k in full)
    built = {}
    for name, keys in (('full', full), ('plain', plain)):
        b = _Recorder()
        out = head.snout_head(b, 'head', (0.0, 0.0, 1.6), 0.2, 0.1, 0.1, 'skin', keys=keys)
        (loft,) = b.lofts
        built[name] = loft['rings']
        assert out['eye_x'] == keys[head.MUZZLE_STOP][3] * 0.1
    assert [r[3] for r in built['full']] == [{'p': k[4]} for k in full], 'the fifth element is the exponent'
    assert [r[3] for r in built['plain']] == [{}] * len(plain), \
        'without the exponent the sections are Builder.loft ellipses'
    assert [r[:3] for r in built['plain']] == [r[:3] for r in built['full']], 'the outline does not change'


def test_snout_head_takes_all_loft_options_in_head_units():
    k = head.MUZZLE_KEYS
    mult = [1.0, 1.1] * 5
    keys = k[:3] + ((k[3][:4] + ({'p': 3.0, 'ra_bneg': 0.5, 'ra_neg': 0.9, 'mult': mult},)),) + k[4:]
    b = _Recorder()
    head.snout_head(b, 'head', (0.0, 0.0, 1.6), 0.2, 0.1, 0.1, 'skin', keys=keys)
    (loft,) = b.lofts
    o = loft['rings'][3][3]
    assert o['p'] == 3.0 and o['mult'] == mult and set(o) == {'p', 'ra_bneg', 'ra_neg', 'mult'}, o
    assert math.isclose(o['ra_bneg'], 0.5 * 0.1) and math.isclose(o['ra_neg'], 0.9 * 0.1), \
        'the half widths scale by the head half width, the exponent and the factors do not'
    assert [r[3] for i, r in enumerate(loft['rings']) if i != 3] == [{'p': e[4]} for i, e in enumerate(k) if i != 3]
    extra = {'rb_neg': 0.4, 'off': (0.2, 0.3)}
    keys = k[:3] + ((k[3][:4] + (extra,)),) + k[4:]
    shifted = _Recorder()
    head.snout_head(shifted, 'head', (0.0, 0.0, 1.6), 0.2, 0.1, 0.15, 'skin', keys=keys)
    o = shifted.lofts[0]['rings'][3][3]
    assert math.isclose(o['rb_neg'], 0.06), o
    assert _close(o['off'], (0.02, 0.045)), o
    assert extra == {'rb_neg': 0.4, 'off': (0.2, 0.3)}, 'caller options stay in head units'
    assert 'key 3' in _raises(ValueError, head._key_options, {'unknown': 1}, 0.1, 3)


def test_snout_head_pt_maps_head_units_to_world_with_the_snout_stretch():
    b = _Recorder()
    c = (0.01, 0.02, 1.6)
    out = head.snout_head(b, 'head', c, 0.2, 0.1, 0.12, 'skin', snout=1.3)
    (loft,) = b.lofts
    pt = out['pt']
    assert _close(pt(*head.MUZZLE_NOSE), loft['cap1']), 'the nose apex in head units lands on the built apex'
    assert _close(pt(*head.MUZZLE_SKULL), loft['cap0']), 'behind the stop nothing stretches'
    for (s, top, *_), (centre, ra, rb, _) in zip(head.MUZZLE_KEYS, loft['rings']):
        assert _close(pt(s, top), centre + _Vector((0.0, 0.0, rb))), 'a key top in head units lands on the ring top'
    assert _close(pt(0.0, 0.0, 1.0), _Vector(c) + _Vector((0.1, 0.0, 0.0))), 'x runs in half widths'


def _loft(rings, n):
    """Builder.loft itself run on a recording builder: the vertices of each ring."""
    b = _Recorder()
    rings_out = builder.Builder.loft(b, 'head', rings, n, (1.0, 0.0, 0.0), 'skin', axis=(0.0, -1.0, 0.0))
    return [[list(v.co) for v in ring] for ring in rings_out]


def _reference_ring(ra, rb, n, o):
    """The superellipse section Builder.loft lays without a lower half width (ra_bneg), computed
    independently, with a vertex on an axis of the ring's frame exactly on it
    (lpk.core.sections.section_factors)."""
    sc = 1.0 / math.cos(math.pi / n)
    ph = math.pi / n
    mult = o.get('mult') or [1.0] * n
    p = o.get('p', 2.0)
    ra_n = o.get('ra_neg', ra); rb_n = o.get('rb_neg', rb)
    out = []
    for j in range(n):
        th = ph + 2 * math.pi * j / n
        quarter, rest = divmod(2 * (1 + 2 * j), n)
        c, s = ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0))[quarter % 4] if rest == 0 else (math.cos(th),
                                                                                                    math.sin(th))
        if p == 2.0:
            kf = sc
        else:
            c = math.copysign(abs(c) ** (2.0 / p), c); s = math.copysign(abs(s) ** (2.0 / p), s); kf = 1.0
        x = c * (ra if c >= 0 else ra_n); y = s * (rb if s >= 0 else rb_n)
        out.append((x, y, kf, mult[j]))
    return out


def test_builder_loft_sections_without_the_lower_half_width_match_the_reference_section():
    n = 10
    opts = (None, {}, {'p': 3.0}, {'ra_neg': 0.03, 'rb_neg': 0.02}, [1.0, 1.2] * 5, {'p': 2.6, 'mult': [0.9] * n})
    rings = [((0.0, -0.01 * i, 1.6), 0.05, 0.04) + ((o,) if o is not None else ()) for i, o in enumerate(opts)]
    built = _loft(rings, n)
    for (centre, ra, rb, *rest), ring in zip(rings, built):
        o = rest[0] if rest and rest[0] else {}
        o = o if isinstance(o, dict) else {'mult': o}
        a, b = _Vector((1.0, 0.0, 0.0)), _Vector((0.0, 0.0, 1.0))
        want = [list(_Vector(centre) + (a * x + b * y) * kf * m) for x, y, kf, m in _reference_ring(ra, rb, n, o)]
        assert ring == want, (o, ring, want)
        assert all(_close(v, _Vector(centre) + _Vector((x, 0.0, y))) for v, (x, y) in
                   zip(ring, builder.loft_section(ra, rb, n, rest[0] if rest else None))), 'loft_section agrees'


def test_builder_loft_lower_half_width_narrows_only_below_the_mid_height():
    for n, p in ((10, 2.0), (9, 2.6)):
        plain = builder.loft_section(0.05, 0.04, n, {'p': p})
        low = builder.loft_section(0.05, 0.04, n, {'p': p, 'ra_bneg': 0.03})
        for (x0, y0), (x1, y1) in zip(plain, low):
            assert y1 == y0, 'the heights stay'
            assert x1 == x0 if y0 >= 0 else math.isclose(x1, x0 * 0.6), (n, p, x0, y0, x1)
        top_half = [abs(x) for x, y in low if y >= 0]
        assert max(top_half) <= 0.05 + 1e-12 and max(abs(x) for x, y in low if y < 0) <= 0.03 + 1e-12


def _raises(exc, fn, *args, **kw):
    try:
        fn(*args, **kw)
    except exc as e:
        return str(e)
    raise AssertionError('%s not raised' % exc.__name__)


def _side_and_front():
    """A side view facing left at 1 cm a pixel, its rows the front's, model y = 0 on column 100, and a
    front view at the same scale whose midline is column 100: the soles on row 200 of both."""
    side = views.Calib(2.0, 0, 200, (200, 200))
    side.zero_px, side.facing = 100, 'left'
    return side, views.Calib(2.0, 0, 200, (200, 200))


# A side outline in side-view pixels: the skull from column 140 back to front to the nose at column 50, its
# top falling from row 40 to row 60 between columns 100 and 50 and its bottom flat on row 80.
SIDE = [(140, 40), (100, 40), (50, 60), (50, 80), (140, 80)]


def test_side_key_and_side_point_read_metres_about_the_head_centre():
    side, _ = _side_and_front()
    c = (0.0, 0.1, 1.4)
    k = head.side_key(side, c, 70, 52, 80, 0.07)
    assert len(k) == 4 and _close(k, (-0.4, 0.08, -0.2, 0.07)), k
    assert head.side_key(side, c, 70, 52, 80, 0.07, 2.6)[4] == 2.6
    assert _close(head.side_point(side, c, 50, 70), (-0.6, -0.1)), 'the column ahead of the centre is negative'
    side.facing = 'right'
    assert _close(head.side_point(side, c, 150, 70), (-0.6, -0.1)), 'a view facing right counts the other way'


def test_front_half_width_reads_the_row_at_a_height_through_any_calibration():
    _, front = _side_and_front()
    diamond = [(100, 50), (130, 80), (100, 110), (70, 80)]
    assert math.isclose(head.front_half_width(front, diamond, front.z(80)), 0.3)
    assert math.isclose(head.front_half_width(front, diamond, front.z(65)), 0.15)
    crop = views.CropOfCalib(front, (40, 40), 2.0, (160, 160))
    in_crop = [((x - 40) * 2, (y - 40) * 2) for x, y in diamond]
    assert math.isclose(head.front_half_width(crop, in_crop, front.z(65)), 0.15), 'a zoomed crop reads the same'
    assert 'row' in _raises(ValueError, head.front_half_width, front, diamond, front.z(120))


def test_traced_keys_read_tops_bottoms_and_mid_height_widths_off_the_outlines():
    side, front = _side_and_front()
    c = (0.0, 0.0, 1.4)
    face = [(100, 30), (130, 55), (130, 72), (100, 95), (70, 72), (70, 55)]
    muzzle = [(100, 55), (112, 62), (112, 78), (100, 82), (88, 78), (88, 62)]
    out = head.traced_keys(side, c, SIDE, (120, 100, 60), opts=(2.2, None, {'p': 2.6}), front=front,
                           front_outline=face, half_widths=(None, None, muzzle))
    (k0, k1, k2), reads = out['keys'], out['reads']
    assert _close(k0[:4], (0.2, 0.2, -0.2, 0.3)) and k0[4] == 2.2, k0
    assert len(k1) == 4 and _close(k1, (0.0, 0.2, -0.2, 0.3)), 'None opts: an ellipse key of four elements'
    assert _close(k2[:4], (-0.4, 0.04, -0.2, 0.12)) and k2[4] == {'p': 2.6}, 'the muzzle on its own outline'
    assert [r['top_py'] for r in reads] == [40.0, 40.0, 56.0] and reads[2]['front_py'] == 68.0
    assert reads[0]['mid_z'] == 1.4 and reads[0]['half_width'] == 0.3
    metres = head.traced_keys(side, c, SIDE, (120, 60), half_widths=(0.25, 0.05))
    assert [k[3] for k in metres['keys']] == [0.25, 0.05] and metres['reads'][0]['front_py'] is None
    assert 'column 160' in _raises(ValueError, head.traced_keys, side, c, SIDE, (160,), half_widths=(0.1,))
    assert 'back of the head' in _raises(ValueError, head.traced_keys, side, c, SIDE, (60, 120),
                                         half_widths=(0.1, 0.1))
    assert '2 entries' in _raises(ValueError, head.traced_keys, side, c, SIDE, (120,), opts=(2, 2),
                                  half_widths=(0.1,))
    assert 'front' in _raises(ValueError, head.traced_keys, side, c, SIDE, (120,))


def test_front_envelope_sets_the_sections_against_the_drawn_front():
    _, front = _side_and_front()
    c = (0.0, 0.0, 1.205)
    # With four sides an ellipse section is the rectangle of its apothems: half width 0.3 between the
    # heights 1.005 and 1.405, rows 99.5 to 59.5 of the front view, which the drawn rectangle spans.
    keys = ((0.2, 0.2, -0.2, 0.3), (-0.2, 0.2, -0.2, 0.3))
    rect = [(70, 60), (130, 60), (130, 99), (70, 99)]
    out = head.front_envelope(keys, c, 4, front, rect)
    assert [r['py'] for r in out['rows']] == list(range(60, 100))
    assert all(r['px'] == 0.0 and math.isclose(r['keys'], 0.3) for r in out['rows']), out['rows']
    low = tuple(k + ({'ra_bneg': 0.1},) for k in keys)
    out = head.front_envelope(low, c, 4, front, rect)
    for r in out['rows']:
        want = 0.1 + (front.z(r['py']) - 1.005) / 0.4 * 0.2       # the side slants from 0.1 up to 0.3
        assert math.isclose(r['keys'], want, abs_tol=1e-5) and math.isclose(r['px'], (want - 0.3) * 100,
                                                                             abs_tol=0.051), r
    assert out['largest']['py'] == 99 and out['largest']['px'] < -19
    one = (keys[0], keys[1] + ({'ra_bneg': 0.1},))
    assert head.front_envelope(one, c, 4, front, rect)['largest']['px'] == 0.0, 'the full key still sets the width'
    tall = [(70, 40), (130, 40), (130, 99), (70, 99)]
    out = head.front_envelope(keys, c, 4, front, tall, nose=(-0.3, 0.4))
    rows = {r['py']: r for r in out['rows']}
    assert rows[50]['from'] == 'nose' and math.isclose(rows[50]['keys'], 0.1575, abs_tol=1e-5), rows[50]
    assert rows[40]['from'] == 'nose' and rows[40]['keys'] < 0.01, 'the cone closes toward its apex'
    assert rows[70]['from'] in (0, 1) and math.isclose(rows[70]['keys'], 0.3), rows[70]
    assert head.front_envelope(keys, c, 4, front, tall)['rows'][0]['keys'] is None, 'no section reaches row 40'


def test_front_envelope_applies_ring_offset_and_lower_height():
    _, front = _side_and_front()
    keys = ((0.2, 0.2, -0.2, 0.3, {'off': (0.1, 0.1), 'rb_neg': 0.1}),
            (-0.2, 0.2, -0.2, 0.3, {'off': (0.1, 0.1), 'rb_neg': 0.1}))
    # With the offset the four-sided sections span heights 1.205 to 1.505 (1.005 to 1.405 without it).
    rect = [(80, 50), (140, 50), (140, 79), (80, 79)]
    out = head.front_envelope(keys, (0.0, 0.0, 1.205), 4, front, rect)
    assert all(r['px'] == 0.0 for r in out['rows']), out


def _loft_rings(points):
    """Three rings of four points round the Y axis, as BMVerts (objects with .co) and as plain points."""
    as_points = [[_Vector(p) for p in ring] for ring in points]
    return [[types.SimpleNamespace(co=_Vector(p)) for p in ring] for ring in points], as_points


RINGS = [[(math.cos(a) * r, y, math.sin(a) * r) for a in (0.0, math.pi / 2, math.pi, 1.5 * math.pi)]
         for y, r in ((0.0, 0.1), (0.2, 0.08), (0.4, 0.06))]


def test_band_source_reads_a_lofts_rings_as_bmverts_or_points():
    made = []
    for rings in _loft_rings(RINGS):
        b = _Recorder()
        shapes.band_source(b, 'tail', rings, 2, (0.0, 0.5, 0.0), ('light', 'dark'), 'dark')
        made.append(([list(v.co) for v in b.verts], b.faces))
    assert made[0] == made[1], 'the same source from BMVerts and from their positions'
    assert len(made[0][0]) == 3 * 4 + 1 and {c for _, c in made[0][1]} == {'light', 'dark'}


def test_ring_band_reads_a_lofts_rings_as_bmverts_or_points():
    made = []
    verts, points = _loft_rings(RINGS)
    for rings in (verts, points):
        b = _Recorder()
        shapes.ring_band(b, 'tail', rings, 'dark', 0.02)
        made.append(([list(v.co) for v in b.verts], b.faces, b.marks))
    assert made[0] == made[1], 'the same band from BMVerts and from their positions'
    assert len(made[0][0]) == 2 * 4 and made[0][2][0]['points'][0] == [0.08, 0.2, 0.0]
    assert [[list(v.co) for v in r] for r in verts] == [[list(p) for p in r] for r in points] \
        == [[list(p) for p in r] for r in RINGS], 'the rings passed in are not moved'


def _close(a, b):
    return all(math.isclose(x, y, abs_tol=1e-12) for x, y in zip(a, b))


def test_straight_tail_lofts_its_profile_along_its_direction_to_an_apex():
    b = _Recorder()
    profile = [(-0.02, 0.03, 0.03), (0.1, 0.05, 0.04, {'p': 3.0}), (0.4, 0.02, 0.02)]
    root = (0.0, 0.1, 0.9)
    out = tails.straight_tail(b, 'tail', root, (0.0, 2.0, -2.0), 0.5, profile, 6, (1, 0, 0), 'fur')
    (loft,) = b.lofts
    assert out == ['rings of tail'], 'the rings Builder.loft returns'
    d = _Vector((0.0, 1.0, -1.0)).normalized()
    for (centre, *rest), (s, *size) in zip(loft['rings'], profile):
        assert _close(centre, _Vector(root) + d * s) and rest == size, (centre, s)
    assert _close(loft['cap1'], _Vector(root) + d * 0.5) and loft['cap0'] is None, 'an open root, the apex at length'
    assert _close(loft['axis'], d) and loft['n'] == 6 and loft['ref'] == (1, 0, 0) and loft['color'] == 'fur'
    assert loft['col0'] is None and loft['col1'] is None
    b = _Recorder()
    tails.straight_tail(b, 'tail', root, (0.0, 1.0, 0.0), 0.5, profile, 6, (1, 0, 0), 'fur', cap0=(0.0, 0.0, 0.9),
                        cap1='flat', col1='dark')
    (loft,) = b.lofts
    assert loft['cap0'] == (0.0, 0.0, 0.9) and loft['cap1'] == 'flat' and loft['col1'] == 'dark'


HEAD_ORIGIN = (0.0, 0.1, 1.5)


def _head_keys(**changed):
    """Head profile keys about HEAD_ORIGIN along -Y, from the back of the skull to the nose; changed: {key
    name: {field: value}} for the keys a correction changes."""
    keys = [('back', 0.0, 0.10, -0.09, 0.07), ('skull', 0.07, 0.14, -0.12, 0.13, 3.0),
            ('muzzle', 0.30, 0.01, -0.11, 0.075), ('nose', 0.36, -0.005, -0.085, 0.04)]
    made = []
    for name, *values in keys:
        fields = dict(zip(('s', 'top', 'bottom', 'half_width', 'exponent'), values), **changed.get(name, {}))
        made.append(sections.ProfileKey(name, **fields))
    return made


def test_profile_head_lofts_its_keys_to_its_apexes():
    keys = _head_keys()
    b = _Recorder()
    out = head.profile_head(b, 'head', HEAD_ORIGIN, keys, 8, {'back': 'fur', 'muzzle': 'dark'}, nose=(-0.39, -0.06),
                            skull=(0.03, 0.0), stop='skull', eye_height=0.02)
    (loft,) = b.lofts
    rings = sections.profile_rings(HEAD_ORIGIN, (0.0, -1.0, 0.0), (0.0, 0.0, 1.0), keys, 8)
    assert loft['rings'] == rings and loft['n'] == 8, "the keys at their exact extents, as a profile block lays them"
    assert _close(loft['cap0'], (0.0, 0.13, 1.5)) and _close(loft['cap1'], (0.0, -0.29, 1.44)), \
        'the apexes in metres about the origin, s toward the back'
    assert [loft['color'](i, 0, None) for i in range(3)] == ['fur', 'fur', 'dark'], 'a band takes its last named key'
    for (s, top, bottom, half, opts), (centre, ra, rb, options), k in zip(out['keys'], rings, keys):
        assert s == -k.s, 'the returned keys run toward the back, as snout_head keys about the origin'
        assert _close(_Vector(HEAD_ORIGIN) + _Vector((0.0, s, (top + bottom) / 2)), centre)
        assert math.isclose(half, ra) and math.isclose((top - bottom) / 2, rb)
        assert opts == {k: options[k] for k in ('p', 'ra_neg', 'rb_neg')}, 'the keys lay the ring as lofted'
    assert out['names'] == ['back', 'skull', 'muzzle', 'nose'] and out['stop'] == 1
    assert _close(out['eye'], (0.1 - 0.07, 1.52)) and math.isclose(out['eye_x'], 0.13)
    assert _close(out['pt'](0.1, 0.02, 0.03), (0.03, 0.2, 1.52))


def test_profile_head_follows_a_corrected_key():
    before, after = _Recorder(), _Recorder()
    for b, keys in ((before, _head_keys()), (after, _head_keys(muzzle={'half_width': 0.09, 'bottom': -0.12}))):
        head.profile_head(b, 'head', HEAD_ORIGIN, keys, 8, 'fur', nose=(-0.39, -0.06), skull=(0.03, 0.0))
    changed = [i for i, (x, y) in enumerate(zip(before.lofts[0]['rings'], after.lofts[0]['rings'])) if x != y]
    assert changed == [2], 'the corrected key, and only it, changes its ring'


def test_profile_head_refuses_what_it_cannot_build():
    keys = _head_keys()
    cases = (
        dict(nose=(-0.39, -0.06), skull=(-0.01, 0.0)),
        dict(nose=(-0.30, -0.06), skull=(0.03, 0.0)),
        dict(nose=(-0.39, -0.06), skull=(0.03, 0.0), stop='brow', eye_height=0.0),
        dict(nose=(-0.39, -0.06), skull=(0.03, 0.0), stop='skull'),
        dict(nose=(-0.39, -0.06), skull=(0.03, 0.0), color={'skull': 'fur'}),
        dict(nose=(-0.39, -0.06), skull=(0.03, 0.0), color={'back': 'fur', 'nose': 'dark'}),
        dict(nose=(-0.39, -0.06), skull=(0.03, 0.0), color={'back': 'fur', 'chin': 'dark'}),
        dict(nose=(-0.39, -0.06), skull=(0.03, 0.0), axis=(0.0, 0.0, 1.0), up=(0.0, -1.0, 0.0)),
        dict(nose=(-0.39, -0.06), skull=(0.03, 0.0), keys=keys[::-1]),
        dict(nose=(-0.39, -0.06), skull=(0.03, 0.0), keys=keys[:1]),
    )
    for case in cases:
        args = dict({'color': 'fur', 'keys': keys}, **case)
        try:
            head.profile_head(_Recorder(), 'head', HEAD_ORIGIN, args.pop('keys'), 8, args.pop('color'), **args)
        except ValueError:
            continue
        raise AssertionError('profile_head took %r' % (case,))



# -- garments over the trunk and the long beard (torso.section_at, skirt, belt; hair.long_beard), on the
# stand-ins of blender_stand_ins with the real Builder ---------------------------------------------------

with _blender_stand_ins():
    _gbuilder = importlib.import_module('lpk.core.builder')
    _gsections = importlib.import_module('lpk.core.sections')
    _torso = importlib.import_module('lpk.forms.torso')
    _hair = importlib.import_module('lpk.forms.hair')

_GPALETTE = {'cloth': (0.5, 0.3, 0.2), 'belt': (0.1, 0.1, 0.1), 'hair': (0.4, 0.2, 0.1), 'tip': (0.9, 0.8, 0.3)}


def _body():
    """A trunk's sections bottom up: crotch (a rounded box), hips, waist, chest."""
    S = _gsections.Section
    return [S('crotch', (0.0, 0.01, 0.80), (0.16, 0.10), exponent=3.0),
            S('hips', (0.0, 0.0, 0.90), (0.18, 0.11), half_neg=(None, 0.13)),
            S('waist', (0.0, -0.01, 1.00), (0.15, 0.09)),
            S('chest', (0.0, 0.0, 1.20), (0.17, 0.12), ratios=(1.0, 1.2, 1.0, 1.2))]


def _extents(ring):
    xs, ys = [v.co.x for v in ring], [v.co.y for v in ring]
    return min(xs), max(xs), min(ys), max(ys)


def test_section_at_interpolates_the_trunk_between_its_sections():
    body = _body()
    cut = _torso.section_at(body, 0.95, name='belt')
    assert cut.name == 'belt' and _close(cut.at, (0.0, -0.005, 0.95))
    assert _close(cut.half, (0.165, 0.10)) and cut.half_neg[0] is None and math.isclose(cut.half_neg[1], 0.11)
    low = _torso.section_at(body, 0.85)
    assert low.half_neg[0] is None and math.isclose(low.half_neg[1], 0.115), 'only the side that differs is resolved'
    assert math.isclose(low.exponent, 2.5)
    ratios = _torso.section_at(body, 1.10).ratios
    assert len(ratios) == 4 and _close(ratios, (1.0, 1.1, 1.0, 1.1)), 'ratios blend with ratios of 1'
    assert _torso.section_at(body, 0.80).half == body[0].half and _torso.section_at(body, 1.20).half == body[-1].half
    assert _torso.section_at(body, 0.90).half_neg == (None, 0.13), 'a cut at a section is that section'
    for bad in ((body, 0.79), (body, 1.21), (body[::-1], 1.0), (body[:1], 0.8)):
        _raises(ValueError, _torso.section_at, *bad)


def test_skirt_hangs_off_the_widest_body_and_flares_to_its_hem():
    body = _body()
    made = []
    for _ in range(2):
        b = _gbuilder.Builder(_GPALETTE)
        R = _torso.skirt(b, 'skirt', body, 1.0, 0.3, 'cloth', thick=0.01, flare=(0.04, 0.02), rows=3, tuck=0.005)
        made.append([[tuple(v.co) for v in ring] for ring in R])
    assert made[0] == made[1], 'deterministic'
    assert len(R) == 5 and all(len(ring) == _torso.SIDES for ring in R)
    assert [round(ring[0].co.z, 9) for ring in R] == [0.7, 0.8, 0.9, 1.0, 1.0], 'the hem first, the tuck ring last'
    # The hips (z 0.9) are the widest: every ring below them hangs from their extents.
    hips = (-0.18, 0.18, -0.13, 0.11)
    for ring, f in ((R[0], 1.0), (R[1], 2 / 3), (R[2], 1 / 3)):
        gx, gy = 0.01 + 0.04 * f, 0.01 + 0.02 * f
        assert _close(_extents(ring), (hips[0] - gx, hips[1] + gx, hips[2] - gy, hips[3] + gy)), _extents(ring)
    assert _close(_extents(R[3]), (-0.16, 0.16, -0.11, 0.09)), 'the top stands thick off the waist'
    assert _close(_extents(R[4]), (-0.145, 0.145, -0.095, 0.075)), 'the tuck ring sits inside the waist'
    top = R[3]
    assert abs(top[7].co.x) < 1e-12 and math.isclose(top[7].co.y, -0.11), 'vertex 7 the front centre, as the trunk'
    assert abs(top[2].co.x) < 1e-12 and math.isclose(top[2].co.y, 0.09), 'vertex 2 the back centre'
    assert min(top[9].co.x, top[0].co.x) > 0 > max(top[4].co.x, top[5].co.x), '9 and 0 the left side, 4 and 5 the right'
    assert len(b.bm.faces) == _torso.SIDES * 4 and all(f.calc_area() > 1e-6 for f in b.bm.faces)
    _raises(ValueError, _torso.skirt, _gbuilder.Builder(_GPALETTE), 'skirt', body, 1.25, 0.3, 'cloth')


def test_belt_hoops_the_body_and_reports_its_front():
    body = _body()
    b = _gbuilder.Builder(_GPALETTE)
    out = _torso.belt(b, 'belt', body, 0.95, 0.04, 0.01, 'belt', over=0.005, tuck=0.004)
    R = out['rings']
    assert len(R) == 4 and [round(r[0].co.z, 9) for r in R] == [0.93, 0.93, 0.97, 0.97]
    wide = (-0.171, 0.171, -0.121, 0.101)               # the cut at 0.93, the widest across the belt
    for ring in R[1:3]:
        assert _close(_extents(ring), (wide[0] - 0.015, wide[1] + 0.015, wide[2] - 0.015, wide[3] + 0.015))
    inner = _torso.section_at(body, 0.93)
    x0, x1, y0, y1 = _extents(R[0])
    assert math.isclose(x1, inner.half[0] - 0.004) and math.isclose(y0, inner.at[1] - inner.half_neg[1] + 0.004)
    assert _close(out['front'], (0.0, -0.136, 0.95))
    assert len(b.bm.faces) == 3 * _torso.SIDES
    _raises(ValueError, _torso.belt, b, 'belt', body, 0.81, 0.04, 0.01, 'belt')


def _sphere(centre, r, rings=8, cols=12):
    """A closed UV sphere as a BVHTree stand-in, a head the beard casts onto."""
    cx, cy, cz = centre
    verts = [(cx, cy, cz + r)]
    for i in range(1, rings):
        t = math.pi * i / rings
        verts += [(cx + r * math.sin(t) * math.cos(2 * math.pi * j / cols),
                   cy + r * math.sin(t) * math.sin(2 * math.pi * j / cols), cz + r * math.cos(t)) for j in range(cols)]
    verts.append((cx, cy, cz - r))
    at = lambda i, j: 1 + (i - 1) * cols + j % cols
    polys = [(0, at(1, j + 1), at(1, j)) for j in range(cols)]
    polys += [(at(i, j), at(i, j + 1), at(i + 1, j + 1), at(i + 1, j)) for i in range(1, rings - 1) for j in range(cols)]
    polys += [(len(verts) - 1, at(rings - 1, j), at(rings - 1, j + 1)) for j in range(cols)]
    return BVHTree.FromPolygons(verts, [p[::-1] for p in polys])          # wound outward


def test_long_beard_hangs_from_the_jaw_to_its_tip():
    centre, tip = (0.0, 0.0, 1.6), (0.0, -0.12, 1.3)
    head = _sphere(centre, 0.1)
    made = []
    for _ in range(2):
        b = _gbuilder.Builder(_GPALETTE)
        R = _hair.long_beard(b, 'beard', head, centre, -0.5, tip, 0.06, 0.02, 'hair', cols=5, symmetric=True)
        made.append([[tuple(v.co) for v in ring] for ring in R])
    assert made[0] == made[1], 'deterministic'
    assert len(R) == 4 and all(len(ring) == 10 for ring in R)
    assert len(b.bm.faces) == 2 * 5 * 3 + 2 * 2 * 5 and min(f.calc_area() for f in b.bm.faces) > _hair.BEARD_MIN_AREA
    for ring in R:
        pts = [tuple(v.co) for v in ring]
        mirrored = sorted((-x, y, z) for x, y, z in pts)
        assert all(_close(p, q) for p, q in zip(sorted(pts), mirrored)), 'an exact mirror image'
    for v in R[0][:5]:
        assert (v.co - _Vector(centre)).length > 0.1, 'the root row front stands off the head'
    apex = [v for v in b.bm.verts if _close(v.co, tip)]
    assert len(apex) == 1, 'closes on its tip'
    assert getattr(b, 'misses', None) is None
    b = _gbuilder.Builder(_GPALETTE)
    _hair.long_beard(b, 'beard', head, centre, lambda phi: -0.4 - 0.2 * abs(phi), tip, 0.06, 0.02, 'hair',
                     fork=0.03, tip_col='tip')
    tips = sorted(round(v.co.x, 9) for v in b.bm.verts if math.isclose(v.co.z, 1.3) and math.isclose(v.co.y, -0.12))
    assert tips == [-0.03, 0.03], 'a split beard ends in two locks'
    assert min(f.calc_area() for f in b.bm.faces) > 0


def test_long_beard_refuses_collapsing_faces():
    centre = (0.0, 0.0, 1.6)
    head = _sphere(centre, 0.1)
    b = _gbuilder.Builder(_GPALETTE)
    cases = (dict(tip=(0.0, -0.12, 1.3), stations=((0.5, 1.0), (0.5, 0.8))),
             dict(tip=(0.0, -0.12, 1.3), stations=((0.0, 1.0),)),
             dict(tip=(0.0, -0.12, 1.3), width=0.0),
             dict(tip=(0.05, -0.12, 1.3), symmetric=True))
    for case in cases:
        args = dict(dict(width=0.06, depth=0.02), **case)
        _raises(ValueError, _hair.long_beard, b, 'beard', head, centre, -0.5, args.pop('tip'), args.pop('width'),
                args.pop('depth'), 'hair', **args)
    msg = _raises(ValueError, _hair.long_beard, b, 'beard', head, centre, -0.5, (0.0, -0.12, 1.3), 1e-6, 1e-6,
                  'hair')
    assert 'collapses' in msg, msg
    assert not b.bm.faces, 'nothing is built before a refusal'


# -- hard-surface forms (lpk.forms.hard), on the stand-ins with the real Builder -------------------------------

with _blender_stand_ins():
    _hard = importlib.import_module('lpk.forms.hard')

_HPALETTE = {'shell': (0.3, 0.3, 0.3), 'edge': (0.5, 0.5, 0.5), 'cap': (0.1, 0.1, 0.1), 'face': (0.8, 0.2, 0.2)}


def _tris(b):
    return sum(len(f.verts) - 2 for f in b.bm.faces)


def _outward(b, centre):
    """Every face of a closed convex body built round `centre` looks away from it."""
    c = _Vector(centre)
    return all(f.normal.dot(f.calc_center_median() - c) > 0 for f in b.bm.faces)


def test_chamfer_section_runs_counter_clockwise_from_the_plus_x_side():
    assert _hard.chamfer_section(0.2, 0.1, 0.0) == [(0.2, -0.1), (0.2, 0.1), (-0.2, 0.1), (-0.2, -0.1)]
    cut = _hard.chamfer_section(0.2, 0.1, 0.02)
    assert len(cut) == len(_hard.SIDES) == 8
    assert _close(cut[0], (0.2, -0.08)) and _close(cut[2], (0.18, 0.1)) and _close(cut[7], (0.18, -0.1))
    area = sum(p[0] * q[1] - q[0] * p[1] for p, q in zip(cut, cut[1:] + cut[:1])) / 2
    assert area > 0, 'counter-clockwise seen from +z'
    _raises(ValueError, _hard.chamfer_section, 0.2, 0.1, 0.1)


def test_chamfer_box_counts_its_triangles_and_faces_outward():
    turned = ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0))
    for corner, edge, tris in ((0.0, 0.0, 12), (0.02, 0.0, 28), (0.0, 0.01, 28), (0.02, 0.01, 60)):
        for axes in (None, turned):
            b = _gbuilder.Builder(_HPALETTE)
            _hard.chamfer_box(b, 'box', (0.1, 0.2, 0.3), (0.1, 0.06, 0.2), axes, 'shell', corner=corner, edge=edge)
            assert _tris(b) == tris, (corner, edge, _tris(b))
            assert _outward(b, (0.1, 0.2, 0.3)), (corner, edge, axes)


def test_chamfer_box_colours_by_band_and_side():
    b = _gbuilder.Builder(_HPALETTE)
    paint = lambda band, side: 'face' if band == 1 and side == '+y' else ('edge' if side in _hard.CORNERS else 'shell')
    _hard.chamfer_box(b, 'box', (0, 0, 0), (0.1, 0.1, 0.2), None, paint, 'cap', 'cap', corner=0.02, edge=0.01)
    names = list(_HPALETTE)
    cols = [names[f[b.fpal]] for f in b.bm.faces]
    assert cols.count('face') == 1 and cols.count('cap') == 2 and cols.count('edge') == 12
    front = [f for f in b.bm.faces if names[f[b.fpal]] == 'face'][0]
    assert _close(front.normal, (0.0, 1.0, 0.0)), 'the +y side of the middle band'
    _raises(ValueError, _hard.chamfer_box, b, 'box', (0, 0, 0), (0.1, 0.1, 0.2), None, paint)


def test_chamfer_loft_steps_look_toward_the_open_side():
    b = _gbuilder.Builder(_HPALETTE)
    rings = _hard.chamfer_loft(b, 'shell', (0, 0, 0), None,
                               [(0.0, 0.1, 0.1, 0.02), (0.1, 0.1, 0.1, 0.02), (0.1, 0.15, 0.15, 0.03),
                                (0.3, 0.15, 0.15, 0.03, {'offset': (0.0, 0.01)})], 'shell', 'cap', 'cap')
    assert len(rings) == 4 and all(len(r) == 8 for r in rings)
    step = [f for f in b.bm.faces if all(abs(v.co.z - 0.1) < 1e-12 for v in f.verts) and len(f.verts) == 4]
    assert len(step) == 8 and all(f.normal.z < -0.999 for f in step), 'a step out looks back toward z = 0'
    caps = [f for f in b.bm.faces if len(f.verts) == 8]
    assert sorted(round(f.normal.z) for f in caps) == [-1, 1]
    assert _close(rings[3][0].co, (0.15, -0.11, 0.3)), 'the offset moves the last section up'
    _raises(ValueError, _hard.chamfer_loft, b, 's', (0, 0, 0), None, [(0.1, 0.1, 0.1, 0), (0.0, 0.1, 0.1, 0)],
            'shell', 'cap', 'cap')
    _raises(ValueError, _hard.chamfer_loft, b, 's', (0, 0, 0), None, [(0.0, 0.1, 0.1, 0), (0.1, 0.1, 0.1, 0.02)],
            'shell', 'cap', 'cap')


def test_standoff_plate_and_slot_lie_on_the_front():
    b = _gbuilder.Builder(_HPALETTE)
    front = _hard.standoff_plate(b, 'plate', [(-0.05, 0.1), (0.05, 0.1), (0.05, 0.2), (-0.05, 0.2)],
                                 (0.0, -0.1, 0.0), 0.01, 'face', 'shell')
    assert all(math.isclose(v.co.y, -0.11) for v in front), 'raised toward -Y'
    assert _tris(b) == 10
    face = [f for f in b.bm.faces if all(v in front for v in f.verts)][0]
    assert _close(face.normal, (0.0, -1.0, 0.0))
    b = _gbuilder.Builder(_HPALETTE)
    _hard.slot(b, 'slot', (0.0, 0.5), (1.0, 0.0), 0.1, 0.01, 'cap', (0.0, -0.2, 0.0))
    (f,) = b.bm.faces
    assert _close(f.normal, (0.0, -1.0, 0.0)) and math.isclose(f.calc_area(), 0.001)
    assert all(math.isclose(v.co.y, -0.2) and abs(v.co.z - 0.5) <= 0.005 + 1e-12 for v in f.verts)


def test_hinge_hub_and_mech_hand_hold_their_triangle_counts():
    b = _gbuilder.Builder(_HPALETTE)
    _hard.hinge(b, 'pin', (0, 0, 0), (0.1, 0, 0), 0.01, 'shell', n=6)
    assert _tris(b) == 4 * 6 - 4
    b = _gbuilder.Builder(_HPALETTE)
    _hard.hub(b, 'hub', (0, 0, 0), (0, -1, 0), 0.02, 0.01, 'shell', 'cap', n=8)
    assert _tris(b) == 4 * 8 - 4
    made = []
    for _ in range(2):
        b = _gbuilder.Builder(_HPALETTE)
        _hard.mech_hand(b, 'hand', (0.3, 0, 1.0), (1, 0, -0.2), (0, 0, 1), (0, -1, 0), 0.08, 0.07, 0.04,
                        'shell', 'edge', back_col='face', fingers=4)
        made.append([tuple(v.co) for v in b.bm.verts])
    assert _tris(b) == 28 + 18 * 5
    assert made[0] == made[1], 'deterministic'


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print('ok', name)
