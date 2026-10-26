"""Host tests of the stage kernels the texture, rig and export rows call (lpk.stages.texture, preview, rig,
export) on stand-ins of bpy, bmesh and mathutils (tests/blender_stand_ins.py): the unwrap entry's choice of
kernel, the fold check weighing a face of no area as nothing, the pack cache restoring each pack from the UVs and settings it starts from; the bake's sources and
its recolour rewriting only Col from the palette; the variant registries bound to their implementations; the effective influence limit; the smoothing pairs
taken from the build's join records and their zones; the export output naming and per-output settings;
the skeleton's bones, parents and rolls and the skin's part binding read from the skeleton template; the
skin row's inner steps, one per call under a zero budget; the budget rows of the bones. Nothing here unwraps, bakes, skins or exports: Blender checks those.

python tests/test_stage_rows.py"""
import ast
import contextlib
import copy
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import types
from types import SimpleNamespace as NS

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import blender_stand_ins  # noqa: E402
from lpk import profiles, skeletons  # noqa: E402

KERNELS = ('lpk.stages.texture', 'lpk.stages.preview', 'lpk.stages.rig', 'lpk.stages.export', 'lpk.stages.pose')


@contextlib.contextmanager
def stand_ins():
    """blender_stand_ins.stand_ins() plus the modules lpk.stages.rig imports besides them (addon_utils,
    mathutils.kdtree, mathutils.geometry); sys.modules is restored afterwards."""
    extra = ('addon_utils', 'mathutils.kdtree', 'mathutils.geometry')
    saved = {k: sys.modules.pop(k) for k in extra if k in sys.modules}
    with blender_stand_ins.stand_ins():
        mathutils = sys.modules['mathutils']
        kdtree = types.ModuleType('mathutils.kdtree')
        geometry = types.ModuleType('mathutils.geometry')
        geometry.intersect_point_line = lambda *a: None
        mathutils.kdtree, mathutils.geometry = kdtree, geometry
        sys.modules.update({'addon_utils': types.ModuleType('addon_utils'), 'mathutils.kdtree': kdtree,
                            'mathutils.geometry': geometry})
        try:
            yield
        finally:
            for k in extra:
                sys.modules.pop(k, None)
    sys.modules.update(saved)


with stand_ins():
    texture, preview, rig, export, pose = (importlib.import_module(m) for m in KERNELS)


def _raises(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except ValueError as e:
        return str(e)
    raise AssertionError('no ValueError from %s' % getattr(fn, '__name__', fn))


@contextlib.contextmanager
def _patched(module, **values):
    old = {k: getattr(module, k) for k in values}
    for k, v in values.items():
        setattr(module, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(module, k, v)


# -- variant registries -------------------------------------------------------------------------------

def test_variant_registries_are_bound_to_their_implementations():
    assert tuple(texture.FINAL_MATERIALS) == texture.MATERIALS
    assert tuple(rig.WEIGHTS) == rig.BACKENDS == ('vhd', 'heat_proxy', 'heat', 'distance'), 'auto tries them in order'
    assert all(callable(fn) and callable(usable) for fn, usable in rig.WEIGHTS.values())
    assert all(callable(fn) for fn in texture.FINAL_MATERIALS.values())
    for name, preset in preview.PRESETS.items():
        assert preview.preset_problems(name) == [] and set(preset) == {'light', 'ramp', 'tones'}


def test_no_variant_name_is_compared_outside_its_implementation():
    names = set(texture.MATERIALS + tuple(preview.PRESETS) + rig.BACKENDS + texture.PACK_SHAPES
                + texture.PACK_MARGINS)
    found = []
    for path in sorted((ROOT / 'lpk').rglob('*.py')):
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, ast.Compare):
                found += ['%s:%d %s' % (path.relative_to(ROOT).as_posix(), node.lineno, c.value)
                          for c in [node.left] + node.comparators
                          if isinstance(c, ast.Constant) and isinstance(c.value, str) and c.value in names]
    assert not found, found


# -- unwrap and pack: the entry's dispatch, the pack cache ----------------------------------------------

def _sheet(colour, part):
    return 'Body'


class _Clock:
    """A clock that advances one second per reading."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        self.t += 1.0
        return self.t


def test_unwrap_takes_the_seamed_unwrap_when_any_seam_is_given():
    calls = []

    def kernel(kind):
        def run(obj_name, sheet_of, atlas, **kw):
            calls.append((kind, sheet_of('skin', 'eye.L'), sheet_of('skin', 'head'), kw))
            return {'face_tris': 0, 'face_angle': None}
        return run

    with _patched(texture, check_groups=lambda *a: calls.append(('groups',) + a[2:]),
                  unwrap_color_atlas=kernel('smart'), unwrap_seamed_atlas=kernel('seamed')):
        assert texture.unwrap('Probe', _sheet, (256, {'Gear': 0.5, 'Body': 1.0}), own={'eye.L': 'Eyes'}) == {
            'face_tris': 0, 'face_angle': None}
        texture.unwrap('Probe', _sheet, (256, {'Body': 1.0}), hard={'arm.L': 50}, default_group='Body')
    assert calls[0] == ('groups', {'Gear': 0.5, 'Body': 1.0}, {'eye.L': 'Eyes'})
    kind, own, plain, kw = calls[1]
    assert (kind, own, plain) == ('smart', texture.OWN_PREFIX + 'Eyes', 'Body'), 'own parts take their own groups'
    assert kw['default_group'] == 'Gear', 'the first group without default_group'
    kind, _, _, kw = calls[3]
    assert kind == 'seamed' and (kw['cut_sides'], kw['panels'], kw['hard']) == (None, None, {'arm.L': 50})


def test_the_parts_of_own_take_groups_and_slots_of_their_materials():
    own = {'eye.L': 'Eyes', 'tooth': 'Enamel', 'eye.R': 'Eyes'}
    sheet = texture._own_sheet(_sheet, own)
    assert [sheet('skin', p) for p in ('eye.L', 'eye.R', 'tooth', 'head')] == [
        texture.OWN_PREFIX + 'Eyes', texture.OWN_PREFIX + 'Eyes', texture.OWN_PREFIX + 'Enamel', 'Body']
    assert texture.own_materials(own) == ['Eyes', 'Enamel'], 'each material once, in the order of its first part'


class _PackScene:
    """The body's UVs as the patched pack kernel leaves them: each pack appends to the UV bytes and gives the
    next area of AREAS."""
    AREAS = (0.10, 0.06, 0.055, 0.0545)

    def __init__(self):
        self.uv, self.packs = b'unwrap', 0

    def pack(self, obj_name, sheet_of, face_part, face_pred, face_area, face_texels, strips, size, rescale, margin,
             shape_method, margin_method):
        self.packs += 1
        self.uv += b'|pack%d' % self.packs
        return {'face_area_before': None, 'face_area': self.AREAS[self.packs - 1], 'face_span': 100.0,
                'face_side_change': None}

    def kernels(self):
        return _patched(texture, _pack=self.pack, uv_bytes=lambda name: self.uv,
                        set_uv_bytes=lambda name, raw: setattr(self, 'uv', raw),
                        unwrap_key=lambda name, part, pred: hashlib.sha256(self.uv).hexdigest())


def _pack_chain(scene, cache, n=3, **kw):
    with scene.kernels():
        return [texture.pack_step('Probe', _sheet, (512, {'Body': 1.0}), rescale=i > 0, cache=cache, **kw)
                for i in range(n)]


def test_pack_step_restores_each_cached_pack_byte_for_byte():
    with tempfile.TemporaryDirectory() as tmp:
        cache = Path(tmp) / 'out' / 'Probe.pack.json'
        first = _PackScene()
        packed = _pack_chain(first, cache)
        assert first.packs == 3 and [r['cached'] for r in packed] == [False] * 3
        assert [r['face_area'] for r in packed] == list(_PackScene.AREAS[:3])
        again = _PackScene()
        restored = _pack_chain(again, cache)
        assert again.packs == 0 and again.uv == first.uv, 'the cached UVs, byte for byte, without packing'
        assert [dict(r, cached=False) for r in restored] == packed and all(r['cached'] for r in restored)
        other = _PackScene()
        _pack_chain(other, cache, margin=0.004)
        assert other.packs == 3, 'another pack setting is another pack'
        raw = cache.read_bytes()
        assert raw.endswith(b'}\n') and b'\r' not in raw
        assert raw.decode('utf-8') == json.dumps(json.loads(raw), sort_keys=True, indent=1) + '\n'
        _pack_chain(_PackScene(), None)
        assert cache.read_bytes() == raw, 'without a cache path nothing is read or written'


def test_pack_key_holds_the_unwrap_and_every_setting():
    settings = {'face_area': None, 'face_texels': 400.0, 'size': 512, 'margin': 0.006, 'rescale': True}
    base = texture.pack_key('u', settings)
    assert base == texture.pack_key('u', dict(settings)) and len(base) == 64
    others = [texture.pack_key('v', settings)] + [texture.pack_key('u', dict(settings, **{k: v})) for k, v in
                                                  (('face_texels', 300.0), ('size', 1024), ('margin', 0.004),
                                                   ('rescale', False))]
    assert len(set(others + [base])) == len(others) + 1, 'each input changes the key'


def test_pack_cache_entries_round_trip_and_refuse_what_they_cannot_restore():
    report = {'face_area_before': 0.1, 'face_area': 0.06, 'face_span': 100.0, 'face_side_change': 22.5}
    entries = []
    for i in range(texture.PACK_CACHE_ENTRIES + 2):
        entries = texture.kept_entries(entries, 'k%d' % i, report, b'uv%d' % i)
    assert [e['key'] for e in entries] == ['k%d' % i for i in range(2, texture.PACK_CACHE_ENTRIES + 2)], \
        'the latest PACK_CACHE_ENTRIES stay'
    entries = texture.kept_entries(entries, 'k3', report, b'new')
    assert entries[-1]['key'] == 'k3' and [e['key'] for e in entries].count('k3') == 1, \
        'a pack replaces its older entry, last'
    assert texture.cached_pack(entries, 'k3') == {'report': report, 'uv': b'new'}
    assert texture.cached_pack(entries, 'missing') is None
    bad = copy.deepcopy(entries)
    bad[-1]['sha'] = '0' * 64
    assert texture.cached_pack(bad, 'k3') is None, 'UVs that do not match their digest'
    bad = copy.deepcopy(entries)
    bad[-1]['report'] = None
    assert texture.cached_pack(bad, 'k3') is None, 'a malformed report'
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'Probe.pack.json'
        assert texture.read_pack_cache(path) == []
        texture.write_pack_cache(path, entries)
        assert texture.read_pack_cache(path) == entries
        for text in ('not json', '[]', '{"entries": {}}'):
            path.write_text(text, encoding='utf-8')
            assert texture.read_pack_cache(path) == [], 'a file that is no pack cache is replaced'


# -- the bake: recolour, sources -----------------------------------------------------------------------

class _Data:
    """An attribute's or a collection's data with foreach_get and foreach_set over a flat array."""

    def __init__(self, values, width=1):
        self.values, self.width, self.writes = np.array(values, np.float64).ravel(), width, []

    def foreach_get(self, prop, out):
        out[:] = self.values

    def foreach_set(self, prop, data):
        self.writes.append(prop)
        self.values = np.array(data, np.float64)


class _Polygons(list):
    def __init__(self, starts, totals):
        super().__init__(range(len(starts)))
        self.data = {'loop_start': starts, 'loop_total': totals}

    def foreach_get(self, prop, out):
        out[:] = self.data[prop]


class _Mesh:
    def __init__(self, pal, starts, totals, col=True):
        n = int(max(s + t for s, t in zip(starts, totals)))
        self.polygons = _Polygons(starts, totals)
        self.attributes = {'pal': NS(data=_Data(pal)), 'part': NS(data=_Data([1] * n)),
                           'join_loop': NS(data=_Data([0] * n))}
        self.col = NS(domain='CORNER', data_type='FLOAT_COLOR', data=_Data(np.zeros(4 * n), 4))
        self.color_attributes = {'Col': self.col} if col else {}
        self.updated = 0

    def update(self):
        self.updated += 1


class _Object(dict):
    def __init__(self, mesh, palette):
        super().__init__(palette=list(palette), parts=['', 'body'])
        self.data = mesh


def test_corner_colours_follow_each_polygons_loops_and_the_builds_conversion():
    with stand_ins():
        from lpk.core.builder import srgb_to_linear
        colours = {'skin': (0.8, 0.6, 0.5), 'cloth': (0.2, 0.3, 0.6)}
        data = texture.corner_colours([1, 0], [3, 0], [4, 3], ['skin', 'cloth'], colours)
        lin = {k: np.array(srgb_to_linear(c), np.float32) for k, c in colours.items()}
        got = data.reshape(-1, 4)
        assert data.dtype == np.float32 and len(got) == 7
        assert all((got[i] == lin['skin']).all() for i in range(3)), 'polygon 1 holds loops 0-2'
        assert all((got[i] == lin['cloth']).all() for i in range(3, 7)), 'polygon 0 holds loops 3-6'
        assert 'run the build' in _raises(texture.corner_colours, [0], [0], [3], ['hair'], colours)


def test_recolour_rewrites_only_col_from_the_palette():
    with stand_ins():
        from lpk.core.builder import srgb_to_linear
        body = _Object(_Mesh([0, 1], [0, 3], [3, 3]), ['skin', 'cloth'])
        eyes = _Object(_Mesh([0], [0], [3]), ['cloth'])
        objects = {'Probe': body, 'Probe_Eyes': eyes}
        before = {k: {a: v.data.values.copy() for a, v in o.data.attributes.items()} for k, o in objects.items()}
        with _patched(texture, bpy=NS(data=NS(objects=objects))):
            colours = {'skin': (1.0, 0.0, 0.0), 'cloth': (0.0, 0.0, 1.0)}
            assert texture.recolour(['Probe', 'Probe_Eyes'], colours) == {'Probe': 6, 'Probe_Eyes': 3}
            for k, o in objects.items():
                assert o.data.col.data.writes == ['color'] and o.data.updated == 1
                for a, values in before[k].items():
                    assert (o.data.attributes[a].data.values == values).all() and o.data.attributes[a].data.writes == []
            got = body.data.col.data.values.reshape(-1, 4)
            assert (got[:3] == np.array(srgb_to_linear((1.0, 0.0, 0.0)), np.float32)).all()
            assert (got[3:] == np.array(srgb_to_linear((0.0, 0.0, 1.0)), np.float32)).all()
            body2 = _Object(_Mesh([0], [0], [3]), ['skin'])
            hairy = _Object(_Mesh([0], [0], [3]), ['hair'])
            objects.update(A=body2, B=hairy)
            assert 'hair' in _raises(texture.recolour, ['A', 'B'], colours)
            assert body2.data.col.data.writes == [], 'nothing changes before every object is checked'
            objects['C'] = _Object(_Mesh([0], [0], [3], col=False), ['skin'])
            assert 'no Col' in _raises(texture.recolour, ['C'], colours)


def test_source_specs_take_the_bake_order_and_the_default_rays():
    objects = {'Probe_Eyes': object(), 'Probe_Belt': object()}
    with _patched(texture, bpy=NS(data=NS(objects=objects))):
        specs = texture.source_specs([{'object': 'Probe_Belt', 'over': True},
                                      {'object': 'Probe_Eyes', 'mask': ['head'], 'ray': 0.05}])
        assert specs == [{'object': 'Probe_Belt', 'mask': None, 'cage': texture.BAKE_CAGE, 'ray': texture.BAKE_RAY,
                          'over': True},
                         {'object': 'Probe_Eyes', 'mask': ('head',), 'cage': texture.BAKE_CAGE, 'ray': 0.05,
                          'over': False}]
        assert 'Probe_Cape' in _raises(texture.source_specs, [{'object': 'Probe_Cape'}])


# -- the rig: the bone table from the joints and the template ------------------------------------------

def _joints(names):
    """A (head, tail) pair per bone, distinct and not degenerate."""
    return {n: ((0.0, 0.0, 0.1 * i), (0.0, 0.0, 0.1 * i + 0.05)) for i, n in enumerate(names)}


def test_bone_table_takes_parents_connections_and_rolls_from_the_template():
    plain = [b['name'] for b in skeletons.bones_for('biped')]
    table = rig.bone_table('biped', _joints(plain))
    assert [b['name'] for b in table] == plain and 'Tail.1' not in plain and 'Index.L' not in plain
    listed = {b['name']: b for b in skeletons.load('biped')['bones']}
    for b in table:
        assert (b['parent'], b['connect']) == (listed[b['name']]['parent'], listed[b['name']]['connect'])
        assert b['roll'] == (0.0, -1.0, 0.0) and isinstance(b['head'], tuple) and b['deform'] is True
    assert set(table[0]) == {'name', 'head', 'tail', 'parent', 'connect', 'roll', 'deform'}
    names = [b['name'] for b in skeletons.bones_for('biped', {'tail': 8, 'hands': 'mitten'})]
    table = {b['name']: b for b in rig.bone_table('biped', _joints(reversed(names)))}
    assert list(table) == names, 'the template order, whatever the order of the joints'
    assert table['Tail.1']['parent'] == 'Hips' and not table['Tail.1']['connect']
    assert (table['Tail.8']['parent'], table['Tail.8']['connect']) == ('Tail.7', True), 'the chain goes on'
    assert table['Tail.8']['roll'] == (0.0, 0.0, 1.0) and table['Index.R']['parent'] == 'Hand.R'
    assert list(table).index('Tail.8') < list(table).index('Index.L'), 'chain bones follow their chain'
    light = [b['name'] for b in skeletons.bones_for('biped', {'neck': 'none', 'shoulders': 'none', 'toes': 'none'})]
    table = {b['name']: b for b in rig.bone_table('biped', _joints(light))}
    assert len(table) == 16, 'joints without the neck, the clavicles and the toes give the light rig'
    assert (table['Head']['parent'], table['Head']['connect']) == ('Chest', False)
    assert (table['UpperArm.R']['parent'], table['UpperArm.R']['connect']) == ('Chest', False)


def test_bone_table_refuses_joints_the_template_does_not_give():
    plain = [b['name'] for b in skeletons.bones_for('biped')]
    msg = _raises(rig.bone_table, 'biped', dict(_joints(plain), Wing=((0, 0, 0), (1, 0, 0))))
    assert "has no bone 'Wing'" in msg and 'extra_bones' in msg
    msg = _raises(rig.bone_table, 'biped', dict(_joints(plain), **{'Index.L': ((0, 0, 0), (1, 0, 0))}))
    assert 'no choice' in msg, 'a mitten hand has all three fingers on both sides'
    assert 'gap' in _raises(rig.bone_table, 'biped', _joints(plain + ['Tail.1', 'Tail.3']))
    short = {k: v for k, v in _joints(plain).items() if k != 'Hand.L'}
    assert 'lacks the required bones Hand.L' in _raises(rig.bone_table, 'biped', short)
    flat = dict(_joints(plain), Head=((0, 0, 1), (0, 0, 1)))
    assert 'one point' in _raises(rig.bone_table, 'biped', flat)


def test_bone_table_adds_the_models_bones_after_the_templates():
    plain = [b['name'] for b in skeletons.bones_for('biped')]
    at = lambda z: ((0.0, 0.1, z), (0.0, 0.1, z + 0.05))
    extra = {'Ear.L': dict(zip(('head', 'tail'), at(2.0)), parent='Head'),
             'Tip.L': dict(zip(('head', 'tail'), at(2.1)), parent='Ear.L', roll=(1, 0, 0)),
             'Socket': dict(zip(('head', 'tail'), at(2.2)), parent='Hand.R', deform=False),
             'Root': dict(zip(('head', 'tail'), at(2.3)), parent=None)}
    table = rig.bone_table('biped', _joints(plain), extra)
    assert [b['name'] for b in table] == plain + list(extra), 'template bones first, then the model bones in order'
    by = {b['name']: b for b in table}
    assert (by['Ear.L']['parent'], by['Ear.L']['connect'], by['Ear.L']['deform']) == ('Head', False, True)
    assert by['Ear.L']['roll'] == (0.0, -1.0, 0.0), "no role: the roll rule's default"
    assert by['Tip.L']['parent'] == 'Ear.L' and by['Tip.L']['roll'] == (1.0, 0.0, 0.0)
    assert by['Socket']['deform'] is False and by['Root']['parent'] is None
    assert by['Root']['head'] == (0.0, 0.1, 2.3)


def test_bone_table_refuses_model_bones_the_rig_cannot_hold():
    plain = _joints([b['name'] for b in skeletons.bones_for('biped')])
    bone = lambda parent, **more: dict(head=(0, 0, 3), tail=(0, 0, 3.1), parent=parent, **more)
    for name, spec, needle in (
            ('Head', bone('Neck'), "template 'biped' has a bone 'Head'"),
            ('Tail.9', bone('Hips'), "template 'biped' has a bone 'Tail.9'"),
            ('Ear', bone('Index.L'), "the parent 'Index.L' is no bone of the rig"),
            ('Ear', bone('Horn'), "the parent 'Horn' is no bone of the rig"),
            ('Ear', bone('Head', colour='red'), 'optionally roll, deform'),
            ('Ear', dict(head=(0, 0, 3), tail=(0, 0, 3), parent='Head'), 'one point')):
        msg = _raises(rig.bone_table, 'biped', plain, {name: spec})
        assert needle in msg and repr(name) in msg, msg
    later = {'Tip': bone('Ear'), 'Ear': bone('Head')}
    assert "the parent 'Ear' is no bone of the rig" in _raises(rig.bone_table, 'biped', plain, later)


# -- the rig: the zones of the joins ---------------------------------------------------------------------

class _Edges(list):
    pass


def _zone_mesh():
    """A trunk ring 0-3 (vertices 1 and 2 on the join loop) under an arm ring 4-5 and a hand vertex 6; the
    part arm.R has no vertex."""
    parts = ['', 'trunk', 'arm.L', 'hand.L', 'arm.R']
    part = [1, 1, 1, 1, 2, 2, 3]
    tag = [0, 1, 1, 0, 0, 0, 0]
    edges = [(0, 1), (1, 2), (2, 3), (3, 0), (1, 4), (2, 5), (4, 5), (5, 6), (0, 4)]
    me = NS(vertices=list(range(len(part))), edges=[NS(vertices=e) for e in edges],
            attributes={'part': NS(data=[NS(value=p) for p in part]), 'join_loop': NS(data=[NS(value=t) for t in tag])})
    ob = _Object(me, [])
    ob['parts'] = parts
    return ob


def test_join_zones_hold_the_join_loop_next_to_the_child():
    joins = skeletons.sided([('trunk', 'arm.{s}', {'UpperArm.{s}': 0.2})])
    zones = rig.join_zones(_zone_mesh(), joins[:1], 0)
    assert zones == [({1, 2, 4, 5}, {1, 2}, {'UpperArm.L': 0.2})], 'vertex 0 is untagged, 3 not next to the arm'
    grown = rig.join_zones(_zone_mesh(), [('trunk', 'arm.L', {})], 1)
    assert grown[0][0] == {0, 1, 2, 3, 4, 5, 6} and grown[0][1] == {1, 2}


def test_compare_import_reports_each_kind_of_difference_it_names():
    kinds = []
    for node in ast.walk(ast.parse((ROOT / 'lpk' / 'stages' / 'export.py').read_text(encoding='utf-8'))):
        if (isinstance(node, ast.Call) and getattr(node.func, 'id', None) == 'differ'
                and isinstance(node.args[0], ast.Constant)):
            kinds.append((node.lineno, node.args[0].value))
    in_order = list(dict.fromkeys(k for _, k in sorted(kinds)))
    assert in_order == list(export.DIFF_KINDS), in_order


def test_an_fbx_header_gets_the_fixed_creation_time_in_place():
    import struct

    def field(name, value):
        return bytes([len(name)]) + name.encode() + b'I' + struct.pack('<i', value)

    fields = [('Version', 1000), ('Year', 2026), ('Month', 10), ('Day', 17), ('Hour', 19), ('Minute', 54),
              ('Second', 9), ('Millisecond', 427)]
    stamp = b'CreationTimeStamp' + b''.join(bytes(13) + field(n, v) for n, v in fields)
    data = b'Kaydara FBX Binary  ' + field('FBXHeaderVersion', 1003) + stamp + b'Objects' + field('Year', 1999)
    fixed = export.fbx_fixed_time(data)
    assert len(fixed) == len(data) and export.fbx_fixed_time(fixed) == fixed, 'in place and idempotent'
    for name, value in export.FBX_CREATION_TIME:
        key = bytes([len(name)]) + name.encode() + b'I'
        i = fixed.index(key, fixed.index(b'CreationTimeStamp')) + len(key)
        assert struct.unpack('<i', fixed[i:i + 4])[0] == value, name
    assert fixed.endswith(b'Objects' + field('Year', 1999)), 'a field outside the header stays'
    assert fixed[:fixed.index(b'CreationTimeStamp')] == data[:data.index(b'CreationTimeStamp')]
    assert 'CreationTimeStamp' in _raises(export.fbx_fixed_time, b'Kaydara FBX Binary  no header')


def _fbx(nodes):
    """A binary FBX file of version 7400 holding `nodes`, each (name, [encoded properties], [child nodes])."""
    import struct

    def node(at, name, props, children):
        plist = b''.join(props)
        pos = at + 13 + len(name) + len(plist)
        body = b''
        for child in children:
            body += node(pos + len(body), *child)
        if children:
            body += bytes(13)
        return struct.pack('<III', pos + len(body), len(props), len(plist)) + bytes([len(name)]) + name + plist + body

    out = b'Kaydara FBX Binary  \x00\x1a\x00' + struct.pack('<I', 7400)
    for n in nodes:
        out += node(len(out), *n)
    return out + bytes(13)


def test_an_fbx_file_gets_its_object_ids_renumbered_in_order_of_appearance():
    import struct

    def L(v):
        return b'L' + struct.pack('<q', v)

    def S(s):
        return b'S' + struct.pack('<I', len(s)) + s

    def scene(document, body, rig, pose):
        array = b'i' + struct.pack('<III', 2, 0, 8) + struct.pack('<ii', 7, 8)
        return _fbx([
            (b'Documents', [], [(b'Document', [L(document), S(b'Scene')], [(b'RootNode', [L(0)], [])])]),
            (b'GlobalSettings', [], [(b'Properties70', [], [(b'P', [S(b'TimeSpanStop'), L(461876000)], [])])]),
            (b'Objects', [], [(b'Model', [L(body), S(b'Body')], [(b'Vertices', [array], [])]),
                              (b'Model', [L(rig), S(b'Rig')], []),
                              (b'Pose', [L(pose)], [(b'PoseNode', [], [(b'Node', [L(rig)], [])])])]),
            (b'Connections', [], [(b'C', [S(b'OO'), L(body), L(rig)], []), (b'C', [S(b'OO'), L(rig), L(0)], [])])])

    first, second = scene(900001, 777000003, 555000002, 333000004), scene(18, 123456789, 42, 987654321)
    fixed = export.fbx_fixed_ids(first)
    assert fixed == export.fbx_fixed_ids(second), 'files that differ by their object ids only become equal'
    assert len(fixed) == len(first) and export.fbx_fixed_ids(fixed) == fixed, 'in place and idempotent'
    values = {b'/'.join(path + (name,)).decode(): [struct.unpack('<q', v)[0] for k, _, v in props if k == b'L']
              for path, name, props in export.fbx_records(fixed) if name != b'C'}
    assert values['Documents/Document'] == [1] and values['Documents/Document/RootNode'] == [0]
    assert values['Objects/Pose'] == [4] and values['Objects/Pose/PoseNode/Node'] == [3]
    assert values['GlobalSettings/Properties70/P'] == [461876000], 'an integer that is no object id stays'
    links = [[struct.unpack('<q', v)[0] for k, _, v in props if k == b'L']
             for _, name, props in export.fbx_records(fixed) if name == b'C']
    assert links == [[2, 3], [3, 0]]
    assert 'not a binary FBX' in _raises(export.fbx_fixed_ids, b'Kaydara FBX ASCII')
    assert 'unknown type' in _raises(export.fbx_fixed_ids, _fbx([(b'Objects', [b'Z\x00'], [])]))


def test_the_row_kernels_import_no_project_state():
    for name in KERNELS:
        tree = ast.parse((ROOT / (name.replace('.', '/') + '.py')).read_text(encoding='utf-8'))
        imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        imported |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert not imported & {'lpk.state', 'lpk.project', 'lpk.model', 'lpk.runner', 'lpk.pipeline'}, (name, imported)


class _UV(tuple):
    """A 2D UV point with mathutils' 2D difference and cross product (a scalar), for _folded_regions."""

    def __sub__(self, o):
        return _UV((self[0] - o[0], self[1] - o[1]))

    def cross(self, o):
        return self[0] * o[1] - self[1] * o[0]


def test_folded_regions_weighs_a_face_of_no_area_as_nothing():
    uv = [(0, 0), (1, 0), (0, 1), (1, 0), (1, 1), (0, 1), (0, 0), (0.5, 0), (1, 0)]
    me = NS(uv_layers={texture.UV_LAYER: NS(data=[NS(uv=p) for p in uv])},
            polygons=[NS(loop_indices=range(3 * i, 3 * i + 3)) for i in range(3)])
    face = lambda i, area: NS(index=i, calc_area=lambda: area)
    with _patched(texture, Vector=_UV):
        assert texture._folded_regions(me, [[face(0, 0.5), face(1, 0.5), face(2, 0.0)]]) == [], \
            'a face of no area neither divides by zero nor counts as stretched'
        assert len(texture._folded_regions(me, [[face(2, 0.0)]])) == 1, 'a region of no area counts as folded'


if __name__ == '__main__':
    failed = 0
    tests = [(k, v) for k, v in list(globals().items()) if k.startswith('test_') and callable(v)]
    for name, fn in tests:
        try:
            fn()
        except Exception:
            failed += 1
            import traceback
            traceback.print_exc()
            print('FAILED ', name)
        else:
            print('ok     ', name)
    print('%d passed, %d failed' % (len(tests) - failed, failed))
    sys.exit(1 if failed else 0)
