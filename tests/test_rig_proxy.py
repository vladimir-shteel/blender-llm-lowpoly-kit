"""Host tests of the numpy helpers behind lpk.stages.rig.heat_proxy_weights, of the weights backend
order and report, of the influence limit the backends keep, of skin's steps, which leave no assignment of
weight 0, and of its binding checks (no Blender needed: bpy, bmesh, addon_utils and mathutils are
replaced by stand-ins while lpk.stages.rig is imported).

python tests/test_rig_proxy.py"""
import contextlib
import importlib
import os
import sys
import types

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@contextlib.contextmanager
def _blender_stand_ins():
    """bpy, bmesh, addon_utils and mathutils stand-ins that cover only rig.py's module-level imports, and
    lpk as a bare package over its folder; sys.modules is restored afterwards."""
    stand_ins = ('bpy', 'bmesh', 'addon_utils', 'mathutils', 'mathutils.bvhtree', 'mathutils.geometry')
    ours = lambda name: name in stand_ins or name == 'lpk' or name.startswith('lpk.')
    saved = {k: v for k, v in sys.modules.items() if ours(k)}
    for k in saved:
        del sys.modules[k]
    mathutils = types.ModuleType('mathutils')
    mathutils.Vector = type('Vector', (tuple,), {})
    mathutils.kdtree = types.ModuleType('mathutils.kdtree')
    bvhtree = types.ModuleType('mathutils.bvhtree')
    bvhtree.BVHTree = type('BVHTree', (), {})
    geometry = types.ModuleType('mathutils.geometry')
    geometry.intersect_point_line = lambda *a: None
    mathutils.bvhtree, mathutils.geometry = bvhtree, geometry
    lpk = types.ModuleType('lpk')
    lpk.__path__ = [os.path.join(ROOT, 'lpk')]
    sys.modules.update({'bpy': types.ModuleType('bpy'), 'bmesh': types.ModuleType('bmesh'),
                        'addon_utils': types.ModuleType('addon_utils'), 'mathutils': mathutils,
                        'mathutils.bvhtree': bvhtree, 'mathutils.geometry': geometry, 'lpk': lpk})
    try:
        yield
    finally:
        for k in [k for k in sys.modules if ours(k)]:
            del sys.modules[k]
        sys.modules.update(saved)


with _blender_stand_ins():
    rig = importlib.import_module('lpk.stages.rig')

A, B, C = np.array([0.0, 0.0, 0.0]), np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0])


def _bary(p, a=A, b=B, c=C):
    p = np.asarray(p, dtype=np.float64).reshape(-1, 3)
    n = len(p)
    return rig._closest_barycentric(p, np.tile(a, (n, 1)), np.tile(b, (n, 1)), np.tile(c, (n, 1)))


def _point(bc, a=A, b=B, c=C):
    return bc[:, 0:1] * a + bc[:, 1:2] * b + bc[:, 2:3] * c


def test_closest_barycentric_regions():
    cases = [
        ((0.25, 0.25, 1.0), (0.5, 0.25, 0.25)),     # inside, above the plane
        ((-1.0, -1.0, 0.0), (1.0, 0.0, 0.0)),       # vertex A
        ((2.0, -0.5, 0.3), (0.0, 1.0, 0.0)),        # vertex B
        ((-0.5, 2.0, -0.2), (0.0, 0.0, 1.0)),       # vertex C
        ((0.5, -1.0, 0.0), (0.5, 0.5, 0.0)),        # edge AB
        ((-1.0, 0.5, 0.0), (0.5, 0.0, 0.5)),        # edge AC
        ((1.0, 1.0, 0.5), (0.0, 0.5, 0.5)),         # edge BC
    ]
    got = _bary([p for p, _ in cases])
    assert np.allclose(got, [e for _, e in cases], atol=1e-12), got


def test_closest_barycentric_beats_dense_sampling():
    rng = np.random.default_rng(7)
    k = np.linspace(0.0, 1.0, 81)
    u, v = np.meshgrid(k, k)
    keep = (u + v) <= 1.0
    grid = np.stack([1.0 - u[keep] - v[keep], u[keep], v[keep]], axis=1)
    for _ in range(40):
        a, b, c = rng.normal(size=(3, 3))
        p = rng.normal(size=(1, 3)) * 2.0
        bc = _bary(p, a, b, c)
        assert np.all(bc >= 0.0) and np.isclose(bc.sum(), 1.0)
        d = np.linalg.norm(p - _point(bc, a, b, c))
        samples = np.linalg.norm(p - _point(grid, a, b, c), axis=1)
        assert d <= samples.min() + 1e-12, (d, samples.min())
        assert samples.min() - d < 0.05 * max(np.linalg.norm(b - a), np.linalg.norm(c - a), np.linalg.norm(c - b))


def test_closest_barycentric_degenerate_triangles():
    seg = np.array([2.0, 0.0, 0.0])
    bc = _bary([(1.5, 1.0, 0.0)], A, B, seg)
    assert np.isfinite(bc).all() and np.isclose(bc.sum(), 1.0)
    assert np.allclose(_point(bc, A, B, seg), [(1.5, 0.0, 0.0)])
    bc = _bary([(0.3, 0.4, 0.5)], A, A, A)
    assert np.allclose(bc, [(1.0, 0.0, 0.0)])


def test_transfer_nearest_interpolates_and_measures_distance():
    verts = np.array([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], dtype=np.float64)
    tris = np.array([(0, 1, 2), (0, 2, 3)])
    W = np.array([(1.0, 0.0), (0.0, 1.0), (0.0, 1.0), (1.0, 0.0)])
    p = np.array([(0.75, 0.25, 0.2), (0.25, 0.75, -0.1), (2.0, 0.5, 0.0)])
    values, dist = rig._transfer_nearest(p, verts, tris, [0, 1, 0], W)
    assert np.allclose(values, [(0.25, 0.75), (0.75, 0.25), (0.0, 1.0)])
    assert np.allclose(dist, [0.2, 0.1, 1.0])


def test_transfer_nearest_agrees_on_a_shared_edge():
    verts = np.array([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], dtype=np.float64)
    tris = np.array([(0, 1, 2), (0, 2, 3)])
    W = np.array([(0.1, 0.9), (0.4, 0.6), (0.7, 0.3), (0.2, 0.8)])
    p = np.array([(0.3, 0.3, 0.05)] * 2)
    values, dist = rig._transfer_nearest(p, verts, tris, [0, 1], W)
    assert np.allclose(values[0], values[1]) and np.allclose(dist, 0.05)
    again, _ = rig._transfer_nearest(p, verts, tris, [0, 1], W)
    assert np.array_equal(values, again)


def test_smooth_weights():
    W = np.array([(1.0, 0.0), (0.0, 0.0), (0.0, 1.0), (0.5, 0.5)])
    edges = np.array([(0, 1), (1, 2)])
    one = rig._smooth_weights(W, edges, 1)
    assert np.allclose(one, [(0.5, 0.0), (0.25, 0.25), (0.0, 0.5), (0.5, 0.5)])
    assert np.array_equal(W, [(1.0, 0.0), (0.0, 0.0), (0.0, 1.0), (0.5, 0.5)])
    zero = rig._smooth_weights(W, edges, 0)
    assert np.array_equal(zero, W) and zero is not W
    many = rig._smooth_weights(W, edges, 200)
    assert np.allclose(many[:3], many[0]) and np.allclose(many[3], (0.5, 0.5))


def test_islands_label_by_smallest_vertex():
    labels = rig._islands(7, [(5, 4), (1, 2), (4, 3), (2, 0)])
    assert labels.tolist() == [0, 0, 0, 3, 3, 3, 6]
    assert rig._islands(3, np.zeros((0, 2))).tolist() == [0, 1, 2]


def test_vertex_normals_are_unweighted_triangle_sums():
    verts = np.array([(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1), (5, 5, 5)], dtype=np.float64)
    tris = np.array([(0, 2, 1), (0, 1, 3)])
    nrm = rig._vertex_normals(verts, tris)
    s = 1.0 / np.sqrt(2.0)
    assert np.allclose(nrm[0], (0.0, -s, -s)) and np.allclose(nrm[1], (0.0, -s, -s))
    assert np.allclose(nrm[2], (0, 0, -1)) and np.allclose(nrm[3], (0, -1, 0))
    assert np.array_equal(nrm[4], (0, 0, 0))


def test_heat_closest_penalises_bones_outside_the_surface():
    p = np.array([(0.0, 0.0, 0.0)])
    up = np.array([(0.0, 0.0, 1.0)])
    heads = np.array([(-1.0, 0.0, -0.10), (-1.0, 0.0, 0.05)])
    tails = np.array([(1.0, 0.0, -0.10), (1.0, 0.0, 0.05)])
    close, ends = rig._heat_closest(p, up, heads, tails)
    assert close.tolist() == [[True, False]]
    assert np.allclose(ends[0], [(0.0, 0.0, -0.10), (0.0, 0.0, 0.05)])
    side = np.array([(1.0, 0.0, 0.0)])
    close, _ = rig._heat_closest(p, side, heads, tails)
    assert close.tolist() == [[False, True]]
    close, _ = rig._heat_closest(p, side, [(-1.0, 0.0, -0.1), (-1.0, 0.0, 0.1)], [(1.0, 0.0, -0.1), (1.0, 0.0, 0.1)])
    assert close.tolist() == [[True, True]]


def test_heat_closest_clamps_to_bone_ends_and_handles_points_on_bones():
    p = np.array([(3.0, 0.0, 0.0), (0.5, 0.0, 0.0)])
    nrm = np.array([(1.0, 0.0, 0.0), (0.0, 0.0, 1.0)])
    close, ends = rig._heat_closest(p, nrm, [(0.0, 0.0, 0.0), (0.0, 5.0, 0.0)], [(1.0, 0.0, 0.0), (0.0, 5.0, 0.0)])
    assert np.allclose(ends[0, 0], (1.0, 0.0, 0.0)) and np.allclose(ends[0, 1], (0.0, 5.0, 0.0))
    assert close.tolist() == [[True, False], [True, False]]


# The weights backends' implementations by function name, as rig.WEIGHTS binds them.
_IMPLEMENTS = {'vhd_weights': 'vhd', 'heat_proxy_weights': 'heat_proxy', 'heat_weights': 'heat',
               '_keep_distance': 'distance'}


@contextlib.contextmanager
def _patched(**fns):
    """Replace module functions of rig, and a backend's implementation in rig.WEIGHTS, for the block."""
    old = {k: getattr(rig, k) for k in fns}
    bound = dict(rig.WEIGHTS)
    for k, f in fns.items():
        setattr(rig, k, f)
        if k in _IMPLEMENTS:
            rig.WEIGHTS[_IMPLEMENTS[k]] = (f, bound[_IMPLEMENTS[k]][1])
    try:
        yield
    finally:
        for k, f in old.items():
            setattr(rig, k, f)
        rig.WEIGHTS.update(bound)


def _backend(name, fail=False, seen=None):
    def run(obj_name, rig_name, allowed, fixed=None, influences=None):
        if seen is not None:
            seen.append((name, influences))
        if fail:
            raise RuntimeError(name + ' failed')
        return {'weights': name}
    return run


def test_auto_tries_vhd_then_heat_proxy_then_heat_then_distance():
    assert rig.BACKENDS == ('vhd', 'heat_proxy', 'heat', 'distance')
    every = lambda: ['vhd', 'heat_proxy', 'heat', 'distance']
    with _patched(available_backends=every, vhd_weights=_backend('vhd', True),
                  heat_proxy_weights=_backend('heat_proxy'), heat_weights=_backend('heat'),
                  _keep_distance=_backend('distance')):
        rep = rig.weights('Body', 'Body_Rig', {})
    assert rep['backend'] == 'heat_proxy' and rep['weights'] == 'heat_proxy'
    assert rep['skipped'] == [{'backend': 'vhd', 'error': 'vhd failed'}]
    assert (rep['requested'], rep['available']) == ('auto', every())
    with _patched(available_backends=every, vhd_weights=_backend('vhd', True),
                  heat_proxy_weights=_backend('heat_proxy', True), heat_weights=_backend('heat', True),
                  _keep_distance=_backend('distance')):
        rep = rig.weights('Body', 'Body_Rig', {})
    assert rep['backend'] == 'distance'
    assert [s['backend'] for s in rep['skipped']] == ['vhd', 'heat_proxy', 'heat']
    with _patched(available_backends=lambda: ['heat_proxy', 'heat', 'distance'],
                  heat_proxy_weights=_backend('heat_proxy', True), heat_weights=_backend('heat')):
        rep = rig.weights('Body', 'Body_Rig', {})
    assert rep['backend'] == 'heat' and [s['backend'] for s in rep['skipped']] == ['heat_proxy']


def test_named_backend_runs_alone_and_unknown_is_refused():
    with _patched(available_backends=lambda: ['heat_proxy', 'distance'], heat_proxy_weights=_backend('heat_proxy')):
        rep = rig.weights('Body', 'Body_Rig', {}, backend='heat_proxy')
    assert rep == {'weights': 'heat_proxy', 'backend': 'heat_proxy', 'requested': 'heat_proxy',
                   'available': ['heat_proxy', 'distance']}, rep
    try:
        rig.weights('Body', 'Body_Rig', {}, backend='voxel')
    except ValueError as e:
        assert 'heat_proxy' in str(e)
    else:
        raise AssertionError('unknown backend accepted')


def test_weights_pass_the_influence_limit_to_every_backend():
    seen = []
    every = lambda: ['vhd', 'heat_proxy', 'heat', 'distance']
    with _patched(available_backends=every, vhd_weights=_backend('vhd', True, seen),
                  heat_proxy_weights=_backend('heat_proxy', False, seen)):
        rig.weights('Body', 'Body_Rig', {}, influences=4)
        rig.weights('Body', 'Body_Rig', {}, backend='heat_proxy')
    assert seen == [('vhd', 4), ('heat_proxy', 4), ('heat_proxy', rig.MAX_INFLUENCES)], seen


def test_limit_keeps_the_strongest_influences():
    w = {'a': 0.4, 'b': 0.3, 'c': 0.2, 'd': 0.08, 'e': 0.02}
    three = rig._limit(w)
    assert len(three) == rig.MAX_INFLUENCES == 3 and set(three) == {'a', 'b', 'c'}
    assert abs(sum(three.values()) - 1.0) < 1e-12 and abs(three['a'] - 0.4 / 0.9) < 1e-12
    four = rig._limit(w, 4)
    assert set(four) == {'a', 'b', 'c', 'd'} and abs(four['d'] - 0.08 / 0.98) < 1e-12
    assert set(rig._limit(w, 5)) == {'a', 'b', 'c', 'd'}, 'a share under MIN_WEIGHT is dropped'
    assert rig._limit({'a': 0.0}) is None



class _Group:
    """bpy VertexGroup: add (REPLACE) and remove change the memberships of the body's vertices."""

    def __init__(self, body, name, index):
        self.body, self.name, self.index = body, name, index

    def add(self, ids, weight, kind):
        for i in ids:
            groups = self.body.data.vertices[i].groups
            groups[:] = [g for g in groups if g.group != self.index] + [types.SimpleNamespace(group=self.index,
                                                                                               weight=weight)]

    def remove(self, ids):
        for i in ids:
            groups = self.body.data.vertices[i].groups
            groups[:] = [g for g in groups if g.group != self.index]


class _Groups(list):
    def get(self, name):
        return next((g for g in self if g.name == name), None)

    def new(self, name):
        self.append(_Group(self.body, name, len(self)))
        return self[-1]


def _body(n):
    body = types.SimpleNamespace(name='Body', data=types.SimpleNamespace(
        vertices=[types.SimpleNamespace(index=i, groups=[]) for i in range(n)]))
    body.vertex_groups = _Groups()
    body.vertex_groups.body = body
    return body


def _memberships(body):
    names = [g.name for g in body.vertex_groups]
    return [{names[g.group]: g.weight for g in v.groups} for v in body.data.vertices]


def test_skin_runs_its_steps_in_the_rest_pose_and_leaves_no_weight_zero():
    body = _body(3)
    rig._set_weights(body, [{'Hips': 1.0, 'Spine': 0.0}, {'Spine': 0.5, 'Chest': 0.5}, {'Chest': 0.0}])
    assert _memberships(body) == [{'Hips': 1.0}, {'Spine': 0.5, 'Chest': 0.5}, {}], 'a weight of 0 is no assignment'
    spine, chest = body.vertex_groups.get('Spine'), body.vertex_groups.get('Chest')
    spine.add([0], 0.0, 'REPLACE')                                  # a membership another writer left at 0
    chest.add([0, 2], 0.0, 'REPLACE')
    before = [{n: w for n, w in m.items() if w > 0} for m in _memberships(body)]
    saved = getattr(rig.bpy, 'data', None)
    rig.bpy.data = types.SimpleNamespace(objects={'Body': body})
    try:
        assert rig.drop_zero_weights('Body') == 3 and rig.drop_zero_weights('Body') == 0
    finally:
        rig.bpy.data = saved
    assert _memberships(body) == before == [{'Hips': 1.0}, {'Spine': 0.5, 'Chest': 0.5}, {}], 'positive ones stay'
    calls = []
    record = lambda name, out: (lambda *a, **k: calls.append(name) or out)
    bones = [types.SimpleNamespace(name=n, use_deform=True) for n in ('Hips', 'Spine')]
    scene = types.SimpleNamespace(data=types.SimpleNamespace(objects={'Body_Rig': types.SimpleNamespace(
        data=types.SimpleNamespace(bones=bones))}))
    held = types.SimpleNamespace(held_pose=lambda name: calls.append('rest') or contextlib.nullcontext())
    with _patched(bpy=scene, pose=held, built_parts=lambda name: ['trunk', 'arm.L'],
                  distance_weights=record('distance', None), weights=record('backend', {'max_influences': 1}),
                  smooth_zones=record('smooth', {'smooth_baked': 0, 'mirror_unmatched': 0}),
                  drop_zero_weights=record('drop', 2)):
        allowed = {'trunk': ['Hips', 'Spine'], 'arm.L': ['Spine']}
        out = rig.skin('Body', 'Body_Rig', allowed, joins=[('trunk', 'arm.L', {})], influences=2)
        assert calls == ['rest', 'distance', 'backend', 'drop', 'smooth', 'drop'], 'each skin step ends with the drop'
        assert out['weights']['zero_dropped'] == out['smooth']['zero_dropped'] == 2 and out['influences'] == 2
        del calls[:]
        flat = rig.skin('Body', 'Body_Rig', allowed)
        assert calls == ['rest', 'distance', 'backend', 'drop'] and flat['smooth'] is None, 'no joins: no bake'
        del calls[:]
        for bad, needle in (({'trunk': ['Hips']}, 'arm.L'), (dict(allowed, trunk=['Chest']), 'lacks: trunk: Chest')):
            try:
                rig.skin('Body', 'Body_Rig', bad)
            except ValueError as e:
                assert needle in str(e), e
            else:
                raise AssertionError('binding %r accepted' % bad)
        try:
            rig.skin('Body', 'Body_Rig', allowed, joins=[('trunk', 'leg.L', {})])
        except ValueError as e:
            assert 'leg.L' in str(e), e
        else:
            raise AssertionError('a join of a part the body lacks accepted')
        assert calls == [], 'a refused binding changes no weight'


def test_binding_problems():
    ok = rig.binding_problems(['trunk', 'belt'], ['Hips', 'Socket'], ['Hips'], {'trunk': ['Hips']},
                              {'belt': {'Hips': 1.0}})
    assert ok == []
    problems = rig.binding_problems(['trunk', 'hair', 'prop', 'cape'], ['Hips', 'Socket'], ['Hips'],
                                    {'trunk': ['Hips', 'Ear.L'], 'hair': ['Socket'], 'cape': []},
                                    {'prop': {'Socket': 1.0}}, [('trunk', 'arm.L', {})])
    assert problems == ["the built part 'cape' takes no bone: give it bones in allowed",
                        'bones the rig lacks: trunk: Ear.L',
                        'bones that deform nothing: hair: Socket; prop: Socket',
                        'the join trunk - arm.L names parts the body does not carry: arm.L'], problems
    assert rig.binding_problems(['hair'], ['Hips'], ['Hips'], {}, {}) == [
        'the built parts hair have no bones in allowed and no weights in fixed']

if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print('ok', name)
