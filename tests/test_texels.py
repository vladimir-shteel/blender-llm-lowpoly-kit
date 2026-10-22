"""Host tests of the bake's texel and reach readings in lpk.stages.texture: the reach band, a mark's
texels where it is narrowest, the painted marks the strip, line and eye tools record
(lpk.core.shapes._mark), fan_decal among them, and their round trip through an object property; and the
probe misses the surface tools count (lpk.core.shapes._miss). bpy, bmesh and mathutils are replaced by
stand-ins while the modules are imported; nothing here bakes.

python tests/test_texels.py"""
import ast
import contextlib
import importlib
import math
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class _Vector(tuple):
    """mathutils.Vector as far as the modules' import-time code and fan_decal use it."""

    def __new__(cls, seq=(0.0, 0.0, 0.0)):
        return tuple.__new__(cls, (float(c) for c in seq))

    x = property(lambda s: s[0])
    y = property(lambda s: s[1])
    z = property(lambda s: s[2])

    def __add__(self, o):
        return _Vector(a + b for a, b in zip(self, o))

    def __sub__(self, o):
        return _Vector(a - b for a, b in zip(self, o))

    def __mul__(self, k):
        return _Vector(a * k for a in self)

    __rmul__ = __mul__

    def __truediv__(self, k):
        return _Vector(a / k for a in self)

    def dot(self, o):
        return sum(a * b for a, b in zip(self, o))

    def cross(self, o):
        a, b = self, o
        return _Vector((a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]))

    @property
    def length(self):
        return math.sqrt(self.dot(self))

    def copy(self):
        return _Vector(self)

    def normalized(self):
        n = math.sqrt(sum(c * c for c in self)) or 1.0
        return _Vector(c / n for c in self)


@contextlib.contextmanager
def _blender_stand_ins():
    """bpy, bmesh and mathutils stand-ins for the module-level imports of the stage and shape modules,
    and lpk as a bare package over its folder; sys.modules is restored afterwards."""
    stand_ins = ('bpy', 'bmesh', 'mathutils', 'mathutils.bvhtree')
    ours = lambda name: name in stand_ins or name == 'lpk' or name.startswith('lpk.')
    saved = {k: v for k, v in sys.modules.items() if ours(k)}
    for k in saved:
        del sys.modules[k]
    mathutils = types.ModuleType('mathutils')
    mathutils.Vector = _Vector
    bvhtree = types.ModuleType('mathutils.bvhtree')
    bvhtree.BVHTree = type('BVHTree', (), {})
    lpk = types.ModuleType('lpk')
    lpk.__path__ = [os.path.join(ROOT, 'lpk')]
    sys.modules.update({'bpy': types.ModuleType('bpy'), 'bmesh': types.ModuleType('bmesh'), 'mathutils': mathutils,
                        'mathutils.bvhtree': bvhtree, 'lpk': lpk})
    try:
        yield
    finally:
        for k in [k for k in sys.modules if ours(k)]:
            del sys.modules[k]
        sys.modules.update(saved)


with _blender_stand_ins():
    texture = importlib.import_module('lpk.stages.texture')
    shapes = importlib.import_module('lpk.core.shapes')


def test_reach_band_holds_the_rays_start_and_end():
    r = texture.reach_band([0.004, 0.016, -0.02, 0.015, -0.015, 0.0], 0.015, 0.03)
    assert r['highest'] == 0.016 and r['lowest'] == -0.02
    assert r['beyond'] == [[1, 0.016]], 'above the cage: the rays start under it'
    assert r['deep'] == [[2, -0.02]], 'below cage - ray: the rays end above it'
    assert texture.reach_band([], 0.015, 0.03) == {'highest': None, 'lowest': None, 'beyond': [], 'deep': []}
    edge = texture.reach_band([0.015 + texture.POSITION_NOISE / 2], 0.015, 0.03)
    assert not edge['beyond'], 'within the storage noise of the edge is inside'


def test_mark_texels_read_a_tapered_line_where_it_is_narrowest():
    samples = [(200.0, 'head'), (200.0, 'head'), None, (150.0, 'neck')]
    flat = texture.mark_texels(0.01, samples)
    assert (flat['texels'], flat['part'], flat['points'], flat['under']) == (1.5, 'neck', 3, 0), \
        'one width: the sparsest point'
    tapered = texture.mark_texels(0.01, samples, widths=[0.01, 0.002, 0.004, 0.009])
    assert (tapered['texels'], tapered['width'], tapered['part'], tapered['under']) == (0.4, 0.002, 'head', 1), \
        'a taper reads at its narrow end, not at its starting width'
    none = texture.mark_texels(0.01, [None, None])
    assert none == {'part': None, 'width': 0.01, 'texels_per_m': None, 'texels': None, 'points': 0, 'under': 0}


class _Builder:
    pass


class _Object(dict):
    pass


def test_marks_record_on_the_builder_and_round_trip_through_the_object():
    b = _Builder()
    shapes.mark(b, 'surface_strip', 'detail', 0.0055, [(0.1, 0.2, 1.3), _Vector((0.11, 0.2, 1.31))])
    shapes.mark(b, 'socket_eyes', 'eyes', 0.02, [(0.03, -0.1, 1.6)], kind='eye')
    assert b.marks[0] == {'tool': 'surface_strip', 'part': 'detail', 'kind': 'line', 'width': 0.0055,
                          'points': [[0.1, 0.2, 1.3], [0.11, 0.2, 1.31]]}
    assert b.marks[1]['kind'] == 'eye'
    shapes.mark(b, 'wrapped_stripes', 'head', 0.01, [(0, 0, 1), (0, 0.1, 1)], widths=[0.01, 0.0021])
    assert b.marks[2]['widths'] == [0.01, 0.0021] and b.marks[2]['width'] == 0.01
    assert 'widths' not in b.marks[0], 'a line of one width records none'
    ob = _Object()
    ob[texture.MARKS] = texture.marks_text(b)
    assert texture.marks_of(ob) == b.marks, 'the record round-trips through the object'
    assert texture.marks_text(_Builder()) is None and texture.marks_of(_Object()) == [], \
        'a builder without marks gives no record'


class _FaceBuilder:
    """A builder that keeps the vertices a decal makes and accepts its faces."""

    def __init__(self):
        self.parts = []

    def pid(self, name):
        if name not in self.parts:
            self.parts.append(name)
        return self.parts.index(name)

    def vert(self, co, pid):
        return types.SimpleNamespace(co=_Vector(co))

    def face(self, verts, col, hint=None):
        return types.SimpleNamespace(normal_update=lambda: None, normal=_Vector((0, -1, 0)), normal_flip=lambda: None)


class _Plane:
    """The plane y = 0 seen from the front (-Y): every ray along +Y hits it under its start."""

    def ray_cast(self, origin, direction, distance):
        return _Vector((origin[0], 0.0, origin[2])), _Vector((0, -1, 0)), 0, 0.5


def test_fan_decal_marks_an_eye_by_its_widest_extent_and_a_line_by_its_narrowest_breadth():
    ellipse = [(0.1 + 0.02 * math.cos(k * math.pi / 4), -0.3, 1.6 + 0.012 * math.sin(k * math.pi / 4)) for k in range(8)]
    b = _FaceBuilder()
    shapes.fan_decal(b, 'face', _Plane(), ellipse, (0, 1, 0), 'eye', lift=0.0015, mark='eye')
    (eye,) = b.marks
    assert eye['tool'] == 'fan_decal' and eye['kind'] == 'eye' and eye['part'] == 'face'
    assert eye['width'] == 0.04 and eye['points'] == [[0.1, -0.0015, 1.6]], eye
    bar = [(-0.02, -0.3, 1.5), (0.0, -0.3, 1.497), (0.02, -0.3, 1.5), (0.02, -0.3, 1.506), (-0.02, -0.3, 1.506)]
    shapes.fan_decal(b, 'face', _Plane(), bar, (0, 1, 0), 'mouth', rings=2, mark='line')
    line = b.marks[1]
    assert line['kind'] == 'line' and line['width'] == 0.009, 'from the top edge to the lowest point: %s' % line
    assert len(line['points']) == len(bar) and line['points'][0] == [-0.02, -0.0015, 1.5]
    rect = [(-0.02, -0.3, 1.5), (0.02, -0.3, 1.5), (0.02, -0.3, 1.506), (-0.02, -0.3, 1.506)]
    shapes.fan_decal(b, 'face', _Plane(), rect, (0, 1, 0), 'mouth', mark='line')
    assert b.marks[2]['width'] == 0.006, 'a bar is as broad as its short side'
    plain = _FaceBuilder()
    shapes.fan_decal(plain, 'face', _Plane(), ellipse, (0, 1, 0), 'eye')
    assert not hasattr(plain, 'marks'), 'an unmarked decal records nothing'
    try:
        shapes.fan_decal(_FaceBuilder(), 'face', _Plane(), ellipse, (0, 1, 0), 'eye', mark='pupil')
    except ValueError as e:
        assert 'pupil' in str(e)
    else:
        raise AssertionError('an unknown mark must raise')


def test_the_strip_line_and_eye_tools_record_their_marks():
    calls = {}
    for rel in ('lpk/core/shapes.py', 'lpk/forms/hands.py', 'lpk/forms/markings.py', 'lpk/forms/eyes.py'):
        tree = ast.parse(open(os.path.join(ROOT, rel), encoding='utf-8').read())
        for fn in tree.body:
            if isinstance(fn, ast.FunctionDef):
                for node in ast.walk(fn):
                    if isinstance(node, ast.Call) and getattr(node.func, 'id', None) == 'mark':
                        calls.setdefault(fn.name, []).append(node.args[1].value)
    lines = ('surface_strip', 'ring_band', 'mitten_finger_lines', 'wrapped_stripes')
    eyes = ('socket_eyes', 'traced_eye', 'bevel_eye')
    expected = dict({n: {n} for n in lines + eyes}, _mark_decal={'fan_decal'})   # fan_decal records through it
    assert {k: set(v) for k, v in calls.items()} == expected, calls


def test_probe_misses_keep_the_part_and_the_first_point():
    b = _Builder()
    shapes.miss(b, 'fan_decal', 'head', _Vector((0.012345, -0.1, 1.6)))
    shapes.miss(b, 'fan_decal', 'head', (0.5, 0.5, 0.5))
    shapes.miss(b, 'fan_decal', 'ear.L', (0.1, 0.0, 1.7), n=2)
    shapes.miss(b, 'hair_cap', 'hair', (0.0, 0.0, 2.0))
    assert b.misses == {'fan_decal': {'head': {'count': 2, 'point': [0.0123, -0.1, 1.6]},
                                      'ear.L': {'count': 2, 'point': [0.1, 0.0, 1.7]}},
                        'hair_cap': {'hair': {'count': 1, 'point': [0.0, 0.0, 2.0]}}}, b.misses


def test_every_probe_miss_names_its_operation_part_and_point():
    calls = {}
    for rel in ('lpk/core/shapes.py', 'lpk/forms/eyes.py', 'lpk/forms/hair.py', 'lpk/forms/head.py'):
        tree = ast.parse(open(os.path.join(ROOT, rel), encoding='utf-8').read())
        for fn in tree.body:
            if isinstance(fn, ast.FunctionDef):
                for node in ast.walk(fn):
                    if isinstance(node, ast.Call) and getattr(node.func, 'id', None) == 'miss':
                        assert len(node.args) == 4, (fn.name, ast.unparse(node))
                        calls.setdefault(fn.name, set()).add(node.args[1].value)
    names = ('cast_point', 'snap_ring', 'conform_plate', 'fan_decal', 'axis_fill', 'ray_grid', 'socket_eyes', 'hair_cap',
             'hair_locks', 'face_decals', 'long_beard')
    assert calls == {n: {n} for n in names}, calls


if __name__ == '__main__':
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print('ok     ', name)
            except Exception as e:
                failed += 1
                print('FAILED ', name, type(e).__name__, e)
    sys.exit(1 if failed else 0)
