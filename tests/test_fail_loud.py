"""Host tests of the fail-loud guards and the probe-miss counting in lpk.forms and lpk.core (no Blender
needed: bpy, bmesh and mathutils are replaced by stand-ins while the modules are imported, and the tests
reach only the code before any mesh is built). The guards raise on misuse that would otherwise go
silently wrong; the probes count their misses on the builder (lpk.core.shapes.miss).

python tests/test_fail_loud.py"""
import contextlib
import importlib
import json
import math
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _Vector:
    """The part of mathutils.Vector the code under test touches before it builds geometry."""

    def __init__(self, seq=(0.0, 0.0, 0.0)):
        self.v = [float(c) for c in seq]

    x = property(lambda s: s.v[0], lambda s, a: s.v.__setitem__(0, a))
    y = property(lambda s: s.v[1], lambda s, a: s.v.__setitem__(1, a))
    z = property(lambda s: s.v[2], lambda s, a: s.v.__setitem__(2, a))

    def __iter__(self):
        return iter(self.v)

    def __len__(self):
        return len(self.v)

    def __getitem__(self, i):
        return self.v[i]

    def __add__(self, o):
        return _Vector(a + b for a, b in zip(self, o))

    def __sub__(self, o):
        return _Vector(a - b for a, b in zip(self, o))

    def __mul__(self, k):
        return _Vector(a * k for a in self)

    __rmul__ = __mul__

    def __truediv__(self, k):
        return _Vector(a / k for a in self)

    def __neg__(self):
        return self * -1.0

    def dot(self, o):
        return sum(a * b for a, b in zip(self, o))

    @property
    def length(self):
        return math.sqrt(self.dot(self))

    def normalized(self):
        n = self.length
        return _Vector(a / n for a in self) if n else _Vector(self)

    def copy(self):
        return _Vector(self)


class _IntLayers(dict):
    def new(self, name):
        self[name] = name
        return name


class _Elements(list):
    def __init__(self):
        super().__init__()
        self.layers = types.SimpleNamespace(int=_IntLayers())

    def ensure_lookup_table(self):
        pass


class _BMesh:
    """bmesh.new(): empty vertex and face sequences with int layers keyed by their names."""

    def __init__(self):
        self.verts, self.faces = _Elements(), _Elements()


@contextlib.contextmanager
def _blender_stand_ins():
    """bpy, bmesh and mathutils stand-ins for the module-level imports of lpk.core and lpk.forms, and lpk as
    a bare package over its folder; sys.modules is restored afterwards."""
    stand_ins = ('bpy', 'bmesh', 'mathutils', 'mathutils.bvhtree', 'mathutils.geometry')
    ours = lambda name: name in stand_ins or name == 'lpk' or name.startswith('lpk.')
    saved = {k: v for k, v in sys.modules.items() if ours(k)}
    for k in saved:
        del sys.modules[k]
    mathutils = types.ModuleType('mathutils')
    mathutils.Vector, mathutils.Matrix = _Vector, type('Matrix', (), {})
    bvhtree = types.ModuleType('mathutils.bvhtree')
    bvhtree.BVHTree = type('BVHTree', (), {})
    mathutils.bvhtree = bvhtree
    bmesh = types.ModuleType('bmesh')
    bmesh.new = _BMesh
    lpk = types.ModuleType('lpk')
    lpk.__path__ = [os.path.join(ROOT, 'lpk')]
    sys.modules.update({'bpy': types.ModuleType('bpy'), 'bmesh': bmesh, 'mathutils': mathutils,
                        'mathutils.bvhtree': bvhtree, 'lpk': lpk})
    try:
        yield
    finally:
        for k in [k for k in sys.modules if ours(k)]:
            del sys.modules[k]
        sys.modules.update(saved)


with _blender_stand_ins():
    builder = importlib.import_module('lpk.core.builder')
    shapes = importlib.import_module('lpk.core.shapes')
    joins = importlib.import_module('lpk.forms.joins')
    torso = importlib.import_module('lpk.forms.torso')
    eyes = importlib.import_module('lpk.forms.eyes')
    head = importlib.import_module('lpk.forms.head')
    hair = importlib.import_module('lpk.forms.hair')

PALETTE = {'skin': (0.8, 0.6, 0.5), 'dark': (0.1, 0.1, 0.1)}


class _MissBVH:
    """A BVH every probe misses."""

    def ray_cast(self, *args):
        return None, None, None, None


def _raises(exc, fn, *args, **kw):
    try:
        fn(*args, **kw)
    except exc as e:
        return str(e)
    raise AssertionError('%s not raised' % exc.__name__)


def test_hole_loops_without_the_join_loop_layer_raise_with_the_declaration():
    b = builder.Builder(PALETTE)
    for form, args in ((joins.armholes, (b, [], [], {'L': (0, 1)})), (joins.leg_holes, (b, [], 'torso', 0.9))):
        msg = _raises(ValueError, form, *args)
        assert "vert_layers=('join_loop',)" in msg and "the body's builder" in msg, msg


def test_hole_loops_are_tagged_with_the_layer():
    b = builder.Builder(PALETTE, vert_layers=(joins.LAYER,))
    verts = [{}, {}]
    joins._tag(b, verts)
    assert verts == [{joins.LAYER: 1}, {joins.LAYER: 1}]


def test_weld_sides_come_from_the_hole_or_must_match_it():
    hole = list(range(8))
    assert joins._hole_size(None, hole, 'weld_leg') == 8
    assert joins._hole_size(8, hole, 'weld_leg') == 8
    msg = _raises(ValueError, joins._hole_size, 6, hole, 'weld_leg')
    assert 'weld_leg' in msg and 'n=6' in msg and 'hole size 8' in msg, msg


def test_weld_forms_check_n_before_building():
    b = builder.Builder(PALETTE)
    hole = list(range(8))
    msg = _raises(ValueError, joins.weld_limb, b, 'arm.L', hole, None, None, None, None, 10, None, 'skin', 'skin',
                  None, None)
    assert 'weld_limb' in msg, msg
    msg = _raises(ValueError, joins.weld_leg, b, 'leg.L', hole, None, None, 6, None, 'skin', 'skin')
    assert 'weld_leg' in msg, msg


def _ring(z, mult=None):
    return ((0.0, 0.0, z), 0.1, 0.08) + (() if mult is None else (mult,))


def test_trunk_rejects_multipliers_on_a_box_ring():
    rings = [_ring(0.9, [1.0] * 9 + [1.2]), _ring(1.0), _ring(1.1), _ring(1.2)]
    msg = _raises(ValueError, torso.trunk, None, 'torso', rings, 'skin')
    assert 'ring 0' in msg and 'boxes' in msg, msg
    rings = [_ring(0.9), _ring(1.0, [1.0, 0.9] * 5), _ring(1.1), _ring(1.2)]
    assert 'ring 1' in _raises(ValueError, torso.trunk, None, 'torso', rings, 'skin')


def test_trunk_accepts_unit_or_no_multipliers_on_box_rings():
    calls = []
    old = torso.polygon_rings, torso.point_loft
    torso.polygon_rings = lambda rings, n, drop: [[None] * n for _ in rings]
    torso.point_loft = lambda b, part, pts, color: calls.append(pts) or pts
    try:
        rings = [_ring(0.9, [1.0] * 10), _ring(1.0), _ring(1.1, [1.0, 1.1] * 5), _ring(1.2, None)]
        torso.trunk(None, 'torso', rings, 'skin', round_rings=len(rings))
        torso.trunk(None, 'torso', [_ring(0.9, [1.3] * 10), _ring(1.0)], 'skin', round_rings=2, boxes=())
    finally:
        torso.polygon_rings, torso.point_loft = old
    assert len(calls) == 2
    assert all(p is not None for p in calls[0][0]) and calls[0][2] == [None] * torso.SIDES


def test_mirror_part_raises_only_on_a_repeated_pair():
    b = builder.Builder(PALETTE)
    assert b.mirror_part('hand.L', 'hand.R') == {}
    b.mirror_part('glove.L', 'hand.R')
    b.mirror_part('hand.R', 'hand.L')
    msg = _raises(ValueError, b.mirror_part, 'hand.L', 'hand.R')
    assert "'hand.L', 'hand.R'" in msg and 'a part of its own' in msg, msg
    assert b.mirrored == [('hand.L', 'hand.R'), ('glove.L', 'hand.R'), ('hand.R', 'hand.L')]
    assert b.parts == ['', 'hand.L', 'hand.R', 'glove.L']


class _Vert(dict):
    """A builder vertex: its coordinates and its int layers by name."""

    def __init__(self, co, pid):
        super().__init__(part=pid)
        self.co = _Vector(co)


def test_snap_ring_counts_misses_only_with_a_builder():
    b = builder.Builder(PALETTE)
    ring = [_Vert((x, 0.0, 1.0), b.pid('collar')) for x in (0.0, 0.1, 0.2)]
    shapes.snap_ring(ring, (0, 1, 0), _MissBVH())
    assert 'misses' not in vars(b)
    shapes.snap_ring(ring, (0, 1, 0), _MissBVH(), b=b)
    assert b.misses == {'snap_ring': {'collar': {'count': 3, 'point': [0.0, 0.0, 1.0]}}}, b.misses
    assert [list(v.co) for v in ring] == [[0.0, 0.0, 1.0], [0.1, 0.0, 1.0], [0.2, 0.0, 1.0]]


class _WallBVH:
    """A BVH holding the plane x = 0: rays record their arguments and hit it."""

    def __init__(self):
        self.calls = []

    def ray_cast(self, origin, direction, *distance):
        self.calls.append((list(origin), list(direction)) + distance)
        if direction.x == 0 or origin.x / -direction.x < 0:
            return None, None, None, None
        return origin + direction * (origin.x / -direction.x), _Vector((1, 0, 0)), 0, 0.0


def test_cast_point_sinks_the_hit_along_the_ray_and_counts_a_miss():
    b = builder.Builder(PALETTE)
    wall = _WallBVH()
    p = shapes.cast_point(b, wall, _Vector((0.3, 0.1, 1.6)), (-2, 0, 0), sink=0.008, distance=1.0)
    assert all(math.isclose(a, e, abs_tol=1e-12) for a, e in zip(p, (-0.008, 0.1, 1.6))), list(p)
    assert wall.calls == [([0.3, 0.1, 1.6], [-1.0, 0.0, 0.0], 1.0)], 'the direction is normalised, the reach kept'
    assert list(shapes.cast_point(b, wall, (0.3, 0.0, 1.0), (-1, 0, 0))) == [0.0, 0.0, 1.0]
    assert len(wall.calls[1]) == 2, 'no distance: the ray has no limit'
    assert 'misses' not in vars(b)
    assert shapes.cast_point(b, wall, (0.3, 0.0, 1.0), (1, 0, 0), sink=0.01) is None
    assert shapes.cast_point(b, _MissBVH(), (0.3, 0.0, 1.0), (-1, 0, 0)) is None
    assert b.misses == {'cast_point': {'<unknown>': {'count': 2, 'point': [0.3, 0.0, 1.0]}}}
    assert json.loads(json.dumps(b.misses)) == b.misses
    assert shapes.cast_point(b, _MissBVH(), (0.12345, -0.2, 1.7), (-1, 0, 0), part='ear.L') is None
    assert b.misses['cast_point']['ear.L'] == {'count': 1, 'point': [0.1235, -0.2, 1.7]}
    assert shapes.cast_point(b, _MissBVH(), (0.9, 0.2, 2.0), (-1, 0, 0), part='ear.L') is None
    assert b.misses['cast_point']['ear.L'] == {'count': 2, 'point': [0.1235, -0.2, 1.7]}


def test_socket_eyes_count_the_eyes_they_skip():
    b = builder.Builder(PALETTE)
    eyes.socket_eyes(b, 'eyes', _MissBVH(), (-0.1, 1.6), 0.04, 0.01, 'dark', 'dark', 'skin')
    assert b.misses == {'socket_eyes': {'eyes': {'count': 2, 'point': [-0.018, -0.1, 1.6]}}} and b.parts == ['', 'eyes']


def test_face_decals_count_the_shapes_they_skip():
    b = builder.Builder(PALETTE)
    shape = ([(0.0, 0.0), (0.1, 0.0), (0.0, 0.1)], 'dark', 0.0)
    head.face_decals(b, 'face', _MissBVH(), lambda x, y, u: _Vector((x, y, u)), [shape, shape])
    assert b.misses == {'face_decals': {'face': {'count': 2, 'point': [0.0, -3.0, 0.0]}}}, b.misses


def test_hair_locks_count_the_locks_they_skip():
    b = builder.Builder(PALETTE)
    lock = (0.0, 0.0, (0.0, 0.0, 0.05), 0.01, False)
    hair.hair_locks(b, 'hair', _MissBVH(), [lock] * 3, 'dark')
    assert b.misses == {'hair_locks': {'hair': {'count': 3, 'point': [0.0, 0.0, 10.0]}}}, b.misses


def test_hair_cap_counts_every_missed_cast_and_keeps_its_fallback():
    old = hair.point_loft
    built = []
    hair.point_loft = lambda b, part, rings, color, cap0=None: built.append((rings, cap0))
    try:
        b = builder.Builder(PALETTE)
        hair.hair_cap(b, 'hair', _MissBVH(), (0.0, 0.0, 1.7), lambda phi: 0.3, lambda phi, f: 0.01, 'dark', n=4,
                      rows=2)
        assert b.misses['hair_cap']['hair']['count'] == 2 * 4 + 4 + 1, b.misses
        s = builder.Builder(PALETTE)
        hair.hair_cap(s, 'hair', _MissBVH(), (0.0, 0.0, 1.7), lambda phi: 0.3, lambda phi, f: 0.01, 'dark', n=4,
                      rows=2, symmetric=True)
        assert s.misses['hair_cap']['hair']['count'] == 3 * 3 + 1 and len(s.misses['hair_cap']['hair']['point']) == 3
    finally:
        hair.point_loft = old
    rings, apex = built[0]
    assert math.isclose(apex.z, 1.7 + 0.1 + 0.01) and math.isclose(apex.x, 0.0, abs_tol=1e-12)
    crown = rings[0][0]
    d = hair._dir(0.0, math.pi / 2 + (0.3 - math.pi / 2) * 0.5)
    assert all(math.isclose(a, b, abs_tol=1e-12) for a, b in zip(crown, _Vector((0.0, 0.0, 1.7)) + d * 0.11))


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print('ok', name)
