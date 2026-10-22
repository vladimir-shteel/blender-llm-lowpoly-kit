"""The frozen texture end to end in Blender (bpy as a Python module, background mode): the worked example
built, frozen and textured; freeze_texture stores its UVs and atlas; a block of the atlas painted by script
(a hand paint) and the UVs of one part moved (a hand UV edit) are refused by the frozen bake until
freeze_texture stores them; with TEXTURE_FROZEN = True the build brings the stored UVs back, unwrap and pack
refuse, and the bake composites only a new 'over' source (a belt round the trunk, added in a copy of the
module) over the frozen atlas: every texel outside the belt's reach, the painted block among them, keeps the
frozen image's levels, the belt's texels change, and a second bake gives the same atlas; a UV edit is
refused by the build stamp; a mesh freeze keeps the UVs; rig and export re-import with empty diffs;
unfreeze_texture removes the frozen texture and says what is lost, and the procedural stages run again.
Last, adopt of the example's own GLB re-imported: the face colours are sampled from its texture, its UVs
and image become the frozen texture, the build restores them and the export re-imports with empty diffs.

Not a host test (the host loop runs tests/test_*.py): run it where bpy imports,

    python3 tests/blender/texture_freeze.py

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
except ImportError:
    print('skipped: bpy does not import here (pip install bpy, or run inside Blender)')
    sys.exit(0)

import numpy as np

from frozen_mode import check_export, note, raises
from lpk import run
from lpk.stages import texture, zones

NAME = 'Mannequin'
ATLAS, FROZEN_IMAGE, FROZEN_MESH = NAME + '_Atlas', NAME + '_AtlasFrozen', NAME + '_Frozen'
BELT = NAME + '_Belt'
# The belt added on top of the frozen texture: a dark band lofted round the trunk just above the shirt's
# hem, and marked 'over' so the frozen bake composites it.
BELT_SOURCE = '''

BELT_LIFT = 0.006


def _belt(P):
    """A dark band round the trunk just above the shirt's hem."""
    sections = trunk_sections(P)
    band = []
    for name, dz in (('low', 0.01), ('high', 0.035)):
        s = torso.section_at(sections, P['shirt_hem_z'] + dz)
        band.append(Section(name, s.at, (s.half[0] + BELT_LIFT, s.half[1] + BELT_LIFT), exponent=s.exponent))
    t = Builder(PALETTE)
    rings = loft_rings(band, (1.0, 0.0, 0.0), torso.SIDES)
    t.loft('trunk', rings, torso.SIDES, Vector(rings[0][3]['ref']), 'shoe')
    return t


_build_mesh = build_mesh


def build_mesh(P):
    body, sources = _build_mesh(P)
    sources['Belt'] = _belt(P)
    return body, sources


SOURCES = dict(SOURCES, Belt={'mask': ('trunk',), 'over': True})
FROZEN = True
'''


def stage(model, stages, **options):
    return run.model(model, stages=stages, **options)


def write(path, text):
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)


def uvs(me):
    return zones.read_uv(me, texture.UV_LAYER)


def body():
    return bpy.data.objects[NAME]


def procedural_texture(model):
    """unwrap, packs until settled (at most 9), bake; returns the bake's report."""
    packs = stage(model, ('unwrap',) + ('pack',) * 3)['pack']
    for _ in range(2):
        if packs[-1]['settled']:
            break
        packs = stage(model, ('pack',) * 3)['pack']
    return stage(model, ('bake',))['bake']['report']


def face_parts(ob):
    parts = list(ob['parts'])
    a = ob.data.attributes['part'].data
    return [parts[a[p.vertices[0]].value] for p in ob.data.polygons]


def paint_block(name, part, colour=(255, 0, 255), half=4):
    """Paint a square of texels in the image `name` round the UV centre of the largest face of `part` (a
    hand paint in Texture Paint); returns (rows, columns) slices of the block."""
    ob = body()
    uv = uvs(ob.data)
    best = None
    for p, pn in zip(ob.data.polygons, face_parts(ob)):
        if pn != part:
            continue
        q = uv[list(p.loop_indices)]
        (ax, ay), (bx, by) = q[1] - q[0], q[2] - q[0]
        area = abs(ax * by - ay * bx) / 2
        if best is None or area > best[0]:
            best = (area, q.mean(axis=0))
    img = bpy.data.images[name]
    w, h = img.size
    x, y = int(best[1][0] * w), int(best[1][1] * h)
    rows, cols = slice(max(0, y - half), y + half), slice(max(0, x - half), x + half)
    levels = texture.image_levels(name)
    levels[rows, cols, :3] = colour
    img.pixels.foreach_set((levels.astype(np.float32) / 255.0).ravel())
    img.update()
    return rows, cols


def shift_part_uvs(part, du):
    """Move the UVs of every face of `part` on the body by (du, 0) (a hand UV edit); returns the UVs."""
    ob = body()
    uv = uvs(ob.data)
    for p, pn in zip(ob.data.polygons, face_parts(ob)):
        if pn == part:
            for li in p.loop_indices:
                uv[li, 0] += du
    ob.data.uv_layers[texture.UV_LAYER].uv.foreach_set('vector', uv.ravel())
    ob.data.update()
    return uv


def trunk_reach(ob, size, margin):
    """The texels a trunk source can reach: the UV bounds of the trunk's faces grown by `margin` texels."""
    uv = uvs(ob.data)
    loops = [li for p, pn in zip(ob.data.polygons, face_parts(ob)) if pn == 'trunk' for li in p.loop_indices]
    lo, hi = uv[loops].min(axis=0), uv[loops].max(axis=0)
    w, h = size
    mask = np.zeros((h, w), bool)
    mask[max(0, int(lo[1] * h) - margin - 1):int(hi[1] * h) + margin + 2,
         max(0, int(lo[0] * w) - margin - 1):int(hi[0] * w) + margin + 2] = True
    return mask


def palette_shares(ob):
    names = list(ob['palette'])
    pal = ob.data.attributes['pal'].data
    counts = {}
    for i in range(len(pal)):
        counts[names[pal[i].value]] = counts.get(names[pal[i].value], 0) + 1
    total = sum(counts.values())
    return {k: v / total for k, v in counts.items()}


def main():
    work = tempfile.mkdtemp(prefix='lpk_texture_')
    folder = os.path.join(work, 'mannequin')
    shutil.copytree(os.path.join(ROOT, 'examples', 'mannequin'), folder,
                    ignore=shutil.ignore_patterns('out', '__pycache__', '*.blend', 'edits.json'))
    model = os.path.join(folder, 'mannequin.py')
    with open(model, encoding='utf-8') as f:
        source = f.read()
    frozen_model = os.path.join(folder, 'mannequin_frozen.py')
    write(frozen_model, source + '\nFROZEN = True\n')
    belt_model = os.path.join(folder, 'mannequin_belt.py')
    write(belt_model, source + BELT_SOURCE)
    tex_model = os.path.join(folder, 'mannequin_texture.py')
    write(tex_model, source + BELT_SOURCE + 'TEXTURE_FROZEN = True\n')
    loose_model = os.path.join(folder, 'mannequin_loose.py')
    write(loose_model, source + '\nTEXTURE_FROZEN = True\n')

    note('the example built, frozen and textured')
    stage(model, ('build',))
    stage(model, ('freeze',))
    assert 'FROZEN = True' in raises(stage, loose_model, ('build',))
    stage(frozen_model, ('build',))
    procedural_texture(frozen_model)
    assert 'FROZEN = True' in raises(stage, model, ('freeze_texture',))
    rep = stage(frozen_model, ('freeze_texture',))['freeze_texture']
    note('  freeze_texture:', rep)
    assert rep['packed'] and rep['size'] == [512, 512] and rep['uv_layer'] == texture.UV_LAYER and rep['islands'] > 0
    assert rep['texture_mode'] == 'procedural' and 'TEXTURE_FROZEN = True' in rep['texture_next']
    img = bpy.data.images[FROZEN_IMAGE]
    assert img.use_fake_user and img.packed_file is not None
    assert np.array_equal(uvs(bpy.data.meshes[FROZEN_MESH]), uvs(body().data))
    assert np.array_equal(texture.image_levels(FROZEN_IMAGE), texture.image_levels(ATLAS))

    note('a hand paint and a hand UV edit, refused until freeze_texture stores them')
    rows, cols = paint_block(ATLAS, 'leg.L')
    painted = texture.image_levels(ATLAS)
    msg = raises(stage, tex_model, ('bake',))
    assert 'painted by hand' in msg and 'freeze_texture' in msg, msg
    note('  bake refused:', msg)
    edited_uv = shift_part_uvs('ear.L', 0.002)
    assert 'unfreeze_texture' in raises(stage, frozen_model, ('freeze',)), 'a mesh freeze would drop the frozen UVs'
    stage(frozen_model, ('freeze_texture',))
    assert np.array_equal(texture.image_levels(FROZEN_IMAGE), painted), 'the paint is what is stored'
    assert np.array_equal(uvs(bpy.data.meshes[FROZEN_MESH]), edited_uv), 'the UV edit is what is stored'
    frozen_levels, frozen_uv = texture.image_levels(FROZEN_IMAGE), uvs(bpy.data.meshes[FROZEN_MESH])

    note('the frozen texture: build brings the UVs back, unwrap and pack refuse')
    out = stage(tex_model, ('build',))['build']
    assert out['frozen'] and out['texture_frozen'] and BELT in [NAME + '_' + k for k in out['sources']], out
    assert np.array_equal(uvs(body().data), frozen_uv)
    for st in ('unwrap', 'pack'):
        msg = raises(stage, tex_model, (st,))
        assert 'texture is frozen' in msg and 'unfreeze_texture' in msg, msg
    note('  unwrap refused:', raises(stage, tex_model, ('unwrap',)))

    note('the bake composites the belt over the frozen atlas')
    rep = stage(tex_model, ('bake',))['bake']
    r = rep['report']
    note('  bake_over:', {k: r[k] for k in ('frozen', 'size', 'sources', 'changed')})
    assert list(r['sources']) == [BELT], 'only the over source bakes'
    belt = r['sources'][BELT]
    assert belt['hit'] > 0 and belt['changed'] > 0 and r['changed'] == belt['changed'], r
    assert not r['reach'][BELT]['beyond'] and not r['reach'][BELT]['deep'], r['reach'][BELT]
    new = texture.image_levels(ATLAS)
    assert np.array_equal(texture.image_levels(FROZEN_IMAGE), frozen_levels), 'the frozen image never changes'
    diff = (new != frozen_levels).any(axis=2)
    assert int(diff.sum()) == r['changed']
    reach = trunk_reach(body(), r['size'], texture.BAKE_MARGIN)
    assert not (diff & ~reach).any(), 'a texel outside the belt\'s reach changed'
    assert np.array_equal(new[rows, cols], frozen_levels[rows, cols]), 'the hand paint is kept'
    assert np.array_equal(new[~reach], frozen_levels[~reach])
    from lpk.stages.view import load_image
    saved = load_image(rep['files'][0])
    assert np.array_equal(np.rint(saved[::-1] * 255).astype(np.uint8)[..., :3], new[..., :3]), 'the PNG is the atlas'
    stage(tex_model, ('bake',))
    assert np.array_equal(texture.image_levels(ATLAS), new), 'a second bake gives the same atlas'
    assert np.array_equal(uvs(body().data), frozen_uv), 'nothing changed the frozen UVs'

    note('rig and export')
    stage(tex_model, ('rig',))
    check_export(stage(tex_model, ('export',))['export'], 'frozen texture')

    note('the build stamp guards the UVs; a mesh freeze keeps them')
    shift_part_uvs('hand.L', 0.001)
    msg = raises(stage, tex_model, ('build',))
    assert "UVs were edited by hand" in msg and 'freeze_texture' in msg, msg
    stage(tex_model, ('build',), discard_edits=True)
    assert np.array_equal(uvs(body().data), frozen_uv)
    rep = stage(tex_model, ('freeze',))['freeze']
    assert rep['uv_layer'] == texture.UV_LAYER and rep['reference'] == 'body', rep
    assert np.array_equal(uvs(bpy.data.meshes[FROZEN_MESH]), frozen_uv)

    note('unfreeze_texture: the frozen texture removed, the procedural stages back')
    rep = stage(tex_model, ('unfreeze_texture',))['unfreeze_texture']
    note('  unfreeze_texture:', rep)
    assert rep['removed'] == {'image': FROZEN_IMAGE, 'uv_layer': texture.UV_LAYER}, rep
    assert 'lost' in rep['lost'] and 'TEXTURE_FROZEN = False' in rep['texture_next']
    assert bpy.data.images.get(FROZEN_IMAGE) is None and texture.UV_LAYER not in bpy.data.meshes[FROZEN_MESH].uv_layers
    assert 'freeze_texture' in raises(stage, tex_model, ('build',))
    stage(belt_model, ('build',))
    r = procedural_texture(belt_model)
    assert 'coverage_total' in r and NAME + '_Belt' in r['reach'], 'the procedural bake bakes every source'
    stage(belt_model, ('rig',))
    export = stage(belt_model, ('export',))['export']
    check_export(export, 'procedural again')
    again = stage(belt_model, ('unfreeze_texture',))['unfreeze_texture']
    assert again['removed'] == {'image': None, 'uv_layer': None} and again['lost'].startswith('nothing')

    note('adopt: the exported GLB with its atlas, re-imported')
    original = palette_shares(body())
    glb = export['glb_generic']['path']
    for o in [o for o in bpy.data.objects if o.name == NAME or o.name.startswith(NAME + '_')]:
        bpy.data.objects.remove(o, do_unlink=True)
    bpy.data.meshes.remove(bpy.data.meshes[FROZEN_MESH])
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=glb, merge_vertices=True)
    imported = [o for o in bpy.data.objects if o not in before]
    mesh = next(o for o in imported if o.type == 'MESH' and o.name == NAME)
    mesh.name = 'Foreign'
    for o in imported:
        if o.type == 'ARMATURE':
            o.name = 'ForeignRig'
    M = run.load(model)
    P = M.props()
    head = mesh.vertex_groups.new(name='head')
    head.add([v.index for v in mesh.data.vertices if (mesh.matrix_world @ v.co).z > P['chin_z'] + 0.02], 1.0, 'REPLACE')
    adopt_model = os.path.join(folder, 'mannequin_adopt.py')
    write(adopt_model, source + "\nFROZEN = True\nTEXTURE_FROZEN = True\nADOPT = 'Foreign'\n")
    rep = stage(adopt_model, ('adopt',))['adopt']
    note('  adopt:', {k: rep[k] for k in ('vertices', 'faces', 'pal', 'texture', 'texture_mode')})
    assert rep['texture'] is not None and rep['texture']['stored']['packed'], rep['texture']
    assert rep['pal']['texture'] == rep['faces'] and rep['pal']['first'] == 0, rep['pal']
    assert texture.UV_LAYER in bpy.data.meshes[FROZEN_MESH].uv_layers
    stored_uv = uvs(bpy.data.meshes[FROZEN_MESH])
    stored_levels = texture.image_levels(FROZEN_IMAGE)
    built = stage(adopt_model, ('build',))['build']
    assert built['texture_frozen']
    adopted = palette_shares(body())
    spread = sum(abs(adopted.get(k, 0.0) - original.get(k, 0.0)) for k in set(adopted) | set(original)) / 2
    note('  palette shares, original:', {k: round(v, 3) for k, v in sorted(original.items())})
    note('  palette shares, adopted: ', {k: round(v, 3) for k, v in sorted(adopted.items())}, 'spread', round(spread, 3))
    assert spread < 0.1, spread
    assert np.array_equal(uvs(body().data), stored_uv), 'the build restores the adopted UVs'
    assert 'unfreeze_texture' in raises(stage, adopt_model, ('unwrap',))
    r = stage(adopt_model, ('bake', 'rig'))['bake']['report']
    assert r['sources'] == {} and r['changed'] == 0, 'without over sources the atlas is the adopted image'
    assert np.array_equal(texture.image_levels(ATLAS), stored_levels)
    check_export(stage(adopt_model, ('export',))['export'], 'adopted texture')
    shutil.rmtree(work, ignore_errors=True)
    print('\nall frozen-texture checks passed')


if __name__ == '__main__':
    main()
