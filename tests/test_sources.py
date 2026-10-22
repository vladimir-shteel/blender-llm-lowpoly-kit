"""Host tests of the colour sources on the frozen surface: the pure parts of lpk.stages.zones.conform_sources
(the polygon and vertex normals, the normal blended at a point, the carry of a point from one surface onto
another, the report) and the runner's wiring (the sources' collection name, the refusal of a 'conform' that
is not True or False), with bpy replaced by tests/blender_stand_ins.py. tests/blender/sources.py runs the
same paths in Blender.

python tests/test_sources.py"""
import importlib
import os
import sys
import types

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tests'))

from lpk.stages import checks, zones  # noqa: E402

# A unit square in z = 0 split into two triangles facing +Z, and a roof: two slopes of two triangles each
# meeting at a ridge along y at x = 1, the left rising to it, the right falling, each ridge vertex on one
# triangle of each slope or two of each.
SQUARE = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], float)
SQUARE_TRIS = [[0, 1, 2], [0, 2, 3]]
ROOF = np.array([[0, 0, 0], [1, 0, 1], [1, 1, 1], [0, 1, 0], [2, 0, 0], [2, 1, 0]], float)
ROOF_TRIS = [[0, 1, 2], [0, 2, 3], [1, 4, 2], [4, 5, 2]]


def test_polygon_normals_follow_the_corner_order_and_area():
    n = zones.polygon_normals(SQUARE, SQUARE_TRIS + [[0, 3, 2, 1], [0, 1, 1]])
    assert np.allclose(n[:2], [0, 0, 1]) and np.allclose(n[2], [0, 0, -1]), n
    assert np.array_equal(n[3], [0, 0, 0]), 'a polygon of no area has no normal'
    v = zones.vertex_normals(ROOF, ROOF_TRIS)
    assert np.allclose(v[1], [0, 0, 1]) and np.allclose(v[2], [0, 0, 1]), 'the ridge takes both slopes alike'
    assert np.allclose(v[0], [-1, 0, 1] / np.sqrt(2)), v[0]
    assert np.array_equal(zones.vertex_normals(np.vstack([SQUARE, [[5, 5, 5]]]), SQUARE_TRIS)[4], [0, 0, 0])


def test_the_point_normal_blends_without_a_jump_across_an_edge():
    v = zones.vertex_normals(ROOF, ROOF_TRIS)
    on_ridge = np.array([[1.0, 0.5, 1.0], [1.0, 0.5, 1.0]])
    a = zones.point_normals(ROOF, ROOF_TRIS, v, [0, 2], on_ridge)
    assert np.allclose(a[0], a[1]) and np.allclose(a[0], [0, 0, 1]), 'either face at the ridge gives one normal'
    mid = zones.point_normals(ROOF, ROOF_TRIS, v, [1], [[0.25, 0.5, 0.25]])[0]
    assert abs(np.linalg.norm(mid) - 1) < 1e-12 and mid[0] < 0 and mid[2] > 0
    quad = zones.point_normals(SQUARE, [[0, 1, 2, 3]], zones.vertex_normals(SQUARE, [[0, 1, 2, 3]]), [0],
                               [[0.5, 0.5, 0.0]])
    assert np.allclose(quad, [[0, 0, 1]]), 'a polygon of four corners takes its own normal'


def test_a_point_keeps_its_offset_and_its_drift_along_the_surface():
    s = np.array([[0.2, 0.3, 0.004], [0.5, 0.5, -0.002]])
    p = np.array([[0.2, 0.3, 0.0], [0.5, 0.5, 0.0]])
    up = np.tile([0.0, 0.0, 1.0], (2, 1))
    same, h = zones.conformed(s, p, up, p, up)
    assert np.array_equal(same, s) and np.allclose(h, [0.004, -0.002]), 'the same surface moves nothing'
    moved, _ = zones.conformed(s, p, up, p + [0.0, -0.02, 0.01], up)
    assert np.allclose(moved - s, [0.0, -0.02, 0.01]), 'a surface moved carries the points along'
    side = np.tile([0.0, -1.0, 0.0], (2, 1))
    q = np.array([[0.2, -0.1, 0.3], [0.5, -0.1, 0.5]])
    turned, _ = zones.conformed(s, p, up, q, side)
    assert np.allclose(turned, q + h[:, None] * side), 'the offset turns with the normal'
    drift = np.array([[0.2, 0.3, 0.004]]) + [0.001, 0.0, 0.0]
    kept, _ = zones.conformed(drift, p[:1], up[:1], q[:1], side[:1])
    assert np.allclose(kept, q[:1] + 0.004 * side[:1] + [0.001, 0.0, 0.0]), 'the drift along the surface stays'


def test_the_report_counts_moves_and_the_reach():
    before = np.zeros((4, 3))
    after = before.copy()
    after[1] = [0.0, 0.03, 0.0]
    after[2] = [zones.POSITION_STEP / 2, 0.0, 0.0]
    cage, ray = 0.015, 0.03
    offsets = np.array([0.001, cage + checks.POSITION_NOISE / 2, cage + 0.002, cage - ray - 0.001])
    rep = zones.conform_report(before, after, offsets, cage, ray, unmatched=1)
    assert rep == {'vertices': 4, 'moved': 1, 'max_shift_cm': 3.0, 'offset_cm': [-1.6, 1.7], 'outside_reach': 2,
                   'unmasked': 0, 'unmatched': 1}, rep
    rep = zones.conform_report(before, after, offsets, cage, ray, unmasked=[False, False, True, False])
    assert rep['outside_reach'] == 1 and rep['unmasked'] == 1, 'a vertex over another part is counted apart'
    empty = zones.conform_report(np.zeros((0, 3)), np.zeros((0, 3)), np.zeros(0), cage, ray)
    assert empty['vertices'] == 0 and empty['max_shift_cm'] == 0.0 and empty['offset_cm'] is None


def test_the_runner_names_the_sources_collection_and_checks_conform():
    from test_run import stand_ins
    with stand_ins():
        run = importlib.import_module('lpk.run')
        M = types.SimpleNamespace(NAME='Probe', __name__='probe', SOURCES={'Face': {'mask': ('head',), 'conform': 0}})
        assert run.names(M)['sources'] == 'Probe_Sources' and run.names(M)['collection'] == 'Probe'
        try:
            run.build(M, {})
            raise AssertionError("a 'conform' of 0 passed")
        except ValueError as e:
            assert str(e) == "SOURCES Face: 'conform' is True or False", e


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
