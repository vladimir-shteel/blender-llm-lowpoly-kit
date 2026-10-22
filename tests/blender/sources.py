"""The colour sources on the frozen surface in Blender (bpy as a Python module, background mode): the worked
example built, frozen and switched to the frozen mode; a frozen build of the unchanged body leaves every
source where the parametric build put it; then the head moved forward and scaled and the trunk widened
with a falloff (run.transform), and a frozen build carries the Face and Trousers sources onto the reshaped
parts: the bake reaches every source vertex, the face moves about as far as the head's front did, and two
builds give the same sources. The same edit with 'conform': False on Face leaves the face under the head's
new surface, out of the bake's reach. The sources live in '<NAME>_Sources' under '<NAME>', excluded from
the view layer, and neither export carries them.

Not a host test (the host loop runs tests/test_*.py): run it where bpy imports,

    python3 tests/blender/sources.py

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

from frozen_mode import check_export, note
from lpk import run
from lpk.core import builder
from lpk.stages import texture as texture_mod, zones

NAME = 'Mannequin'
SOURCES = (NAME + '_Face', NAME + '_Trousers')
HEAD_SHIFT = (0.0, -0.02, 0.0)
HEAD_SCALE = 1.15
TRUNK_SCALE = (1.12, 1.2, 1.0)


def co(name):
    return zones.read(bpy.data.objects[name].data)['co']


def texture(model):
    """unwrap, packs until settled (at most 9), bake; returns the bake's report."""
    packs = run.model(model, ('unwrap',) + ('pack',) * 3)['pack']
    for _ in range(2):
        if packs[-1]['settled']:
            break
        packs = run.model(model, ('pack',) * 3)['pack']
    return run.model(model, ('bake',))['bake']['report']


def misses(reach):
    return {k: (len(r['beyond']), len(r['deep'])) for k, r in reach.items()}


def write(path, text):
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)


def check_collections():
    top, coll = bpy.data.collections[NAME], bpy.data.collections[NAME + '_Sources']
    assert coll.name in top.children and coll not in list(bpy.context.scene.collection.children), \
        'the sources collection is a child of the model collection only'
    assert sorted(o.name for o in coll.objects) == sorted(SOURCES), [o.name for o in coll.objects]
    for name in (NAME, NAME + '_Rig'):
        ob = bpy.data.objects.get(name)
        assert ob is None or [c.name for c in ob.users_collection] == [NAME], (name, ob.users_collection)
    assert all([c.name for c in bpy.data.objects[s].users_collection] == [coll.name] for s in SOURCES)
    layer = builder.layer_collection(bpy.context.view_layer.layer_collection, coll)
    assert layer.exclude, 'the sources collection is excluded from the view layer'
    shown = {o.name for o in bpy.context.view_layer.objects}
    assert not shown & set(SOURCES), shown & set(SOURCES)


def imported_names(path):
    """The names of the objects importing `path` makes, removed again afterwards."""
    before = set(bpy.data.objects)
    if path.endswith('.glb'):
        bpy.ops.import_scene.gltf(filepath=path)
    else:
        bpy.ops.import_scene.fbx(filepath=path)
    made = [o for o in bpy.data.objects if o not in before]
    names = sorted(o.name for o in made)
    for o in made:
        bpy.data.objects.remove(o, do_unlink=True)
    return names


def main():
    work = tempfile.mkdtemp(prefix='lpk_sources_')
    folder = os.path.join(work, 'mannequin')
    shutil.copytree(os.path.join(ROOT, 'examples', 'mannequin'), folder,
                    ignore=shutil.ignore_patterns('out', '__pycache__', '*.blend', 'edits.json'))
    model = os.path.join(folder, 'mannequin.py')
    with open(model, encoding='utf-8') as f:
        source = f.read()
    frozen_model = os.path.join(folder, 'mannequin_frozen.py')
    write(frozen_model, source + '\n# The frozen mode: build copies Mannequin_Frozen.\nFROZEN = True\n')
    line = "SOURCES = {'Trousers': {'mask': ('trunk',)}, 'Face': {'mask': ('head',)}}"
    assert line in source
    fixed_model = os.path.join(folder, 'mannequin_fixed.py')
    write(fixed_model, source.replace(line, "SOURCES = {'Trousers': {'mask': ('trunk',)}, "
                                            "'Face': {'mask': ('head',), 'conform': False}}")
          + '\nFROZEN = True\n')

    note('parametric build: the sources in their own collection')
    built = run.model(model, ('build',))['build']
    assert 'conform' not in built, 'the parametric build conforms nothing'
    check_collections()
    parametric = {s: co(s) for s in SOURCES}
    run.model(model, ('build',))
    check_collections()

    note('frozen build of the unchanged body: no source moves')
    run.model(model, ('freeze',))
    out = run.model(frozen_model, ('build',))['build']
    note('  conform:', out['conform'])
    for key in ('Face', 'Trousers'):
        r = out['conform'][key]
        assert r['moved'] == 0 and r['unmatched'] == 0 and r['outside_reach'] == 0, (key, r)
    for s in SOURCES:
        assert np.array_equal(co(s), parametric[s]), s
    check_collections()

    note('reshape: the head forward and larger, the trunk wider and deeper')
    head_before = zones.read(bpy.data.objects[NAME].data)
    rep = run.transform(frozen_model, 'head', translate=HEAD_SHIFT, scale=HEAD_SCALE)
    note('  head moved, max cm', rep['max_displacement_cm'])
    rep = run.transform(frozen_model, 'trunk', scale=TRUNK_SCALE, falloff=2)
    note('  trunk moved, max cm', rep['max_displacement_cm'], 'neighbours', rep['neighbours_moved'])
    head_after = zones.read(bpy.data.objects[NAME].data)

    note('frozen build: the sources follow')
    out = run.model(frozen_model, ('build',))['build']
    note('  conform:', out['conform'])
    face, trousers = out['conform']['Face'], out['conform']['Trousers']
    assert face['moved'] == face['vertices'] and trousers['moved'] > 0, out['conform']
    assert face['unmatched'] == 0 and trousers['unmatched'] == 0
    # The face's expected shift: how far the head's vertices nearest each face vertex moved.
    names = list(bpy.data.objects[NAME]['parts'])
    head = np.flatnonzero(head_before['part'] == names.index('head'))
    shift = np.linalg.norm(co(SOURCES[0]) - parametric[SOURCES[0]], axis=1)
    near = np.array([head[np.argmin(np.linalg.norm(head_before['co'][head] - p, axis=1))]
                     for p in parametric[SOURCES[0]]])
    head_shift = np.linalg.norm(head_after['co'][near] - head_before['co'][near], axis=1)
    note('  face shift cm: median %.2f (the head under it %.2f), max %.2f (%.2f)'
         % (np.median(shift) * 100, np.median(head_shift) * 100, shift.max() * 100, head_shift.max() * 100))
    assert abs(np.median(shift) - np.median(head_shift)) < 0.15 * np.median(head_shift)
    assert abs(face['max_shift_cm'] - shift.max() * 100) < 0.01
    first = {s: co(s) for s in SOURCES}
    marks = bpy.data.objects[SOURCES[0]].get(texture_mod.MARKS)
    run.model(frozen_model, ('build',))
    for s in SOURCES:
        assert np.array_equal(co(s), first[s]), 'two frozen builds give the same %s' % s
    assert bpy.data.objects[SOURCES[0]].get(texture_mod.MARKS) == marks
    assert bpy.data.objects.get(NAME + '_SourceRef') is None and bpy.data.meshes.get(NAME + '_SourceRef') is None

    note('unwrap, packs, bake: every source vertex within reach')
    bake = texture(frozen_model)
    note('  reach (beyond, deep):', misses(bake['reach']))
    for s in SOURCES:
        r = bake['reach'][s]
        assert r['beyond'] == [] and r['deep'] == [], (s, r)
    eyes = bake['texels']['eyes']
    assert eyes and all(e['part'] == 'head' for e in eyes), eyes
    check_collections()

    note('rig and export: no source in the files')
    rep = run.model(frozen_model, ('rig', 'export'))['export']
    check_export(rep, 'conformed')
    check_collections()
    for profile, r in rep.items():
        path = r['path']
        got = imported_names(path)
        note('  %s re-imported: %s' % (profile, got))
        assert not [g for g in got if any(g.startswith(s) for s in SOURCES)], got

    note("the same edit with 'conform': False on Face")
    out = run.model(fixed_model, ('build',))['build']
    assert out['conform']['Face'] is None and out['conform']['Trousers']['moved'] > 0, out['conform']
    assert np.array_equal(co(SOURCES[0]), parametric[SOURCES[0]]), 'the face stays where it was built'
    bake = texture(fixed_model)
    reach = misses(bake['reach'])
    note('  reach (beyond, deep):', reach)
    assert sum(reach[SOURCES[0]]) > 0 and reach[SOURCES[1]] == (0, 0), reach

    shutil.rmtree(work, ignore_errors=True)
    print('\nall colour-source checks passed')


if __name__ == '__main__':
    main()
