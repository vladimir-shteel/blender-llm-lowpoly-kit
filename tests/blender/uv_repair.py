"""Mesh edits under a frozen texture end to end in Blender (bpy as a Python module, background mode): the
worked example built, frozen and its texture frozen; edits with Blender's own operators that keep the UVs
(the head subdivided, a knife cut across the left leg, an edge ring of the right leg cut, the left foot
subdivided by the zone operation) leave the UV check with nothing on those parts; edits that break the UVs
(a trunk face extruded, a face of the right leg filled again with its UVs at the origin, a foot face's UVs
laid over the head's island, an arm face's UVs moved off the atlas) are listed by part with their reason;
on an atlas too small for new islands the repair reports no room and changes nothing; the repair gives the
broken faces new islands in free space, clear of every other island and of each other, every texel outside
their cells byte-identical in the frozen atlas and the atlas, the frozen texture stored so the build stamp
accepts it, the same UVs and texels from the same scene again; build, bake, rig and export re-import with
empty diffs.

Not a host test (the host loop runs tests/test_*.py): run it where bpy imports,

    python3 tests/blender/uv_repair.py

It works on a copy of examples/mannequin in a temporary folder and prints a short summary; any failed
check raises."""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import bpy
    import bmesh
except ImportError:
    print('skipped: bpy does not import here (pip install bpy, or run inside Blender)')
    sys.exit(0)

import numpy as np

from frozen_mode import check_export, edit, extrude_trunk, leave, note, raises, subdivide_head
from texture_freeze import face_parts, procedural_texture, write
from lpk import run
from lpk.stages import imaging, texture, zones

NAME = 'Mannequin'
ATLAS, FROZEN_IMAGE, FROZEN_MESH = NAME + '_Atlas', NAME + '_AtlasFrozen', NAME + '_Frozen'
KEPT = ('head', 'leg.L', 'leg.R', 'foot.L')


def stage(model, stages, **options):
    return run.model(model, stages=stages, **options)


def body():
    return bpy.data.objects[NAME]


def uvs():
    return zones.read_uv(body().data, texture.UV_LAYER)


def part_layer(bm, ob, part):
    return bm.verts.layers.int['part'], list(ob['parts']).index(part)


def knife_part(ob, part):
    """Cut every face of `part` with a plane across it at half its height (mesh.bisect, a knife cut)."""
    bm = edit(ob)
    layer, pid = part_layer(bm, ob, part)
    zs = [v.co.z for v in bm.verts if v[layer] == pid]
    for f in bm.faces:
        f.select = all(v[layer] == pid for v in f.verts)
    bmesh.update_edit_mesh(ob.data)
    assert bpy.ops.mesh.bisect(plane_co=(0.0, 0.0, (min(zs) + max(zs)) / 2), plane_no=(0.0, 0.0, 1.0)) == {'FINISHED'}
    leave(ob)


def cut_ring(ob, part, at=0.6):
    """Cut once through the ring of edges of `part` that cross the height `at` of its span (a loop cut:
    mesh.subdivide_edgering on that ring)."""
    bm = edit(ob)
    bpy.ops.mesh.select_mode(type='EDGE')
    layer, pid = part_layer(bm, ob, part)
    zs = [v.co.z for v in bm.verts if v[layer] == pid]
    z = min(zs) + at * (max(zs) - min(zs))
    ring = [e for e in bm.edges if all(v[layer] == pid for v in e.verts)
            and min(v.co.z for v in e.verts) < z < max(v.co.z for v in e.verts)
            and abs(e.verts[0].co.z - e.verts[1].co.z) > 0.5 * (e.verts[0].co - e.verts[1].co).length]
    assert len(ring) >= 6, len(ring)
    for e in ring:
        e.select = True
    bmesh.update_edit_mesh(ob.data)
    assert bpy.ops.mesh.subdivide_edgering(number_cuts=1) == {'FINISHED'}
    leave(ob)


def fill_collapsed(ob, part):
    """Delete the front face of `part` nearest its centre and fill the hole with a new face whose UVs bmesh
    leaves at the origin (a fill without UVs)."""
    bpy.context.view_layer.objects.active = ob
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    layer, pid = part_layer(bm, ob, part)
    faces = [f for f in bm.faces if all(v[layer] == pid for v in f.verts) and f.normal.y < -0.5]
    mid = sum((f.calc_center_median() for f in faces), faces[0].calc_center_median() * 0) / len(faces)
    face = min(faces, key=lambda f: ((f.calc_center_median() - mid).length, f.index))
    verts = list(face.verts)
    bmesh.ops.delete(bm, geom=[face], context='FACES_ONLY')
    new = bm.faces.new(verts)
    uvl = bm.loops.layers.uv[texture.UV_LAYER]
    for loop in new.loops:
        loop[uvl].uv = (0.0, 0.0)
    bm.to_mesh(ob.data)
    bm.free()
    ob.data.update()


def largest(ob, part):
    """The face of `part` with the largest UV area."""
    uv = uvs()
    best = None
    for p, pn in zip(ob.data.polygons, face_parts(ob)):
        if pn != part:
            continue
        q = uv[list(p.loop_indices)]
        (ax, ay), (bx, by) = q[1] - q[0], q[2] - q[0]
        area = abs(ax * by - ay * bx)
        if best is None or area > best[0]:
            best = (area, p.index)
    return best[1]


def set_face_uvs(ob, face, uv_of):
    """Write the UVs of `face`'s corners with uv_of(their UVs) (a hand UV edit)."""
    uv = uvs()
    loops = list(ob.data.polygons[face].loop_indices)
    uv[loops] = uv_of(uv[loops])
    ob.data.uv_layers[texture.UV_LAYER].uv.foreach_set('vector', uv.ravel())
    ob.data.update()


def broken(report):
    return {part: entry['broken'] for part, entry in report['parts'].items()}


def snapshot():
    return uvs().copy(), texture.image_levels(FROZEN_IMAGE), texture.image_levels(ATLAS)


def save(path):
    for name in (ATLAS,):
        img = bpy.data.images[name]
        if img.packed_file is None:
            img.pack()
    bpy.ops.wm.save_as_mainfile(filepath=path)


def raster(uv, faces, size):
    """The texels the faces' UVs touch (lpk.stages.imaging.uv_raster)."""
    A, _ = texture.uv_arrays(NAME)
    tris, tri_face, _, _ = zones.face_uv_areas(A['co'], A['loop_start'], A['loop_total'], A['loop_vert'], uv, size)
    return imaging.uv_raster(tris[np.isin(tri_face, list(faces))], (size[1], size[0]))


def main():
    work = tempfile.mkdtemp(prefix='lpk_uv_repair_')
    folder = os.path.join(work, 'mannequin')
    shutil.copytree(os.path.join(ROOT, 'examples', 'mannequin'), folder,
                    ignore=shutil.ignore_patterns('out', '__pycache__', '*.blend', 'edits.json'))
    model = os.path.join(folder, 'mannequin.py')
    with open(model, encoding='utf-8') as f:
        source = f.read()
    frozen_model = os.path.join(folder, 'mannequin_frozen.py')
    write(frozen_model, source + '\nFROZEN = True\n')
    tex_model = os.path.join(folder, 'mannequin_texture.py')
    write(tex_model, source + '\nFROZEN = True\nTEXTURE_FROZEN = True\n')
    blend = os.path.join(work, 'broken.blend')

    note('the example built, frozen, its texture frozen')
    stage(model, ('build',))
    stage(model, ('freeze',))
    stage(frozen_model, ('build',))
    procedural_texture(frozen_model)
    assert 'TEXTURE_FROZEN = True' in raises(run.repair_uvs, frozen_model)
    stage(frozen_model, ('freeze_texture',))
    base = stage(tex_model, ('build',))['build']['uv_check']
    assert base == run.check_uvs(tex_model)
    note('  the unwrap\'s own faults:', {p: {k: len(v) for k, v in e.items() if isinstance(v, list) and v}
                                         for p, e in base['parts'].items()})
    assert not set(KEPT) & set(base['parts']), base['parts'].keys()
    counts = {p: len(v) for p, v in broken(base).items()}

    note('edits that keep the UVs: subdivide, knife, loop cut, the zone subdivide')
    M = run.load(tex_model)
    P = M.props()
    subdivide_head(body())
    knife_part(body(), 'leg.L')
    cut_ring(body(), 'leg.R')
    rep = stage(tex_model, ('freeze',))['freeze']
    assert rep['topology_changed'] and rep['uv_layer'] == texture.UV_LAYER
    check = rep['uv_check']
    note('  freeze uv_check: faces', base['faces'], '->', check['faces'], 'broken', check['broken'])
    assert check['faces'] > base['faces'] and not set(KEPT) & set(check['parts']), check['parts'].keys()
    assert {p: len(v) for p, v in broken(check).items()} == counts, 'the edits broke no other face'
    check = run.subdivide(tex_model, 'foot.L', cuts=2)['uv_check']
    assert not set(KEPT) & set(check['parts']) and {p: len(v) for p, v in broken(check).items()} == counts
    assert stage(tex_model, ('build',))['build']['uv_check'] == run.check_uvs(tex_model)

    note('edits that break the UVs: an extrusion, a fill without UVs, two hand UV edits')
    extrude_trunk(body(), P['shirt_hem_z'] + 0.1)
    fill_collapsed(body(), 'leg.R')
    check = stage(tex_model, ('freeze',))['freeze']['uv_check']
    assert check['parts']['trunk']['zero'] and check['parts']['leg.R']['zero'], check['parts']
    stage(tex_model, ('build',))
    head = largest(body(), 'head')
    head_uv = uvs()[list(body().data.polygons[head].loop_indices)]
    foot = largest(body(), 'foot.R')
    set_face_uvs(body(), foot, lambda q: head_uv)
    arm = largest(body(), 'arm.R')
    set_face_uvs(body(), arm, lambda q: q + np.array([1.5, 0.0], np.float32))
    check = run.check_uvs(tex_model)
    found = {p: {k: v for k, v in e.items() if isinstance(v, list) and v and k != 'broken'}
             for p, e in check['parts'].items() if p not in counts}
    note('  check_uvs:', found)
    assert check['parts']['foot.R']['overlap'] == [foot] and check['parts']['arm.R']['outside'] == [arm], found
    assert 'head' not in check['parts'], 'the larger island is not read as lying on the smaller'
    edited = sorted(p for p in check['parts'] if p not in counts)
    assert edited == ['arm.R', 'foot.R', 'leg.R', 'trunk'], edited
    assert 'UVs were edited by hand' in raises(stage, tex_model, ('build',))
    save(blend)

    note('no room: the same islands on an atlas too small for new ones')
    small = texture.image_levels(FROZEN_IMAGE)[::32, ::32].copy()
    texture.store_levels(FROZEN_IMAGE, small)
    before = uvs().copy()
    rep = run.repair_uvs(tex_model, parts=edited)
    note('  repair:', {k: rep[k] for k in ('placed', 'cells', 'changed')}, rep['next'][:60] + '...')
    assert not rep['placed'] and 'unfreeze_texture' in rep['next'] and any(c['cell'] is None for c in rep['charts'])
    assert np.array_equal(uvs(), before) and np.array_equal(texture.image_levels(FROZEN_IMAGE), small)
    assert 'stored' not in rep and 'UVs were edited by hand' in raises(stage, tex_model, ('build',))

    results = []
    for attempt in range(2):
        bpy.ops.wm.open_mainfile(filepath=blend)
        note('the repair, run %d' % (attempt + 1))
        uv0, frozen0, atlas0 = snapshot()
        size = tuple(bpy.data.images[FROZEN_IMAGE].size)
        rep = run.repair_uvs(tex_model, parts=edited)
        note('  repair:', {k: rep[k] for k in ('placed', 'texels_per_m', 'cells', 'changed')},
             'charts', len(rep['charts']))
        assert rep['placed'] and rep['stored']['layer'] == texture.UV_LAYER, rep
        faces = sorted(f for p in edited for f in rep['faces'][p])
        assert faces == sorted(f for p in edited for f in rep['before']['parts'][p]['broken'])
        assert sorted(f for c in rep['charts'] for f in c['faces']) == faces
        assert set(rep['after']['parts']) == set(counts), rep['after']['parts'].keys()
        uv1, frozen1, atlas1 = snapshot()
        polys = body().data.polygons
        moved = [f for f in range(len(polys))
                 if not np.array_equal(uv0[list(polys[f].loop_indices)], uv1[list(polys[f].loop_indices)])]
        assert moved == faces, 'only the broken faces get new UVs'
        cells = np.zeros((size[1], size[0]), bool)
        for c in rep['charts']:
            x, y, w, h = c['cell']
            assert not cells[y:y + h, x:x + w].any(), 'the cells do not overlap'
            cells[y:y + h, x:x + w] = True
        others = [f for f in range(len(body().data.polygons)) if f not in set(faces)
                  and face_parts(body())[f] not in getattr(M, 'OWN', {})]
        assert not (raster(uv1, others, size) & cells).any(), 'no cell covers another island'
        assert not (raster(uv1, faces, size) & ~cells).any(), 'the new islands lie in their cells'
        assert np.array_equal(frozen1[~cells], frozen0[~cells]), 'frozen texels outside the cells kept'
        assert np.array_equal(atlas1[~cells], atlas0[~cells]), 'atlas texels outside the cells kept'
        assert rep['changed'] > 0 and np.array_equal(frozen1[cells], atlas1[cells])
        assert np.array_equal(zones.read_uv(bpy.data.meshes[FROZEN_MESH], texture.UV_LAYER), uv1), 'UVs stored'
        assert texture.image_edited(ATLAS) is None
        results.append((uv1, frozen1, atlas1))
    assert all(np.array_equal(a, b) for a, b in zip(*results)), 'the same scene repairs to the same UVs and texels'

    note('build, bake, rig and export over the repaired texture')
    out = stage(tex_model, ('build', 'bake', 'rig'))
    assert np.array_equal(uvs(), results[0][0]), 'the build restores the repaired UVs'
    assert out['bake']['report']['changed'] == 0, 'no over source: the atlas is the frozen image'
    assert np.array_equal(texture.image_levels(ATLAS), results[0][1])
    assert set(out['bake']['uv_check']['parts']) == set(counts)
    check_export(stage(tex_model, ('export',))['export'], 'repaired texture')
    again = run.repair_uvs(tex_model, parts=edited)
    assert again['faces'] == {} and again['changed'] == 0, 'nothing left to repair'
    shutil.rmtree(work, ignore_errors=True)
    print('\nall UV repair checks passed')


if __name__ == '__main__':
    main()
