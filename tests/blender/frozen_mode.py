"""The frozen mesh mode end to end in Blender (background mode): the worked example
built, frozen, edited for real with Blender's mesh operators (the head's faces subdivided, a trunk face
extruded, an edge ring of an arm dissolved), refused by the build stamp, frozen again with its zones
transferred, built in the frozen mode and taken through unwrap, packs, bake, rig and export; the parametric
mode's guard against moves not captured; the zone tools; and adopt of the example's own export
re-imported as a foreign mesh. Captures need Blender's user interface and are not run; the part capture's
clean-up is checked.

Not a host test (the host loop runs tests/test_*.py): run it in Blender,

    blender -b --python-exit-code 1 --python tests/blender/frozen_mode.py

It works on a copy of examples/mannequin in a temporary folder and prints a short summary; any failed
check raises."""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import bpy
import bmesh

import numpy as np

from lpk import run
from lpk.stages import zones

NAME = 'Mannequin'
LOG = []


def note(*args):
    LOG.append(' '.join(str(a) for a in args))
    print(*args)


def raises(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except (ValueError, RuntimeError) as e:
        return str(e)
    raise AssertionError('no error from %s' % getattr(fn, '__name__', fn))


def body():
    return bpy.data.objects[NAME]


def edit(ob):
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_mode(type='FACE')
    bpy.ops.mesh.select_all(action='DESELECT')
    return bmesh.from_edit_mesh(ob.data)


def leave(ob):
    bmesh.update_edit_mesh(ob.data)
    bpy.ops.object.mode_set(mode='OBJECT')


def part_ids(ob, part):
    parts = list(ob['parts'])
    a = ob.data.attributes['part'].data
    return [i for i in range(len(a)) if a[i].value == parts.index(part)]


def subdivide_head(ob):
    """Subdivide every face of the head; returns the ids of the new vertices."""
    n0 = len(ob.data.vertices)
    bm = edit(ob)
    layer = bm.verts.layers.int['part']
    hid = list(ob['parts']).index('head')
    for f in bm.faces:
        f.select = all(v[layer] == hid for v in f.verts)
    bmesh.update_edit_mesh(ob.data)
    assert bpy.ops.mesh.subdivide(number_cuts=1) == {'FINISHED'}
    leave(ob)
    return list(range(n0, len(ob.data.vertices)))


def extrude_trunk(ob, z, depth=0.03):
    """Extrude the front face of the trunk nearest the midline at height `z` (m) by `depth` m forward;
    returns the new vertex ids."""
    n0 = len(ob.data.vertices)
    bm = edit(ob)
    layer = bm.verts.layers.int['part']
    tid = list(ob['parts']).index('trunk')
    front = [f for f in bm.faces if all(v[layer] == tid for v in f.verts) and f.normal.y < -0.9]
    face = min(front, key=lambda f: (abs(f.calc_center_median().z - z) + abs(f.calc_center_median().x), f.index))
    face.select = True
    bmesh.update_edit_mesh(ob.data)
    assert bpy.ops.mesh.extrude_region_move(TRANSFORM_OT_translate={'value': (0.0, -depth, 0.0)}) == {'FINISHED'}
    leave(ob)
    return list(range(n0, len(ob.data.vertices)))


def dissolve_arm_ring(ob, M, P):
    """Dissolve one closed ring of the left arm between the shoulder and the wrist (its vertices, so the
    faces on both sides merge into polygons); returns the number of vertices removed."""
    d = np.subtract(M.arm_point(P, 'wrist', 1.0), M.arm_point(P, 'shoulder', 1.0))
    d /= np.linalg.norm(d)
    ids = part_ids(ob, 'arm.L')
    co = np.array([tuple(ob.data.vertices[i].co) for i in ids])
    t = co @ d
    edges = {tuple(sorted(e.vertices)) for e in ob.data.edges}
    rings = []
    order = np.argsort(t, kind='stable')
    group = [order[0]]
    for a, b in zip(order[:-1], order[1:]):
        if t[b] - t[a] < 1e-3:
            group.append(b)
        else:
            rings.append(group)
            group = [b]
    rings.append(group)
    cycles = []
    for g in rings:
        vs = sorted(ids[k] for k in g)
        ring_edges = [e for e in edges if e[0] in vs and e[1] in vs]
        degree = {v: 0 for v in vs}
        for a, b in ring_edges:
            degree[a] += 1
            degree[b] += 1
        if len(vs) >= 6 and len(ring_edges) == len(vs) and all(x == 2 for x in degree.values()):
            cycles.append((vs, ring_edges))
    assert len(cycles) >= 3, 'found %d closed rings on arm.L' % len(cycles)
    vs, ring_edges = cycles[len(cycles) // 2]
    n0 = len(ob.data.vertices)
    bm = edit(ob)
    bpy.ops.mesh.select_mode(type='VERT')
    wanted = set(vs)
    for v in bm.verts:
        v.select = v.index in wanted
    bm.select_flush(True)
    bmesh.update_edit_mesh(ob.data)
    assert bpy.ops.mesh.dissolve_verts() == {'FINISHED'}
    leave(ob)
    return n0 - len(ob.data.vertices)


def stage(model, stages, **options):
    return run.model(model, stages=stages, **options)


def pipeline(model):
    """unwrap, packs until settled (at most 9), bake, rig, export; returns the export report."""
    r = stage(model, ('unwrap',) + ('pack',) * 3)
    packs = r['pack']
    for _ in range(2):
        if packs[-1]['settled']:
            break
        packs = stage(model, ('pack',) * 3)['pack']
    note('  packs settled:', packs[-1]['settled'])
    stage(model, ('bake', 'rig'))
    return stage(model, ('export',))['export']


def check_export(rep, what):
    for profile, r in rep.items():
        diffs = r['reimport']['diffs']
        note('  export %s %s: diffs %s' % (what, profile, diffs))
        assert diffs == [], (profile, diffs)


def main():
    work = tempfile.mkdtemp(prefix='lpk_frozen_')
    folder = os.path.join(work, 'mannequin')
    shutil.copytree(os.path.join(ROOT, 'examples', 'mannequin'), folder,
                    ignore=shutil.ignore_patterns('out', '__pycache__', '*.blend', 'edits.json'))
    model = os.path.join(folder, 'mannequin.py')
    with open(model, encoding='utf-8') as f:
        source = f.read()
    frozen_model = os.path.join(folder, 'mannequin_frozen.py')
    with open(frozen_model, 'w', encoding='utf-8', newline='\n') as f:
        f.write(source + '\n# The frozen mode: build copies Mannequin_Frozen.\nFROZEN = True\n')
    M = run.load(model)
    P = M.props()
    P['edits'] = {}

    note('parametric build and a freeze of the unchanged body')
    built = stage(model, ('build',))['build']
    n_built = built['body']['verts']
    parts = list(body()['parts'])
    assert zones.edited(NAME) is None and built['frozen'] is False
    rep = stage(model, ('freeze',))['freeze']
    assert rep['reference'] == 'body' and not rep['topology_changed'] and rep['changed'] == {'part': {}, 'pal': {}}
    assert rep['mode'] == 'parametric' and 'FROZEN = True' in rep['next']
    assert bpy.data.meshes[NAME + '_Frozen'].use_fake_user

    note('topology edits with bpy.ops: subdivide the head, extrude a trunk face, dissolve an arm ring')
    ob = body()
    removed = dissolve_arm_ring(ob, M, P)
    new_head = subdivide_head(ob)
    raw = [ob.data.attributes['part'].data[i].value for i in new_head]
    new_trunk = extrude_trunk(ob, (P['armpit_z'] + P['waist_z']) / 2)
    note('  head +%d verts (interpolated part values %s), extruded +%d, ring -%d'
         % (len(new_head), sorted(set(raw)), len(new_trunk), removed))
    msg = raises(stage, model, ('build',))
    assert 'topology was edited by hand' in msg and 'set FROZEN = True' in msg, msg
    note('  build refused:', msg)
    msg = raises(stage, model, ('capture_edits',))
    assert 'topology' in msg and 'freeze' in msg, msg
    note('  capture_edits refused:', msg)

    note('freeze against the frozen mesh it replaces')
    edited_count = len(ob.data.vertices)
    rep = stage(model, ('freeze',))['freeze']
    note('  report:', {k: rep[k] for k in ('reference', 'topology_changed', 'far', 'far_max_cm', 'changed',
                                           'join_loop', 'triangulated')})
    assert rep['reference'] == 'frozen' and rep['topology_changed']
    vp = [a.value for a in ob.data.attributes['part'].data]
    assert list(ob['parts']) == parts and all(0 < v < len(parts) for v in vp), 'every vertex carries a real part'
    assert {parts[vp[i]] for i in new_head} == {'head'}, 'the subdivided head stays head'
    assert rep['far'] == {'trunk': len(new_trunk)}, rep['far']
    assert all(parts[vp[i]] == 'trunk' for i in range(edited_count - len(new_trunk), edited_count))
    assert rep['join_loop']['tagged'] == rep['join_loop']['reference'], rep['join_loop']
    assert all(len(p.vertices) == 3 for p in ob.data.polygons)
    A, R = zones.read(ob.data), zones.read(bpy.data.meshes[NAME + '_Frozen'])
    assert zones.topology_key(len(A['co']), A['loop_total'], A['loop_vert']) == \
        zones.topology_key(len(R['co']), R['loop_total'], R['loop_vert'])
    assert (A['part'] == R['part']).all() and (A['pal'] == R['pal']).all()

    note('first freeze against a fresh parametric build (no frozen mesh)')
    keep = zones.read(ob.data)
    bpy.data.meshes.remove(bpy.data.meshes[NAME + '_Frozen'])
    del ob[zones.STAMP_TOPOLOGY]
    rep2 = stage(model, ('freeze',))['freeze']
    again = zones.read(ob.data)
    assert rep2['reference'] == 'parametric' and rep2['far'] == rep['far']
    assert (again['part'] == keep['part']).all() and (again['pal'] == keep['pal']).all(), \
        'the parametric build and the frozen mesh it froze give the same zones'
    assert not [o for o in bpy.data.objects if o.name.endswith('_ZoneRef')]

    note('the parametric build goes on until FROZEN is set')
    assert stage(model, ('build',))['build']['body']['verts'] == n_built

    note('frozen build and the stages after it')
    out = stage(frozen_model, ('build',))['build']
    assert out['frozen'] and out['body']['verts'] == edited_count and set(out['sources']) == set(M.SOURCES), out
    assert out['body']['degenerate'] == {}, out['body']['degenerate']
    note('  body', out['body']['tris'], 'tris', out['body']['verts'], 'verts')
    first = zones.read(body().data)
    stage(frozen_model, ('build',))
    second = zones.read(body().data)
    assert all(np.array_equal(first[k], second[k]) for k in ('co', 'loop_vert', 'part', 'pal', 'join_loop')), \
        'the frozen build is deterministic'
    assert np.array_equal(first['part'], A['part']) and np.array_equal(first['co'], A['co'])
    assert raises(stage, frozen_model, ('capture_edits',)) == \
        'capture_edits is for the parametric mode: in the frozen mode run freeze'
    check_export(pipeline(frozen_model), 'frozen')

    note('frozen guard: a moved vertex, then a topology edit')
    ob = body()
    ob.data.vertices[0].co.z += 0.01
    moved = tuple(ob.data.vertices[0].co)
    msg = raises(stage, frozen_model, ('build',))
    assert 'run freeze to store the moves' in msg, msg
    stage(frozen_model, ('freeze', 'build'))
    assert tuple(body().data.vertices[0].co) == moved
    subdivide_head(body())
    msg = raises(stage, frozen_model, ('build',))
    assert 'run freeze to store the edit' in msg, msg
    stage(frozen_model, ('build',), discard_edits=True)

    note('parametric guard: a moved vertex is refused until capture_edits stores it')
    stage(model, ('build',), discard_edits=True)
    ob = body()
    i = part_ids(ob, 'trunk')[5]
    ob.data.vertices[i].co.x += 0.008
    target = tuple(ob.data.vertices[i].co)
    msg = raises(stage, model, ('build',))
    assert 'run capture_edits' in msg, msg
    cap = stage(model, ('capture_edits',))['capture_edits']
    assert cap['parts'].get('trunk') == 1, cap
    stage(model, ('build',))
    assert np.allclose(tuple(body().data.vertices[i].co), target, atol=1e-6)
    del body()[zones.STAMP_POSITIONS]
    assert 'carries no build stamp' in raises(stage, model, ('build',))
    stage(model, ('build',), discard_edits=True)
    os.remove(os.path.join(folder, 'edits.json'))
    stage(model, ('build',), discard_edits=True)

    note('zone tools')
    summary = run.zones(model, reference='parametric')
    assert summary['arm.L']['mirror'] == 'arm.R' and summary['arm.L']['deviation']['max_cm'] == 0.0, summary['arm.L']
    assert summary['trunk']['neighbours'].get('arm.L', 0) > 0 and summary['head']['uncoloured'] == 0
    stage(frozen_model, ('build',))
    fz = run.zones(frozen_model, reference='parametric')
    assert fz['trunk']['deviation']['max_cm'] >= 2.9, fz['trunk']['deviation']
    note('  frozen vs parametric deviation, trunk:', fz['trunk']['deviation'], 'arm.L:', fz['arm.L']['deviation'])
    assert run.zones(frozen_model, reference='frozen')['head']['deviation']['max_cm'] == 0.0
    sel = run.select(frozen_model, 'ear.L')
    assert sel['verts'] == len(part_ids(body(), 'ear.L')) and sel['faces'] > 0
    got = run.assign(frozen_model, 'ear_left')
    assert got['from'] == {'ear.L': sel['verts']} and 'ear_left' in body()['parts'], got
    painted = run.paint(frozen_model, 'shirt')
    assert painted['faces'] == sel['faces']
    assert run.model(frozen_model, ('freeze',))['freeze']['reference'] == 'body'
    assert 'ear_left' in bpy.data.meshes[NAME + '_Frozen']['parts']
    try:
        run.capture(frozen_model, part='head')
        note('  part capture ran')
    except Exception as e:  # no viewport in background mode
        note('  part capture needs the user interface here: %s' % type(e).__name__)
    assert bpy.data.objects.get(NAME + '_Part') is None and bpy.data.meshes.get(NAME + '_Part') is None

    note('adopt: the exported GLB re-imported as a foreign mesh')
    stage(model, ('build',), discard_edits=True)
    export = pipeline(model)
    check_export(export, 'parametric')
    glb = export['glb_generic']['path']
    for o in [o for o in bpy.data.objects if o.name == NAME or o.name.startswith(NAME + '_')]:
        bpy.data.objects.remove(o, do_unlink=True)
    bpy.data.meshes.remove(bpy.data.meshes[NAME + '_Frozen'])
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=glb, merge_vertices=True)
    imported = [o for o in bpy.data.objects if o not in before]
    note("  imported:", sorted((o.name, o.type) for o in imported))
    mesh = next(o for o in imported if o.type == "MESH" and o.name == NAME)
    mesh.name = 'Foreign'
    for o in imported:
        if o.type == 'ARMATURE':
            o.name = 'ForeignRig'
    adopt_model = os.path.join(folder, 'mannequin_adopt.py')
    with open(adopt_model, 'w', encoding='utf-8', newline='\n') as f:
        f.write(source + "\nFROZEN = True\nADOPT = 'Foreign'\n")
    head = mesh.vertex_groups.new(name='head')
    up = [v.index for v in mesh.data.vertices if (mesh.matrix_world @ v.co).z > P['chin_z'] + 0.02]
    head.add(up, 1.0, 'REPLACE')
    rep = stage(adopt_model, ('adopt', 'build', 'rig'))
    note('  adopt:', {k: rep['adopt'][k] for k in ('vertices', 'zones', 'pal', 'parts')})
    assert rep['adopt']['zones']['vertex_group'] == len(up) and rep['adopt']['zones']['blocks'] > 0
    assert rep['build']['frozen'] and rep['rig']['skin'] is not None
    shutil.rmtree(work, ignore_errors=True)
    print('\nall frozen-mode checks passed')


if __name__ == '__main__':
    main()
