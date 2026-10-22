"""Host tests of lpk.core.builder.Builder and of the forms whose geometry needs Builder.loft's own vertices
(no Blender needed: bpy, bmesh and mathutils are replaced by the stand-ins of blender_stand_ins while the
modules are imported, and the bmesh stand-in keeps vertices, faces and their int layers): moving and grounding a part, the
degenerate faces finish reports, loft_points as Builder.loft's vertices, the boots standing on the floor and work_boot_points
as the built boot's points, paw_toes as strap_paw's toes and its digits' spans, strap_paw's returned strap rings,
hair_locks' mirrored locks, and the winding of shapes.bridge between coplanar loops and loops apart.

python tests/test_builder.py"""
import importlib
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from blender_stand_ins import Vector as _Vector, stand_ins as _blender_stand_ins  # noqa: E402


with _blender_stand_ins():
    builder = importlib.import_module('lpk.core.builder')
    shapes = importlib.import_module('lpk.core.shapes')
    feet = importlib.import_module('lpk.forms.feet')
    hair = importlib.import_module('lpk.forms.hair')

PALETTE = {'skin': (0.8, 0.6, 0.5), 'dark': (0.1, 0.1, 0.1), 'sole': (0.3, 0.3, 0.3),
           'tread': (0.2, 0.2, 0.2), 'band': (0.5, 0.1, 0.1), 'cap': (0.9, 0.9, 0.9), 'hair': (0.4, 0.2, 0.1),
           'tip': (0.9, 0.8, 0.3)}


def _raises(exc, fn, *args, **kw):
    try:
        fn(*args, **kw)
    except exc as e:
        return str(e)
    raise AssertionError('%s not raised' % exc.__name__)


def _verts(b, part):
    pid = b.parts.index(part)
    return [v for v in b.bm.verts if v[b.vpart] == pid]


def _low(b, part):
    return min(v.co.z for v in _verts(b, part))


def _box(b, part, centre, half):
    """An axis-aligned box of 8 vertices and 6 faces, without Builder.box's Matrix."""
    pid = b.pid(part)
    (cx, cy, cz), (hx, hy, hz) = centre, half
    vs = {(i, j, k): b.vert((cx + i * hx, cy + j * hy, cz + k * hz), pid)
          for i in (-1, 1) for j in (-1, 1) for k in (-1, 1)}
    for q in (((-1, -1, -1), (-1, 1, -1), (-1, 1, 1), (-1, -1, 1)), ((1, -1, -1), (1, -1, 1), (1, 1, 1), (1, 1, -1)),
              ((-1, -1, -1), (-1, -1, 1), (1, -1, 1), (1, -1, -1)), ((-1, 1, -1), (1, 1, -1), (1, 1, 1), (-1, 1, 1)),
              ((-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1)), ((-1, -1, 1), (-1, 1, 1), (1, 1, 1), (1, -1, 1))):
        b.face([vs[k] for k in q], 'skin')


def test_move_part_moves_only_that_parts_vertices():
    b = builder.Builder(PALETTE)
    _box(b, 'foot.L', (0.1, 0.0, 0.05), (0.03, 0.08, 0.05))
    _box(b, 'leg.L', (0.1, 0.0, 0.4), (0.04, 0.04, 0.3))
    before = {p: [list(v.co) for v in _verts(b, p)] for p in ('foot.L', 'leg.L')}
    assert b.move_part('foot.L', (0.01, -0.074, 0.002)) is None
    moved = [list(v.co) for v in _verts(b, 'foot.L')]
    assert all(math.isclose(m[k], o[k] + d, abs_tol=1e-12) for m, o in zip(moved, before['foot.L'])
               for k, d in enumerate((0.01, -0.074, 0.002))), 'every vertex of the part moves by the offset'
    assert [list(v.co) for v in _verts(b, 'leg.L')] == before['leg.L'], 'other parts stay'
    assert b.parts == ['', 'foot.L', 'leg.L'], 'part index 0 is reserved'
    assert "'feet.L'" in _raises(ValueError, b.move_part, 'feet.L', (0, 0, 1)), 'a misspelt part raises'
    assert b.parts == ['', 'foot.L', 'leg.L'], 'a misspelt part is not registered'


def test_ground_part_sets_the_lowest_vertex_on_z_and_returns_the_shift():
    b = builder.Builder(PALETTE)
    _box(b, 'foot.L', (0.1, 0.0, 0.0), (0.03, 0.08, 0.02))          # 2 cm under the floor
    _box(b, 'leg.L', (0.1, 0.0, 0.4), (0.04, 0.04, 0.3))
    leg = [list(v.co) for v in _verts(b, 'leg.L')]
    dz = b.ground_part('foot.L')
    assert math.isclose(dz, 0.02, abs_tol=1e-12) and _low(b, 'foot.L') == 0.0, (dz, _low(b, 'foot.L'))
    assert [list(v.co) for v in _verts(b, 'leg.L')] == leg, 'other parts stay'
    assert b.ground_part('foot.L') == 0.0, 'a grounded part stays where it is'
    dz = b.ground_part('foot.L', z=0.05)
    assert math.isclose(dz, 0.05, abs_tol=1e-12) and math.isclose(_low(b, 'foot.L'), 0.05, abs_tol=1e-12)
    b.scale_part('foot.L', (0.1, 0.0, 0.1), 1.3)                    # a later change of the shape
    assert math.isclose(b.ground_part('foot.L'), (0.1 - 0.05) * 1.3 - 0.1, abs_tol=1e-12)
    assert _low(b, 'foot.L') == 0.0, 'grounding follows the shape it reads'
    assert 'ground_part' in _raises(ValueError, b.ground_part, 'tail')


def test_the_boots_stand_on_the_floor():
    boots = {'work_boot': lambda b: feet.work_boot(b, 'boot.L', 0.1, 0.32, 'dark', 'sole', 'tread', band_col='band'),
             'platform_boot': lambda b: feet.platform_boot(b, 'boot.L', 0.1, 1, 0.12, 'dark', 'sole')}
    for name, build in boots.items():
        laid, grounded = builder.Builder(PALETTE), builder.Builder(PALETTE)
        ground, feet._ground_new = feet._ground_new, lambda b, part, old: 0.0
        try:
            laid_out = build(laid)
        finally:
            feet._ground_new = ground
        out = build(grounded)
        low = _low(laid, 'boot.L')
        assert low > 0.0 and _low(grounded, 'boot.L') == 0.0, (name, low)
        assert all(math.isclose(g.co.z, l.co.z - low, abs_tol=1e-12) and (g.co.x, g.co.y) == (l.co.x, l.co.y)
                   for g, l in zip(_verts(grounded, 'boot.L'), _verts(laid, 'boot.L'))), \
            '%s: the boot as laid out, moved straight down onto the floor' % name
        if out is not None:
            assert laid_out[0].z == laid_out[1].z == 0.035, 'the points on the top of the sole as laid out'
            assert all(math.isclose(p.z, q.z - low, abs_tol=1e-12) for p, q in zip(out, laid_out)), \
                'the returned points move with the boot'
    b = builder.Builder(PALETTE)
    _box(b, 'boot.L', (0.1, 0.0, 0.5), (0.02, 0.02, 0.02))           # held by the part before the boot
    held = [list(v.co) for v in _verts(b, 'boot.L')]
    feet.work_boot(b, 'boot.L', 0.1, 0.32, 'dark', 'sole', 'tread')
    assert [list(v.co) for v in _verts(b, 'boot.L')][:8] == held, 'what the part held before stays'
    assert _low(b, 'boot.L') == 0.0


def _lofts(form, *args, **kw):
    """The Builder.loft calls `form` makes, as (args, keywords), and the builder it built into."""
    b = builder.Builder(PALETTE)
    calls, loft = [], b.loft
    b.loft = lambda *a, **k: calls.append((a, k)) or loft(*a, **k)
    form(b, *args, **kw)
    return calls, b


def test_work_boot_takes_its_toe_cap_colour_cuff_and_band_height():
    args = ('boot.L', 0.1, 0.32, 'dark', 'sole', 'tread')
    (_, (shaft, _), (_, upper)), b = _lofts(feet.work_boot, *args, band_col='band')
    rings = shaft[1]
    assert rings[0][1:] == (0.062 * 1.04,) * 2 and rings[1][0][2] == 0.32 - 0.04, \
        'by default the cuff flares to 1.04 of the shaft and the band is 4 cm tall'
    assert upper['col1'] == 'sole', 'by default the toe cap takes the sole colour'
    assert not [f for f in b.bm.faces if f[b.fpal] == b.keys.index('cap')]
    (_, (shaft, _), (_, upper)), b = _lofts(feet.work_boot, *args, band_col='band', cap_col='cap', cuff=1.2,
                                            band_h=0.06)
    rings = shaft[1]
    assert rings[0][1:] == (0.062 * 1.2,) * 2 and rings[1][0][2] == 0.32 - 0.06 and rings[1][1:] == (0.062, 0.062)
    assert upper['col1'] == 'cap'
    assert len([f for f in b.bm.faces if f[b.fpal] == b.keys.index('cap')]) == 1, 'one flat toe cap'


def test_strap_paw_builds_its_toes_through_paw_toes():
    for sx, width, length, toes, sides in ((1, 0.066, 0.25, 4, 3), (-1, 0.058, 0.31, 5, 4), (1, 0.071, 0.22, 3, 3)):
        calls, _ = _lofts(feet.strap_paw, 'foot.L', 0.113, sx, 0.41, 'skin', 'dark', length=length, width=width,
                          toes=toes, digit_sides=sides)
        x, ball, toe, m = 0.113, -0.03 - length * 0.42, length * 0.30, (toes - 1) / 2
        want = []                                                    # the toe lofts strap_paw's numbers give
        for k in range(toes):
            tx = x + sx * 0.004 + (k - m) * (width * 1.6 / toes)
            want.append((('foot.L', [((tx, ball, 0.020), 0.015, 0.015), ((tx, ball - toe, 0.013), 0.012, 0.010)],
                            sides, feet.X, 'skin'), {'cap1': (tx, ball - toe - 0.035, 0.0), 'col1': 'dark'}))
        assert len(calls) == 1 + toes and calls[1:] == want and repr(calls[1:]) == repr(want), \
            'strap_paw passes paw_toes these loft arguments, float for float'


def test_strap_paw_returns_its_strap_rings_where_the_paw_was_built():
    b = builder.Builder(PALETTE)
    rings = feet.strap_paw(b, 'foot.L', 0.1, 1, 0.3, 'skin', 'dark')
    built = [[list(p) for p in r] for r in rings]
    off = (0.0, -0.074, 0.0)
    b.move_part('foot.L', off)
    dz = b.ground_part('foot.L')
    assert dz > 0.0 and [[list(p) for p in r] for r in rings] == built, 'the points stay where they were built'
    paw = _verts(b, 'foot.L')[:3 * 6]                                # the loft's first three rings
    shifted = [p + _Vector(off) + _Vector((0.0, 0.0, dz)) for r in rings for p in r]
    assert all(math.dist(p, v.co) < 1e-12 for p, v in zip(shifted, paw)), \
        "shifted by the move and the grounding, they lie on the paw's rings"


def test_paw_toes_digits_span_their_apothems_by_side_count():
    for sides, left, right, low in ((3, 2.0, 1.0, 2 * math.sin(math.pi / 3)), (4, 1.0, 1.0, 1.0),
                                    (5, 1 / math.cos(math.pi / 5), 1.0, None)):
        b = builder.Builder(PALETTE)
        w, h = 0.01, 0.008
        (R,) = feet.paw_toes(b, 'toes.L', (0.0, 0.0, 0.1), (0.0, -0.05, 0.1), ((w, h), (w, h)), 0.05, 0.02,
                             'skin', 'dark', toes=1, digit_sides=sides)
        xs, zs = [v.co.x for v in R[0]], [v.co.z for v in R[0]]
        assert math.isclose(min(xs), -left * w, abs_tol=1e-9) and math.isclose(max(xs), right * w, abs_tol=1e-9), \
            (sides, min(xs) / w, max(xs) / w)
        if low is not None:
            assert math.isclose(0.1 - min(zs), low * h, abs_tol=1e-9), (sides, (0.1 - min(zs)) / h)


def test_paw_toes_lays_its_digits_across_x_with_claws_at_their_height():
    b = builder.Builder(PALETTE)
    ball, tip, spacing = (0.1, -0.05, 0.03), (0.1, -0.11, 0.012), 0.022
    rings = feet.paw_toes(b, 'toes.L', ball, tip, ((0.009, 0.008), (0.007, 0.005)), spacing, 0.02, 'skin', 'dark',
                          toes=4, digit_sides=4, claw_z=0.001)
    assert len(rings) == 4 and all(len(R) == 2 and all(len(r) == 4 for r in R) for R in rings)
    centres = [sum(v.co.x for v in R[0]) / 4 for R in rings]
    assert all(math.isclose(c, 0.1 + (k - 1.5) * spacing, abs_tol=1e-12) for k, c in enumerate(centres)), \
        'the digits from -X to +X, spacing apart, centred on the ball'
    apexes = [v for v in _verts(b, 'toes.L') if not any(v in r for R in rings for r in R)]
    assert len(apexes) == 4 and all(math.isclose(v.co.y, -0.13, abs_tol=1e-12) and v.co.z == 0.001 for v in apexes)
    claws = [f for f in b.bm.faces if f[b.fpal] == b.keys.index('dark')]
    assert len(claws) == 4 * 4 and len(b.bm.faces) == 4 * (4 + 4), \
        'a side band and a claw cone per digit, the root open'


def test_mitt_paw_is_left_where_its_floor_points_put_it():
    b = builder.Builder(PALETTE)
    with _blender_stand_ins():                                       # mitt_paw imports fur.tuft when called
        feet.mitt_paw(b, 'foot.L', (0.1, 0.05, 0.0), (0.1, -0.12, 0.0), 0.05, 0.09, 'skin', 'dark')
    body = _verts(b, 'foot.L')[:4 * 8 + 2]
    assert min(v.co.z for v in body) > 0.0 > _low(b, 'foot.L'), 'the mitt floats and its claws dip, unmoved'


class _TiltedScalp:
    """A BVH over the plane z = 1 + 0.004 x, tilted across the midline the way a head whose faces
    triangulate differently on its two sides is; rays that start over |x| > miss_x miss."""

    def __init__(self, miss_x=1.0):
        self.miss_x = miss_x

    def ray_cast(self, origin, direction):
        o = _Vector(origin)
        if abs(o.x) > self.miss_x:
            return None, None, None, None
        return _Vector((o.x, o.y, 1.0 + 0.004 * o.x)), _Vector((0.0, 0.0, 1.0)), 0, o.z - 1.0


LOCKS = [(0.0, 0.01, (0.0, 0.01, 0.05), 0.01, False), (0.03, 0.0, (0.012, 0.005, 0.04), 0.008, True),
         (0.05, -0.02, (0.02, -0.01, 0.03), 0.007, False)]


def _twins(b, part):
    """For each vertex of `part`, the distance from its mirror image to the nearest vertex of the part."""
    vs = [tuple(v.co) for v in _verts(b, part)]
    return [min(math.dist((-x, y, z), w) for w in vs) for x, y, z in vs]


def test_hair_locks_mirror_builds_the_minus_x_side_as_an_exact_mirror_image():
    b = builder.Builder(PALETTE)
    hair.hair_locks(b, 'crest', _TiltedScalp(), LOCKS + [(-x, y, (-o[0], o[1], o[2]), w, lit)
                                                        for x, y, o, w, lit in LOCKS[1:]], 'hair', tip_col='tip')
    assert max(_twins(b, 'crest')) > 1e-4, 'cast at each side, the twins land at different heights'
    b = builder.Builder(PALETTE)
    hair.hair_locks(b, 'crest', _TiltedScalp(), LOCKS, 'hair', tip_col='tip', mirror=True)
    assert len(_verts(b, 'crest')) == 5 * (2 * 4 + 1), 'the midline lock once, the side locks twice'
    assert max(_twins(b, 'crest')) < 1e-12, 'every vertex has its mirror twin'
    copied = [v for v in _verts(b, 'crest')[9:] if v.co.x < 0.0]               # past the midline lock
    originals = {(-v.co.x, v.co.y, v.co.z) for v in copied}
    assert len(copied) == 2 * 9 and all(any(tuple(w.co) == o for w in _verts(b, 'crest')) for o in originals), \
        'the -X locks are the +X locks with x negated, float for float'
    tips = [f for f in b.bm.faces if f[b.fpal] == b.keys.index('tip')]
    assert len(tips) == 2 * 4 and sum(1 for f in tips if all(v.co.x < 0 for v in f.verts)) == 4, \
        'the lit lock and its twin carry the tip colour'
    faces = [f for f in b.bm.faces if all(any(v is c for c in copied) for v in f.verts)]
    assert len(faces) == 2 * (4 + 4), 'a side band and a cone per copied lock'
    for f in faces:
        (src,) = [g for g in b.bm.faces if [tuple(v.co) for v in g.verts] ==
                  [(-v.co.x, v.co.y, v.co.z) for v in reversed(f.verts)]]
        assert src[b.fpal] == f[b.fpal], 'a copied face keeps its colour and runs the other way round'
    assert not b.__dict__.get('misses')
    b = builder.Builder(PALETTE)
    hair.hair_locks(b, 'crest', _TiltedScalp(miss_x=0.04), LOCKS, 'hair', mirror=True)
    missed = {'hair_locks': {'crest': {'count': 1, 'point': [0.05, -0.02, 10.0]}}}
    assert len(_verts(b, 'crest')) == 3 * 9 and b.misses == missed, 'a missed lock skips its twin'
    listed, b = b, builder.Builder(PALETTE)
    hair.hair_locks(b, 'crest', _TiltedScalp(miss_x=0.04), (lock for lock in LOCKS), 'hair', mirror=True)
    assert [list(v.co) for v in _verts(b, 'crest')] == [list(v.co) for v in _verts(listed, 'crest')] and \
        b.misses == missed, 'locks given as a generator build the same locks'


def test_hair_locks_mirror_refuses_locks_it_cannot_mirror():
    b = builder.Builder(PALETTE)
    assert '[1]' in _raises(ValueError, hair.hair_locks, b, 'crest', _TiltedScalp(),
                            [LOCKS[0], (-0.03, 0.0, (0.0, 0.0, 0.04), 0.008, False)], 'hair', mirror=True)
    assert '[0]' in _raises(ValueError, hair.hair_locks, b, 'crest', _TiltedScalp(),
                            [(0.0, 0.01, (0.01, 0.0, 0.05), 0.01, False)], 'hair', mirror=True)
    assert 'n = 3' in _raises(ValueError, hair.hair_locks, b, 'crest', _TiltedScalp(), LOCKS, 'hair', n=3,
                              mirror=True)
    assert not b.bm.verts, 'nothing is built before the raise'
    hair.hair_locks(b, 'crest', _TiltedScalp(), LOCKS[1:], 'hair', n=3, mirror=True)
    assert max(_twins(b, 'crest')) < 1e-12, 'an odd n mirrors exactly off the midline'


def _ring(b, part, z, r, n=8, turn=0.0):
    pid = b.pid(part)
    return [b.vert((r * math.cos(turn + 2 * math.pi * j / n), r * math.sin(turn + 2 * math.pi * j / n), z), pid)
            for j in range(n)]


def _tube(b, low, high):
    """The faces of a tube between two rings of one size, wound away from its axis."""
    n = len(low)
    for j in range(n):
        q = [low[j], low[(j + 1) % n], high[(j + 1) % n], high[j]]
        mid = sum((v.co for v in q), _Vector()) / 4
        b.face(q, 'skin', hint=(0.0, 0.0, mid.z))


def _bridged(b, before):
    return [f for f in b.bm.faces if f.is_valid and f not in before]


def test_a_bridge_between_coplanar_loops_faces_the_side_of_the_surface_it_continues():
    for below, side in ((True, 1.0), (False, -1.0)):
        b = builder.Builder(PALETTE)
        rim, inner = _ring(b, 'trunk', 1.0, 1.0), _ring(b, 'neck', 1.0, 0.5)
        _tube(b, *((_ring(b, 'trunk', 0.0, 1.0), rim) if below else (rim, _ring(b, 'trunk', 2.0, 1.0))))
        for loop in (rim, rim[::-1]):
            before = set(b.bm.faces)
            shapes.bridge(b, loop, inner, 'skin')
            made = _bridged(b, before)
            assert len(made) == 16 and all(abs(f.normal.z - side) < 1e-9 for f in made),                 'a flat ledge on top of a tube faces up, one under it down, whatever the loop order'
            for f in made:
                f.is_valid = False
                b.bm.faces.remove(f)
                for v in f.verts:
                    v.link_faces.remove(f)
    b = builder.Builder(PALETTE)
    rim, inner = _ring(b, 'trunk', 1.0, 1.0), _ring(b, 'neck', 1.0, 0.5)
    _tube(b, _ring(b, 'neck', 2.0, 0.5), inner)                       # only the ring has faces: a tube rising
    before = set(b.bm.faces)
    shapes.bridge(b, rim, inner, 'skin')
    assert all(f.normal.z > 0.999 for f in _bridged(b, before)), 'the ring decides when the loop has no face'
    for loop, z in ((None, 1.0), ('reversed', -1.0)):
        b = builder.Builder(PALETTE)
        rim, inner = _ring(b, 'trunk', 1.0, 1.0), _ring(b, 'neck', 1.0, 0.5)
        before = set(b.bm.faces)
        shapes.bridge(b, rim if loop is None else rim[::-1], inner, 'skin')
        made = _bridged(b, before)
        assert all(abs(f.normal.z - z) < 1e-9 for f in made), "with no face on either, the loop's own normal"
        assert all(len(f.verts) == 3 for f in made) and len(made) == 16


def test_a_bridge_between_loops_apart_keeps_facing_away_from_their_centre():
    b = builder.Builder(PALETTE)
    rim, ring = _ring(b, 'trunk', 1.0, 1.0), _ring(b, 'neck', 1.2, 0.5)
    assert shapes._flat_side(rim, ring) is None
    before = set(b.bm.faces)
    shapes.bridge(b, rim, ring, 'skin')
    hint = _Vector((0.0, 0.0, 1.1))
    made = _bridged(b, before)
    assert len(made) == 16 and all(f.normal.dot(f.calc_center_median() - hint) > 0 for f in made)
    lifted = _ring(b, 'neck', 1.0 + 2 * shapes.COPLANAR_M, 0.5)
    assert shapes._flat_side(rim, lifted) is None, 'past COPLANAR_M the loops are apart'
    assert shapes._flat_side(rim, _ring(b, 'neck', 1.0 + shapes.COPLANAR_M / 2, 0.5)) is not None


def test_degenerate_faces_counts_the_faces_under_the_area_floor_per_part():
    b = builder.Builder(PALETTE)
    _box(b, 'trunk', (0.0, 0.0, 1.0), (0.1, 0.1, 0.1))
    assert builder.degenerate_faces(b) == {}
    pid = b.pid('arm.L')
    flat = [b.vert(p, pid) for p in ((0.0, 0.0, 0.0), (0.1, 0.0, 0.0), (0.2, 0.0, 0.0))]
    b.face(flat, 'skin')
    side = 1e-6                                     # a 1 um sliver: 5e-13 m^2
    b.face([b.vert(p, pid) for p in ((0.0, 0.0, 0.5), (side, 0.0, 0.5), (0.0, side, 0.5))], 'skin')
    b.face([b.vert(p, pid) for p in ((0.0, 0.0, 0.7), (0.01, 0.0, 0.7), (0.0, 0.01, 0.7))], 'skin')
    assert builder.degenerate_faces(b) == {'arm.L': 2}


def test_loft_points_are_the_vertices_builder_loft_lays():
    rings = [((0.0, 0.0, 1.0), 0.1, 0.08, {'p': 3}), ((0.0, 0.0, 0.5), 0.07, 0.07), ((0.02, 0.0, 0.1), 0.05, 0.04)]
    b = builder.Builder(PALETTE)
    R = b.loft('leg.L', rings, 6, (1.0, 0.0, 0.0), 'skin')
    frames, points = builder.loft_points(rings, 6, (1.0, 0.0, 0.0))
    assert len(frames) == 3 and [[tuple(v.co) for v in r] for r in R] == [[tuple(p) for p in r] for r in points]


def test_work_boot_points_are_the_built_boots_points_without_building():
    for kw in ({}, {'length': 0.3, 'width': 0.05, 'sole_h': 0.05, 'heel_y': 0.08, 'shaft_r': 0.05, 'cuff': 1.2,
                    'band_h': 0.03}):
        b = builder.Builder(PALETTE)
        ball, toe = feet.work_boot(b, 'boot.L', 0.1, 0.32, 'dark', 'sole', 'tread', band_col='band', **kw)
        k = feet.work_boot_points(0.1, 0.32, **kw)
        assert sorted(k) == ['ankle', 'ball', 'ground', 'heel', 'toe', 'top']
        assert all(math.isclose(p, q, abs_tol=1e-12) for p, q in zip(k['ball'] + k['toe'], tuple(ball) + tuple(toe)))
        verts = _verts(b, 'boot.L')
        assert any(all(math.isclose(p, q, abs_tol=1e-12) for p, q in zip(k['heel'], v.co)) for v in verts), \
            'the heel apex is a vertex of the built boot'
        assert k['ground'] < 0.0 and k['top'][2] == 0.32 + k['ground'] and k['ankle'][1] == 0.012
        assert min(p[2] for p in (k['ankle'], k['ball'], k['heel'])) > 0.0 == _low(b, 'boot.L')


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print('ok', name)
