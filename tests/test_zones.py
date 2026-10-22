"""Host tests of the zone tools' pure parts (lpk.stages.zones) and of the runner's frozen-mode wiring
(lpk.run, with bpy replaced by tests/blender_stand_ins.py): the build stamp's digests, the zone choice from
nearest-surface hits, the join-loop tags, the report counts, the per-part table of the summary, the
colour matching of adopt, the operations on a part (ring distances, falloff weights, the transform, the
pivots, welded parts, pinned vertices, the smoothing, the collapse order, the report); the stage list with adopt and freeze, the discard_edits option and the guard's
messages for each mode, the operations' refusal in the parametric mode; the UV digest and the texture
modes' wiring (the stage order, the refusals of unwrap and pack, the UV layer a freeze keeps, the 'over'
check, the guard's UV message); the UV check of mesh edits under a frozen texture (UV islands, edges and
neighbours, each fault by part, the triangle depths) and its repair (densities, charts, the layout in free
space) with the runner's UV calls. tests/blender/frozen_mode.py, tests/blender/zone_ops.py,
tests/blender/texture_freeze.py and tests/blender/uv_repair.py run the same paths in Blender.

python tests/test_zones.py"""
import importlib
import os
import sys
import types

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tests'))

from lpk.stages import zones  # noqa: E402

# Two unit squares side by side in the plane z = 0, each split into two triangles: vertices 0-2-3-1 and
# 2-4-5-3, x from 0 to 2.
CO = np.array([[0, 0, 0], [0, 1, 0], [1, 0, 0], [1, 1, 0], [2, 0, 0], [2, 1, 0]], float)
TRIS = [[0, 2, 3], [0, 3, 1], [2, 4, 5], [2, 5, 3]]
LOOP_TOTAL = [3, 3, 3, 3]
LOOP_VERT = [i for t in TRIS for i in t]
EDGES = [[0, 2], [2, 3], [0, 3], [3, 1], [1, 0], [2, 4], [4, 5], [2, 5], [5, 3]]


def test_the_topology_key_reads_the_mesh_as_stored_and_ignores_moves():
    key = zones.topology_key(6, LOOP_TOTAL, LOOP_VERT)
    assert key == zones.topology_key(6, np.array(LOOP_TOTAL), np.array(LOOP_VERT, np.int32))
    assert key != zones.topology_key(7, LOOP_TOTAL, LOOP_VERT), 'a loose vertex changes it'
    swapped = [i for t in [TRIS[1], TRIS[0]] + TRIS[2:] for i in t]
    assert key != zones.topology_key(6, LOOP_TOTAL, swapped), 'the face order is part of it'
    quads = zones.topology_key(6, [4, 4], [0, 2, 3, 1, 2, 4, 5, 3])
    assert quads != key


def test_the_position_digest_rounds_to_its_step():
    d = zones.position_digest(CO)
    assert d == zones.position_digest(CO.astype(np.float32)), 'float32 positions read back digest the same'
    assert d == zones.position_digest(CO + zones.POSITION_STEP * 0.2)
    moved = CO.copy()
    moved[3, 2] += 1e-4
    assert d != zones.position_digest(moved)


def test_polygons_and_their_parts_follow_the_majority_rule():
    polys = zones.polygons([0, 3, 6, 9], LOOP_TOTAL, LOOP_VERT)
    assert polys == TRIS
    vpart = [1, 1, 2, 2, 2, 2]
    assert zones.polygon_parts(polys, vpart).tolist() == [2, 1, 2, 2]
    assert zones.polygon_parts([[0, 2, 1, 3]], vpart).tolist() == [1], 'a tie goes to the first vertex'


def test_a_vertex_takes_the_part_of_the_nearest_corner_of_its_face():
    ref_part = np.array([1, 1, 1, 1, 2, 2])
    hits = np.array([0, 2, 2, 3])
    points = np.array([[1.0, 0.0, 0.0], [1.9, 0.1, 0.0], [1.2, 0.1, 0.0], [1.0, 1.0, 0.0]])
    got = zones.nearest_corner_parts(hits, points, CO, TRIS, ref_part)
    assert got.tolist() == [1, 2, 1, 1], 'on a reference vertex its part, inside a face its nearest corner'
    assert got.dtype.kind == 'i'


def test_join_tags_hold_only_close_to_a_tagged_vertex():
    tags = zones.join_tags([[1, 0, 0], [1, 0, 5e-5], [1, 0, 3e-4], [0, 0, 0]], CO, [0, 0, 1, 0, 0, 0])
    assert tags.tolist() == [1, 1, 0, 0]
    assert zones.join_tags(CO, CO, np.zeros(6)).tolist() == [0] * 6


def test_counts_compare_names_not_indices():
    names = ['', 'head', 'trunk']
    assert zones.name_counts([1, 2, 2, 7], names) == {'head': 1, 'trunk': 2, '': 1}
    # The new list orders the parts the other way round: the same names do not count as changed.
    assert zones.changed_counts([1, 2, 2], names, [2, 1, 1], ['', 'trunk', 'head']) == {}
    assert zones.changed_counts([1, 2, 2], names, [1, 1, 2], names) == {'head': 1}
    assert zones.changed_counts(None, names, [1, 2], names) == {'head': 1, 'trunk': 1}
    far, worst = zones.far_counts([0.0, 0.01, 0.03, 0.001], [1, 2, 2, 1], names)
    assert far == {'trunk': 2} and worst == {'trunk': 3.0}


def test_the_part_table_counts_borders_bounds_and_mirror():
    co = CO - [1.0, 0.0, 0.0]
    vpart = [1, 1, 2, 2, 3, 3]
    names = ['', 'side.R', 'mid', 'side.L']
    polys = TRIS
    table = zones.part_table(co, vpart, polys, [0, 0, 1, 5], EDGES, names, 2)
    assert list(table) == ['side.R', 'mid', 'side.L']
    assert table['side.R']['mirror'] == 'side.L' and table['side.L']['mirror'] == 'side.R'
    assert table['mid']['mirror'] == 'mid' and table['mid']['mirror_offset'] == 0.0
    assert table['side.L']['centre'] == [1.0, 0.5, 0.0] and table['side.L']['size'] == [0.0, 1.0, 0.0]
    assert zones.polygon_parts(polys, vpart).tolist() == [2, 1, 3, 2]
    assert table['mid']['faces'] == 2 and table['mid']['tris'] == 2 and table['mid']['verts'] == 2
    assert table['mid']['neighbours'] == {'side.R': 1, 'side.L': 1}
    assert table['mid']['border_m'] == {'side.R': round(2 ** 0.5, 3), 'side.L': round(2 ** 0.5, 3)}
    assert table['mid']['uncoloured'] == 1, 'pal 5 is outside a palette of 2'
    unnamed = zones.part_table(co, [0, 9, 2, 2, 2, 2], polys, [0] * 4, EDGES, names, 2)
    assert unnamed['']['verts'] == 2, 'ids 0 and out of range collect under the empty name'
    assert zones.deviation([0.01, 0.03]) == {'mean_cm': 2.0, 'max_cm': 3.0} and zones.deviation([]) is None


def test_adopt_matches_colours_and_groups():
    palette = {'skin': (0.87, 0.71, 0.60), 'shirt': (0.27, 0.48, 0.62), 'black': (0.0, 0.0, 0.0)}
    srgb = (0.02, 0.5, 0.9)
    lin = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in srgb]   # srgb_to_linear's
    assert np.allclose(zones.linear_to_srgb(lin), srgb, atol=1e-12)
    assert zones.nearest_colour((0.3, 0.5, 0.6), palette) == 1
    assert zones.nearest_colour((0.0, 0.0, 0.0), {'a': (0.1, 0.1, 0.1), 'b': (0.1, 0.1, 0.1)}) == 0
    assert zones.strongest_group([(3, 0.4), (1, 0.6), (2, 0.6)], {1: 'head', 2: 'trunk'}) == 1
    assert zones.strongest_group([(3, 0.9)], {1: 'head'}) is None
    assert zones.strongest_group([(1, 0.0)], {1: 'head'}) is None


# A hexagon fan: vertex 0 at the centre, 1 to 6 round it, one part; a separate pair 7-8 of another part.
FAN = np.array([[0, 0, 1.0]] + [[np.cos(k * np.pi / 3), np.sin(k * np.pi / 3), 0.0] for k in range(6)]
               + [[5, 0, 0], [6, 0, 0]], float)
FAN_TRIS = [[0, k, k % 6 + 1] for k in range(1, 7)]
FAN_EDGES = [[0, k] for k in range(1, 7)] + [[k, k % 6 + 1] for k in range(1, 7)] + [[7, 8]]


def test_rings_count_edges_from_the_part_and_weights_fall_to_zero():
    rings = zones.ring_distances(6, EDGES, [1], 5)
    assert rings.tolist() == [1, 0, 2, 1, 3, 2], rings
    assert zones.ring_distances(6, EDGES, [1], 1).tolist() == [1, 0, -1, 1, -1, -1]
    assert zones.ring_distances(9, FAN_EDGES, [0], 4)[7:].tolist() == [-1, -1], 'a separate shell is not reached'
    w = zones.falloff_weights([0, 1, 2, 3, -1], 2)
    assert np.allclose(w, [1.0, 2 / 3, 1 / 3, 0.0, 0.0])
    assert zones.falloff_weights([0, 1, -1], 0).tolist() == [1.0, 0.0, 0.0]


def test_the_transform_turns_scales_and_blends_about_its_pivot():
    R = zones.rotation_matrix((0, 0, 90))
    assert np.allclose(R @ [1, 0, 0], [0, 1, 0])
    assert np.allclose(zones.rotation_matrix((90, 0, 90)) @ [0, 1, 0], [0, 0, 1]), 'X first, then Z'
    co = np.array([[1, 0, 0], [3, 0, 2], [2, 2, 0.0]])
    assert zones.pivot_point(co, 'centre').tolist() == [2, 1, 1] and zones.pivot_point(co, 'base').tolist() == [2, 1, 0]
    assert zones.pivot_point(co, (0, 0, 5)).tolist() == [0, 0, 5]
    for bad in ('middle', (1, 2)):
        try:
            zones.pivot_point(co, bad)
            raise AssertionError('pivot %r passed' % (bad,))
        except ValueError as e:
            assert 'centre, base' in str(e)
    out = zones.transformed(co, [1, 0.5, 0], (0, 0, 1), (0, 0, 0), 2.0, (1, 0, 0))
    assert np.allclose(out, [[1, 0, 1], [4, 0, 3.5], [2, 2, 0]]), out
    out = zones.transformed(co, [1, 1, 1], (0, 0, 0), (0, 0, 0), (1, 1, 0.5), (0, 0, 0))
    assert np.allclose(out[:, 2], [0, 1, 0])


def test_welds_pins_and_the_faces_of_a_part():
    vpart = [1, 1, 2, 2, 2, 2]
    assert zones.welded_parts(EDGES, vpart, 1) == [2] and zones.welded_parts(EDGES, vpart, 2) == [1]
    assert zones.welded_parts(FAN_EDGES, [1] * 7 + [2, 2], 2) == []
    assert zones.part_faces(TRIS, vpart, 2).tolist() == [False, False, True, True]
    assert zones.pinned_vertices(TRIS, vpart, 2).tolist() == [False, False, True, True, True, True]
    pin = zones.pinned_vertices(FAN_TRIS, [1] * 9, 1)
    assert pin.tolist() == [False] + [True] * 6 + [False, False], 'the rim is pinned, the centre is not'


def test_smoothing_moves_only_the_free_vertices_all_at_once():
    movable = np.zeros(9, bool)
    movable[0] = True
    out = zones.smoothed(FAN, FAN_EDGES, movable, 1, 0.5)
    assert np.allclose(out[0], [0, 0, 0.5]) and np.array_equal(out[1:], FAN[1:])
    assert np.allclose(zones.smoothed(FAN, FAN_EDGES, movable, 2, 0.5)[0], [0, 0, 0.25])
    both = np.zeros(9, bool)
    both[[7, 8]] = True
    out = zones.smoothed(FAN, FAN_EDGES, both, 1, 1.0)
    assert np.allclose(out[7], [6, 0, 0]) and np.allclose(out[8], [5, 0, 0]), 'one simultaneous update'


def test_collapses_go_cheapest_first_and_never_share_a_neighbourhood():
    up = [(0, 0, 1)]
    assert zones.collapse_cost((0, 0, 0), (1, 0, 0), up) == 0.0
    assert zones.collapse_cost((0, 0, 0), (1, 0, 2), up + [(1, 0, 0)]) == 5.0
    nb = {0: [1], 1: [0], 2: [3], 3: [2, 4], 4: [3, 5], 5: [4]}
    picks = zones.collapse_order([(0.5, 0, 1), (0.1, 4, 5), (0.1, 3, 4), (0.2, 2, 3)], nb, 5)
    assert picks == [(3, 4), (0, 1)], picks
    assert zones.collapse_order([(0.5, 0, 1), (0.1, 4, 5)], nb, 1) == [(4, 5)]


def test_the_operation_report_shape():
    rep = zones.operation_report('smooth', 'trunk', (10, 16), (10, 16), 1.5, pinned=4)
    assert rep == {'operation': 'smooth', 'part': 'trunk', 'vertices': [10, 10], 'faces': [16, 16],
                   'max_displacement_cm': 1.5, 'pinned': 4}
    assert zones.max_displacement_cm(CO, CO + [0, 0, 0.0123]) == 1.23
    assert zones.max_displacement_cm(np.zeros((0, 3)), np.zeros((0, 3))) == 0.0


def _runner():
    from test_run import stand_ins
    return stand_ins


def test_the_runner_lists_adopt_and_freeze_and_routes_discard_edits():
    with _runner()():
        run = importlib.import_module('lpk.run')
        assert run.STAGES.index('capture_edits') < run.STAGES.index('adopt') < run.STAGES.index('freeze') \
            < run.STAGES.index('build')
        assert {'adopt', 'freeze'} <= set(run.MEASURED) and set(run.RUNNERS) | {'pack'} == set(run.STAGES)
        assert 'discard_edits' in run.OPTIONS and set(run.OPTIONS) == {'rescale', 'backend', 'discard_edits'}
        try:
            run.check_options({'discard': True})
            raise AssertionError('an unknown option passed')
        except ValueError as e:
            assert 'discard_edits' in str(e)
        calls = []
        saved = dict(run.RUNNERS)
        for k in run.RUNNERS:
            run.RUNNERS[k] = (lambda name: lambda M, P, **kw: calls.append((name, kw)))(k)
        try:
            run.model(os.path.join(ROOT, 'examples', 'mannequin', 'mannequin.py'), ('build', 'freeze', 'adopt', 'rig'),
                      discard_edits=True, backend='distance')
        finally:
            run.RUNNERS.update(saved)
        assert calls == [('adopt', {}), ('freeze', {}), ('build', {'discard_edits': True}),
                         ('rig', {'backend': 'distance'})], calls


def test_the_guard_names_the_stage_that_keeps_each_change():
    with _runner()():
        run = importlib.import_module('lpk.run')
        z = importlib.import_module('lpk.stages.zones')
        objects = sys.modules['bpy'].data.objects
        saved = z.edited
        M = types.SimpleNamespace(NAME='Probe', __name__='probe')
        try:
            run.guard(M, 'build')
            objects['Probe'] = object()
            expected = {
                (False, 'topology'): 'set FROZEN = True', (True, 'topology'): 'run freeze to store the edit',
                (False, 'positions'): 'run capture_edits', (True, 'positions'): 'run freeze to store the moves',
                (False, 'unstamped'): 'carries no build stamp', (True, 'unstamped'): 'carries no build stamp'}
            for (mode, change), text in expected.items():
                M.FROZEN = mode
                z.edited = lambda name, uvs=False, change=change: change
                try:
                    run.guard(M, 'build')
                    raise AssertionError('no error for %s' % change)
                except ValueError as e:
                    assert text in str(e) and 'discard_edits=True' in str(e), str(e)
            z.edited = lambda name, uvs=False: None
            run.guard(M, 'build')
            assert run.frozen(M) is True and run.names(M)['frozen'] == 'Probe_Frozen'
            M.FROZEN = True
            try:
                run.capture_edits(M, {})
                raise AssertionError('capture_edits ran in the frozen mode')
            except ValueError as e:
                assert str(e) == 'capture_edits is for the parametric mode: in the frozen mode run freeze'
        finally:
            z.edited = saved
            objects.clear()


def test_the_operations_refuse_the_parametric_mode():
    with _runner()():
        run = importlib.import_module('lpk.run')
        model = os.path.join(ROOT, 'examples', 'mannequin', 'mannequin.py')
        calls = [lambda: run.transform(model, 'hand.L', translate=(0.01, 0, 0)), lambda: run.replace(model, 'head'),
                 lambda: run.decimate(model, 'hair', 0.5), lambda: run.subdivide(model, 'foot.L'),
                 lambda: run.smooth(model, 'trunk')]
        for call in calls:
            try:
                call()
                raise AssertionError('an operation ran in the parametric mode')
            except ValueError as e:
                assert str(e) == 'zone operations change the frozen mesh: freeze the model first (FROZEN = True)'



def test_the_uv_digest_reads_the_stored_float32_values():
    uv = np.array([[0.25, 0.5], [0.125, 1.0]])
    assert zones.uv_digest(uv) == zones.uv_digest(uv.astype(np.float32).ravel())
    moved = uv.copy()
    moved[1, 0] += 1e-4
    assert zones.uv_digest(moved) != zones.uv_digest(uv)


class _Mesh:
    def __init__(self, uv_layers=()):
        self.uv_layers = {k: object() for k in uv_layers}


def test_the_runner_wires_the_texture_modes():
    with _runner()():
        run = importlib.import_module('lpk.run')
        texture = importlib.import_module('lpk.stages.texture')
        z = importlib.import_module('lpk.stages.zones')
        order = [run.STAGES.index(s) for s in ('freeze', 'unfreeze_texture', 'build', 'unwrap', 'pack', 'bake',
                                               'freeze_texture', 'rig')]
        assert order == sorted(order), run.STAGES
        assert run.OPTIONS['discard_edits'] == ('build', 'bake')
        data = sys.modules['bpy'].data
        data.meshes, data.images = {}, {}
        M = types.SimpleNamespace(NAME='Probe', __name__='probe', TEXTURE_FROZEN=True)
        try:
            assert 'set FROZEN = True' in _raises(run.texture_frozen, M)
            assert 'freeze the model' in _raises(run.freeze_texture, M, {})
            M.FROZEN = True
            assert run.texture_frozen(M) and run.names(M)['atlas_frozen'] == 'Probe_AtlasFrozen'
            for stage in ('unwrap', 'pack'):
                msg = _raises(getattr(run, stage), M, {})
                assert msg == ('%s: the texture is frozen (TEXTURE_FROZEN = True): unwrap and pack would replace the '
                               'frozen UVs; run unfreeze_texture first' % stage), msg
            assert run.kept_uv(M, 'freeze') == texture.UV_LAYER
            M.TEXTURE_FROZEN = False
            assert run.kept_uv(M, 'freeze') is None and not run.texture_stored(M)
            data.meshes['Probe_Frozen'] = _Mesh([texture.UV_LAYER])
            assert run.texture_stored(M)
            msg = _raises(run.kept_uv, M, 'transform')
            assert msg.startswith('transform: ') and 'TEXTURE_FROZEN = True' in msg and 'unfreeze_texture' in msg
            data.meshes['Probe_Frozen'] = _Mesh()
            data.images['Probe_AtlasFrozen'] = object()
            assert run.texture_stored(M)
            data.images.clear()
            data.objects['Probe'] = types.SimpleNamespace(data=types.SimpleNamespace(uv_layers={texture.UV_LAYER: 0}))
            M.SOURCES, M.PALETTE = {'Belt': {'over': 1}}, {}
            assert "'over' is True or False" in _raises(run.bake, M, {})
            M.TEXTURE_FROZEN = True
            M.SOURCES = {'Belt': {'over': True}}
            assert 'run freeze_texture' in _raises(run.bake, M, {})
            saved = z.edited
            z.edited = lambda name, uvs=False: 'uv' if uvs else None
            try:
                msg = _raises(run.guard, M, 'build')
                assert "UVs were edited by hand" in msg and 'run freeze_texture' in msg and 'discard_edits' in msg
                M.TEXTURE_FROZEN = False
                run.guard(M, 'build')
            finally:
                z.edited = saved
            rep = run.unfreeze_texture(M, {})
            assert rep == {'removed': {'image': None, 'uv_layer': None}, 'lost': 'nothing: no frozen texture was stored',
                           'texture_mode': 'procedural'}, rep
        finally:
            data.objects.clear()
            del data.meshes, data.images


# A strip of four unit squares along x in z = 0, each split into two triangles (faces 2k and 2k + 1 of
# square k), laid out in UV at 0.05 per metre from (0.1, 0.1): one island.
STRIP_CO = np.array([[x, y, 0] for x in range(5) for y in (0, 1)], float)
STRIP_TRIS = [t for k in range(4) for t in ([2 * k, 2 * k + 2, 2 * k + 3], [2 * k, 2 * k + 3, 2 * k + 1])]
STRIP_LOOPS = (list(range(0, 24, 3)), [3] * 8, [i for t in STRIP_TRIS for i in t])
STRIP_UV = 0.1 + 0.05 * STRIP_CO[STRIP_LOOPS[2], :2]
SIZE = (256, 256)


def _faults(uv, parts, **kw):
    return zones.uv_faults(STRIP_CO, *STRIP_LOOPS, uv, parts, SIZE, **kw)


def test_uv_islands_join_faces_that_meet_in_uv_at_both_ends_of_an_edge():
    assert zones.uv_islands(*STRIP_LOOPS, STRIP_UV).tolist() == [0] * 8
    uv = STRIP_UV.copy()
    uv[12:24, 0] += 0.5
    assert zones.uv_islands(*STRIP_LOOPS, uv).tolist() == [0, 0, 0, 0, 1, 1, 1, 1], 'a cut between squares 1 and 2'
    uv = STRIP_UV.copy()
    uv[3 * 3 + 1] += 1e-7
    assert zones.uv_islands(*STRIP_LOOPS, uv).tolist() == [0] * 8, 'float rounding still meets'
    uv[3 * 3 + 1] += 1e-3
    assert zones.uv_islands(*STRIP_LOOPS, uv).tolist() == [0, 0, 1, 0, 1, 1, 1, 1], \
        'one end apart parts the strip at the diagonal of square 1, the only edge face 2 shares toward square 0'


def test_edges_list_their_faces_and_corners_in_order():
    edges = zones.edge_corners(*STRIP_LOOPS)
    assert [(a, b) for a, b, _ in edges] == sorted((a, b) for a, b, _ in edges)
    shared = {(a, b): g for a, b, g in edges}[(2, 3)]
    assert [f for f, _, _ in shared] == [0, 3], shared
    lv = STRIP_LOOPS[2]
    assert all(lv[la] == 2 and lv[lb] == 3 for _, la, lb in shared)
    nb = zones.face_neighbours(*STRIP_LOOPS)
    assert nb[0] == [1, 3] and nb[3] == [0, 2] and nb[7] == [4, 6], nb


def test_the_uv_check_finds_nothing_on_a_clean_layout_and_leaves_out_what_it_skips():
    parts = ['a'] * 4 + ['b'] * 4
    uv = STRIP_UV.copy()
    uv[12:24, 1] += 0.5
    f = _faults(uv, parts)
    assert not f['broken'].any() and f['checked'].all()
    assert np.allclose(f['texels_per_m'], 0.05 * 256) and np.allclose(f['ratio'], 1.0)
    rep = zones.uv_report(f, parts, SIZE)
    assert rep == {'size': [256, 256], 'faces': 8, 'broken': 0, 'texels_per_m': 12.8,
                   'skipped': {'own': 0, 'degenerate': 0}, 'parts': {}}, rep
    uv[0:3] = uv[0]
    f = _faults(uv, parts, skip={'a'})
    assert not f['broken'].any() and f['skipped'] == {'own': 4, 'degenerate': 0}
    assert _faults(uv, parts, min_area=0.6)['skipped'] == {'own': 0, 'degenerate': 8}


def test_the_uv_check_names_each_fault_by_part():
    parts = ['a'] * 4 + ['b'] * 4
    uv = STRIP_UV.copy()
    uv[12:24, 1] += 0.5
    uv[0:3] = uv[0]                                   # face 0: collapsed to a point
    uv[3:6, 0] -= 0.2                                 # face 1: off the atlas at u < 0
    uv[15:18] = uv[6:9]                               # face 5 of b laid over face 2 of a
    c = uv[21:24].mean(axis=0)
    uv[21:24] = c + (uv[21:24] - c) * 0.1             # face 7: a tenth of its size
    f = _faults(uv, parts)
    assert np.flatnonzero(f['zero']).tolist() == [0]
    assert np.flatnonzero(f['outside']).tolist() == [1]
    assert np.flatnonzero(f['overlap']).tolist() == [5], 'only the smaller island is read as on the other'
    assert np.flatnonzero(f['density']).tolist() == [7] and abs(f['ratio'][7] - 0.1) < 1e-6
    rep = zones.uv_report(f, parts, SIZE)
    assert rep['broken'] == 4 and list(rep['parts']) == ['a', 'b']
    assert rep['parts']['a'] == {'faces': 4, 'broken': [0, 1], 'zero': [0], 'outside': [1], 'overlap': [],
                                 'density': [], 'ratio': []}, rep['parts']['a']
    assert rep['parts']['b'] == {'faces': 4, 'broken': [5, 7], 'zero': [], 'outside': [], 'overlap': [5],
                                 'density': [7], 'ratio': [0.1]}, rep['parts']['b']
    same = _faults(uv, ['a'] * 8)
    assert not same['overlap'].any(), 'an overlap within one part is not read'


def test_two_triangles_interpenetrate_by_their_least_projection_overlap():
    a = np.array([[[0, 0], [4, 0], [0, 4]]], float)
    assert zones.triangle_depths(a, a + [10, 0])[0] < 0
    assert zones.triangle_depths(a, a + [4, 0])[0] == 0, 'touching at a corner'
    assert abs(zones.triangle_depths(a, a + [3, 0])[0] - 1 / np.sqrt(2)) < 1e-9
    point = np.array([[[1, 1], [1, 1], [1, 1]]], float)
    assert zones.triangle_depths(a, point)[0] == 0, 'a point has no depth'


def test_the_repair_density_is_the_parts_intact_median():
    parts = ['a'] * 4 + ['b'] * 4
    uv = STRIP_UV.copy()
    uv[12:24, 1] += 0.5
    uv[15:18] *= 2.0
    f = _faults(uv, parts)
    d = zones.part_densities(f, parts, [5])
    assert list(d) == ['b'] and abs(d['b'] - 12.8) < 1e-9, d
    d = zones.part_densities(f, ['a'] * 7 + ['c'], [7])
    assert list(d) == ['c'] and abs(d['c'] - 12.8) < 1e-9, 'a part of only broken faces takes the mesh median'
    assert 'texel density' in _raises(zones.part_densities, f, parts, list(range(8)))


def test_charts_grow_over_shared_edges_within_a_part_and_a_normal_cone():
    normals = np.array([[0, 0, 1.0]] * 6 + [[0, 1.0, 0]] * 2)
    nb = zones.face_neighbours(*STRIP_LOOPS)
    parts = ['a'] * 8
    assert zones.uv_charts([7, 0, 1, 3, 2, 6], normals, nb, parts) == [[0, 1, 2, 3], [6, 7]]
    assert zones.uv_charts([0, 1, 2, 3], normals, nb, ['a', 'a', 'b', 'b'] + ['a'] * 4) == [[0, 1], [2, 3]]
    flat = zones.chart_flat([0, 1], STRIP_CO, zones.polygons(*STRIP_LOOPS), normals[0])
    assert np.allclose(flat[0], [[0, 0], [1, 0], [1, 1]]) and np.allclose(flat[1], [[0, 0], [1, 1], [0, 1]])


def test_the_repair_layout_places_new_islands_in_free_space_only():
    parts = ['a'] * 8
    occupied = np.zeros((64, 64), bool)
    occupied[:20, :] = True
    occupied[20:, :30] = True
    rep = zones.uv_repair_layout(STRIP_CO, *STRIP_LOOPS, [2, 3, 7], parts, {'a': 10.0}, occupied, (64, 64), 2)
    assert rep['placed'] and [c['faces'] for c in rep['charts']] == [[2, 3], [7]]
    cells = [c['cell'] for c in rep['charts']]
    assert cells == [[30, 20, 15, 15], [30, 35, 20, 13]], 'each cell its extent plus one and two margins'
    assert rep['cells'].sum() == 15 * 15 + 20 * 13 and not (rep['cells'] & occupied).any()
    assert sorted(rep['uv']) == [2, 3, 7]
    corners = np.concatenate([rep['uv'][f] for f in (2, 3)]) * 64
    assert np.allclose(corners.min(axis=0), [30 + 2.5, 20 + 2.5]) and np.allclose(np.ptp(corners, axis=0), 10.0)
    again = zones.uv_repair_layout(STRIP_CO, *STRIP_LOOPS, [2, 3, 7], parts, {'a': 10.0}, occupied, (64, 64), 2)
    assert all(np.array_equal(rep['uv'][f], again['uv'][f]) for f in rep['uv']), 'deterministic'
    full = zones.uv_repair_layout(STRIP_CO, *STRIP_LOOPS, [2, 3, 7], parts, {'a': 10.0}, occupied, (64, 64), 20)
    assert not full['placed'] and all(c['cell'] is None for c in full['charts']) and full['uv'] == {}


def test_the_runner_wires_the_uv_calls():
    with _runner()():
        run = importlib.import_module('lpk.run')
        model = os.path.join(ROOT, 'examples', 'mannequin', 'mannequin.py')
        msg = _raises(run.repair_uvs, model)
        assert msg.startswith('repair_uvs: ') and 'TEXTURE_FROZEN = True' in msg, msg
        assert 'run build first' in _raises(run.check_uvs, model)
        data = sys.modules['bpy'].data
        data.images = {}
        M = types.SimpleNamespace(NAME='Probe', __name__='probe', ATLAS=(256, {'Body': 1.0}))
        try:
            assert run.uv_size(M) == (256, 256)
            data.images['Probe_Atlas'] = types.SimpleNamespace(size=(512, 256))
            assert run.uv_size(M) == (512, 256)
            data.images['Probe_AtlasFrozen'] = types.SimpleNamespace(size=(128, 128))
            assert run.uv_size(M) == (128, 128), 'the frozen atlas first'
        finally:
            del data.images


def _raises(fn, *args):
    try:
        fn(*args)
    except ValueError as e:
        return str(e)
    raise AssertionError('no ValueError from %s' % getattr(fn, '__name__', fn))


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
