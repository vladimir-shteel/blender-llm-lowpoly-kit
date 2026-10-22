"""Host tests of the stage runner (lpk.run) and the worked example (examples/mannequin/mannequin.py), with
bpy, bmesh and mathutils replaced by stand-ins (tests/blender_stand_ins.py): the stage list and the
options are checked before anything runs, the stages run in the order of STAGES with 'pack' repeated
and the first pack's rescale following the unwrap, the measurements are read only for the stages that
need them, a stage refuses a scene without what an earlier stage makes, the bake takes the model's GRIT; the example's measurements, blocks, bones, seams and its whole build_mesh run on the host.

python tests/test_run.py"""
import contextlib
import importlib
import os
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tests'))

import blender_stand_ins  # noqa: E402

MODEL = os.path.join(ROOT, 'examples', 'mannequin', 'mannequin.py')


@contextlib.contextmanager
def stand_ins():
    """blender_stand_ins.stand_ins() plus what lpk.stages.rig, lpk.stages.blocks and lpk.run import besides
    them (addon_utils, mathutils.kdtree, mathutils.Euler, bpy.data); sys.modules is restored afterwards."""
    extra = ('addon_utils', 'mathutils.kdtree')
    saved = {k: sys.modules.pop(k) for k in extra if k in sys.modules}
    with blender_stand_ins.stand_ins():
        mathutils = sys.modules['mathutils']
        kdtree = types.ModuleType('mathutils.kdtree')
        mathutils.kdtree, mathutils.Euler = kdtree, type('Euler', (), {})
        mathutils.geometry.intersect_point_line = lambda *a: None
        sys.modules['bpy'].data = types.SimpleNamespace(objects={})
        sys.modules.update({'addon_utils': types.ModuleType('addon_utils'), 'mathutils.kdtree': kdtree})
        try:
            yield
        finally:
            for k in extra:
                sys.modules.pop(k, None)
    sys.modules.update(saved)


def _raises(exc, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except exc as e:
        return str(e)
    raise AssertionError('no %s from %s' % (exc.__name__, fn))


def test_stages_and_options_are_checked_before_anything_runs():
    with stand_ins():
        run = importlib.import_module('lpk.run')
        assert 'bake' in _raises(ValueError, run.check_stages, ('build', 'bake', 'bake'))
        assert 'paint' in _raises(ValueError, run.check_stages, ('paint',))
        run.check_stages(('pack', 'pack', 'pack'))
        assert 'speed' in _raises(ValueError, run.model, MODEL, ('build',), speed=2)
        assert set(run.RUNNERS) | {'pack'} == set(run.STAGES)
        assert set(run.MEASURED) <= set(run.STAGES)


def _recording(run, calls):
    def stage(name):
        def fn(M, P, **kw):
            calls.append((name, P is not None, kw))
            return name
        return fn
    runners = {k: stage(k) for k in run.RUNNERS}
    def pack(M, P, rescale=True):
        calls.append(('pack', P is not None, {'rescale': rescale}))
        return {'face_side_change': changes.pop(0) if changes else 5.0}
    changes = []
    calls.changes = changes
    return runners, pack


class _Calls(list):
    pass


def test_stages_run_in_table_order_with_pack_repeated_and_measured_only_when_needed():
    with stand_ins():
        run = importlib.import_module('lpk.run')
        calls = _Calls()
        runners, pack = _recording(run, calls)
        saved = run.RUNNERS, run.pack
        run.RUNNERS, run.pack = runners, pack
        try:
            report = run.model(MODEL, ('pack', 'unwrap', 'build', 'pack'))
            assert [c[0] for c in calls] == ['build', 'unwrap', 'pack', 'pack']
            assert [r['settled'] for r in report['pack']] == [False, False] and report['build'] == 'build'
            assert [c[2]['rescale'] for c in calls[2:]] == [False, True], 'the pack after an unwrap never rescales'
            calls.clear()
            run.model(MODEL, ('pack',), rescale=False)
            run.model(MODEL, ('pack',))
            assert [c[2]['rescale'] for c in calls] == [False, True]
            calls.clear()
            calls.changes.extend([0.4, 3.0, 0.5, 0.2])
            report = run.model(MODEL, ('unwrap',) + ('pack',) * 5)
            assert [r['face_side_change'] for r in report['pack']] == [0.4, 3.0, 0.5], \
                'the unscaled first pack never settles; the packs stop after the first that does'
            calls.changes.clear()
            calls.clear()
            run.model(MODEL, ('pose_test', 'export'))
            assert [c[1] for c in calls] == [False, False], 'no measurements without a stage that reads them'
            calls.clear()
            run.model(MODEL, ('rig',), backend='distance')
            assert calls == [('rig', True, {'backend': 'distance'})]
        finally:
            run.RUNNERS, run.pack = saved


def test_a_missing_model_attribute_is_named():
    with stand_ins():
        run = importlib.import_module('lpk.run')
        M = types.SimpleNamespace(NAME='Probe', __name__='probe')
        assert 'Probe defines no TEST_POSE' in _raises(AttributeError, run.need, M, 'TEST_POSE')


def _model():
    run = importlib.import_module('lpk.run')
    M = run.load(MODEL)
    P = M.props()
    P['edits'] = {}
    return run, M, P


def test_the_example_measures_blocks_and_rigs_on_the_host():
    with stand_ins():
        run, M, P = _model()
        assert P['head_half'][2] > P['head_half'][0] > 0 and 0.5 < P['arm_rad'] < 0.8
        blocks = M.blocks(P)
        kinds = importlib.import_module('lpk.stages.blocks').KINDS
        assert all(kind in kinds for kind, _, _, _ in blocks)
        assert all(colour in M.PALETTE for _, _, colour, _ in blocks)
        rig = importlib.import_module('lpk.stages.rig')
        table = rig.bone_table(M.SKELETON, M.bones(P))
        assert len(table) == 27 and {b['name'] for b in table} >= {'Index.L', 'Thumb.R', 'Toes.L'}
        assert sorted(M.seams(P)) == ['cuts', 'panels']
        skeletons = importlib.import_module('lpk.skeletons')
        assert [j[:2] for j in skeletons.sided(M.JOINS, M.SKELETON)] == [
            ('trunk', 'arm.L'), ('trunk', 'arm.R'), ('trunk', 'leg.L'), ('trunk', 'leg.R')]


def test_the_examples_build_runs_on_the_host_and_records_its_edit_references():
    with stand_ins():
        run, M, P = _model()
        body, sources = M.build_mesh(P)
        assert body.parts == ['', 'head', 'ear.L', 'ear.R', 'hair', 'trunk', 'arm.L', 'leg.L', 'arm.R', 'leg.R',
                              'hand.L', 'hand.R', 'foot.L', 'foot.R']
        assert set(sources) == set(M.SOURCES) == {'Face', 'Trousers'} and len(sources['Face'].bm.faces) > 0
        assert all(len(f.verts) == 3 for f in body.bm.faces), 'every part is triangulated as it is finished'
        edits = importlib.import_module('lpk.core.edits')
        mirrored = {'ear.R', 'foot.R'}
        assert set(P[edits.REFS]) == set(body.parts[1:]) - mirrored
        again = M.props()
        again['edits'] = {}
        b2, _ = M.build_mesh(again)
        assert [tuple(v.co) for v in b2.bm.verts] == [tuple(v.co) for v in body.bm.verts], 'the build is deterministic'


def test_reference_corners_follow_the_views_facing():
    with stand_ins():
        run = importlib.import_module('lpk.run')
        views = importlib.import_module('lpk.core.views')
        cal = views.Calib(1.75, 100, 900, (700, 1000))
        plane, low, high = run.corners(cal, 'front', (700, 1000), 350)
        k = 1.75 / 800
        assert plane == 'front' and low == (-350 * k, 0.0, -100 * k) and high == (350 * k, 0.0, 900 * k)
        _, low, high = run.corners(cal, 'back', (700, 1000), 300)
        assert low[0] == 300 * k and high[0] == -400 * k, 'a back view runs its pixels toward -X'
        cal.zero_px, cal.facing = 250, 'left'
        plane, low, high = run.corners(cal, 'left', (500, 1000))
        assert plane == 'side' and low[1] == -250 * k and high[1] == 250 * k, 'facing left: forward (-Y) is left'
        cal.facing = 'right'
        assert run.corners(cal, 'right', (500, 1000))[1][1] == 250 * k


def test_block_kinds_lay_their_parts():
    with stand_ins():
        blocks = importlib.import_module('lpk.stages.blocks')
        builder = importlib.import_module('lpk.core.builder')
        sections = importlib.import_module('lpk.core.sections')
        b = builder.Builder({'grey': (0.5, 0.5, 0.5)})
        blocks.BUILDERS['wedge'](b, 'snout', 'grey', (0, -0.1, 1.6), (0, -0.2, 1.58), (0.04, 0.03), (0.01, 0.01))
        blocks.BUILDERS['ellipsoid'](b, 'head', 'grey', (0, 0, 1.6), (0.08, 0.1, 0.12))
        blocks.BUILDERS['tube'](b, 'tail', 'grey', [(0, 0.1, 1.0), (0, 0.3, 0.9)], [0.03, 0.01])
        blocks.BUILDERS['loft'](b, 'arm', 'grey', [sections.Section('a', (0.2, 0, 1.4), (0.05, 0.04)),
                                                   sections.Section('b', (0.4, 0, 1.1), (0.03, 0.03))], (0, 1, 0))
        assert b.parts == ['', 'snout', 'head', 'tail', 'arm']
        counts = {}
        for v in b.bm.verts:
            counts[b.parts[v[b.vpart]]] = counts.get(b.parts[v[b.vpart]], 0) + 1
        assert counts == {'snout': 8, 'head': 8 * (blocks.ELLIPSOID_RINGS - 1) + 2, 'tail': 16, 'arm': 16}
        assert set(blocks.BUILDERS) == set(blocks.KINDS)


def test_references_stand_in_rows_clear_of_the_model_and_of_each_other():
    with stand_ins():
        run = importlib.import_module('lpk.run')
        gap = run.REFERENCE_GAP
        placed = {'front': ('front', (-0.76, 0.0, -0.2), (0.76, 0.0, 2.0)),
                  'back': ('front', (0.76, 0.0, -0.2), (-0.76, 0.0, 2.0)),
                  'side': ('side', (0.0, -0.5, -0.2), (0.0, 0.5, 2.0))}
        shifts = run.layout(placed)
        front, back = shifts['front'][0], shifts['back'][0]
        assert abs((0.76 + front) - (-0.76 - gap)) < 1e-9, 'the first image ends a gap past the widest reach'
        assert abs((0.76 + back) - (-0.76 + front - gap)) < 1e-9, 'the next one a gap past the first'
        assert shifts['side'] == (0.0, 0.5 + gap + 0.5, 0.0) and shifts['front'][1:] == (0.0, 0.0)


def test_a_stage_without_what_an_earlier_stage_makes_names_the_stage_to_run_first():
    with stand_ins():
        run = importlib.import_module('lpk.run')
        texture = importlib.import_module('lpk.stages.texture')
        objects = sys.modules['bpy'].data.objects
        M = types.SimpleNamespace(NAME='Probe', __name__='probe', __lpk_folder__=ROOT)
        P = {'edits': {}}
        for stage in ('unwrap', 'pack', 'bake', 'rig', 'preview', 'export'):
            msg = _raises(ValueError, run.pack if stage == 'pack' else run.RUNNERS[stage], M, P)
            assert msg == '%s: no body Probe in the scene: run build first' % stage, msg
        objects['Probe'] = types.SimpleNamespace(data=types.SimpleNamespace(uv_layers={}))
        for stage in ('pack', 'bake'):
            msg = _raises(ValueError, run.pack if stage == 'pack' else run.bake, M, P)
            assert msg == '%s: the body Probe has no atlas UV layer %s: run unwrap first' % (stage, texture.UV_LAYER)
        for stage in ('pose_test', 'pose_rest', 'export'):
            assert _raises(ValueError, run.RUNNERS[stage], M, P) == \
                '%s: no rig Probe_Rig in the scene: run rig first' % stage
        objects['Probe'].data.uv_layers[texture.UV_LAYER] = object()
        objects['Probe_Rig'] = object()
        found = run.require(M, 'export', 'uv', 'rig')
        assert found == {'body': objects['Probe'], 'uv': objects['Probe'], 'rig': objects['Probe_Rig']}
        objects.clear()


def test_the_bake_stage_passes_the_models_grit():
    with stand_ins(), tempfile.TemporaryDirectory() as folder:
        run = importlib.import_module('lpk.run')
        texture = importlib.import_module('lpk.stages.texture')
        objects = sys.modules['bpy'].data.objects
        objects['Probe'] = types.SimpleNamespace(data=types.SimpleNamespace(uv_layers={texture.UV_LAYER: None}))
        M = types.SimpleNamespace(NAME='Probe', __name__='probe', __lpk_folder__=folder, PALETTE={}, ATLAS=(64, {'A': 1}),
                                  sheet_of=lambda colour, part: 'A')
        seen = []
        saved = texture.bake, texture.stamp_image
        texture.bake = lambda *a, **k: seen.append(k['grit'])
        texture.stamp_image = lambda name: None
        try:
            run.bake(M, {})
            M.GRIT = [0.5, 0.4, 0.3]
            run.bake(M, {})
            M.GRIT = texture.GRIT
            run.bake(M, {})
            M.GRIT = (0.5, 2.0, 0.3)
            assert 'GRIT' in _raises(ValueError, run.bake, M, {})
        finally:
            texture.bake, texture.stamp_image = saved
            objects.clear()
        assert seen == [None, (0.5, 0.4, 0.3), tuple(texture.GRIT)], seen


def test_a_model_rewritten_at_once_with_the_same_length_loads_its_new_code():
    import shutil, tempfile
    with stand_ins():
        run = importlib.import_module('lpk.run')
        d = tempfile.mkdtemp()
        try:
            path = os.path.join(d, 'probe.py')
            for value in ('0.006', '0.014'):
                with open(path, 'w', encoding='utf-8', newline='\n') as f:
                    f.write('NAME = "Probe"\nNOSE = %s\n' % value)
                os.utime(path, (1000000000, 1000000000))     # the same second both times
                assert run.load(path).NOSE == float(value), value
        finally:
            shutil.rmtree(d)


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
