"""The operations on a whole part in Blender (background mode): the worked example
built, frozen and switched to the frozen mode, then each runner operation on one part, each stored as the
frozen mesh by its call: hand.L moved and scaled (a separate shell: nothing else moves), arm.L turned with
a falloff of two rings (the trunk round the armhole follows, the seam stays closed), the head replaced by
the module's recipe after a head number changed, the hair decimated to half its faces, foot.L subdivided,
the trunk smoothed with its border pinned. The mesh is checked after each: no open or non-manifold edge
added, no face of no area, the part count and the build stamp kept. Decimate and subdivide are run twice
from the same frozen mesh and compared. Then build (frozen), unwrap, packs, bake, rig and export, every
re-import without diffs; and every operation refused in the parametric mode.

Not a host test (the host loop runs tests/test_*.py): run it in Blender,

    blender -b --python-exit-code 1 --python tests/blender/zone_ops.py

It works on a copy of examples/mannequin in a temporary folder and prints a short summary; any failed
check raises."""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy

import numpy as np

from frozen_mode import check_export, note, pipeline, raises
from lpk import run
from lpk.core import builder
from lpk.stages import zones

NAME = 'Mannequin'
FROZEN_NAME = NAME + '_Frozen'
PARAMETRIC = 'zone operations change the frozen mesh: freeze the model first (FROZEN = True)'


def body():
    return bpy.data.objects[NAME]


def health(me):
    """(open edges, non-manifold edges, faces under DEGENERATE_M2) of a mesh."""
    A = zones.read(me)
    count = {}
    for p in A['polys']:
        for k in range(len(p)):
            e = (min(p[k], p[(k + 1) % len(p)]), max(p[k], p[(k + 1) % len(p)]))
            count[e] = count.get(e, 0) + 1
    degenerate = sum(1 for p in me.polygons if p.area < builder.DEGENERATE_M2)
    return sum(1 for c in count.values() if c == 1), sum(1 for c in count.values() if c > 2), degenerate


def part_of(A, names, part):
    return np.flatnonzero(A['part'] == names.index(part))


def stored(rep, before_health):
    """The checks every operation's call meets: the body stored as the frozen mesh (same topology and
    zones) and stamped, triangles only, the part list kept, no open or non-manifold edge and no face of no
    area added."""
    ob = body()
    A, F = zones.read(ob.data), zones.read(bpy.data.meshes[FROZEN_NAME])
    assert zones.edited(NAME) is None, 'the call stamps the body'
    assert zones.topology_key(len(A['co']), A['loop_total'], A['loop_vert']) == \
        zones.topology_key(len(F['co']), F['loop_total'], F['loop_vert'])
    assert (A['part'] == F['part']).all() and (A['pal'] == F['pal']).all() and np.allclose(A['co'], F['co'])
    assert all(len(p.vertices) == 3 for p in ob.data.polygons)
    assert rep['freeze']['far'] == {} and rep['freeze']['triangulated'] == 0, rep['freeze']
    h = health(ob.data)
    assert h[0] <= before_health[0] and h[1] == 0 and h[2] == 0, (h, before_health)
    assert list(bpy.data.meshes[FROZEN_NAME]['parts']) == list(ob['parts'])
    shown = {k: rep[k] for k in rep if k != 'freeze'}
    note('  %s: %s; open/non-manifold/zero-area %s' % (rep['operation'], shown, h))
    return h


def twice(frozen_model, call):
    """Run `call` from the current frozen mesh twice, restoring it in between; returns the first report
    after checking both runs give the same vertex order, positions and zones."""
    keep = bpy.data.meshes[FROZEN_NAME].copy()
    keep.use_fake_user = True
    rep = call()
    first = zones.read(bpy.data.meshes[FROZEN_NAME])
    bpy.data.meshes.remove(bpy.data.meshes[FROZEN_NAME])
    keep.name = FROZEN_NAME
    run.model(frozen_model, ('build',))
    call()
    second = zones.read(bpy.data.meshes[FROZEN_NAME])
    for k in ('co', 'loop_vert', 'part', 'pal', 'join_loop'):
        assert np.array_equal(first[k], second[k]), 'the %s of two runs differ' % k
    return rep


def main():
    work = tempfile.mkdtemp(prefix='lpk_zoneops_')
    folder = os.path.join(work, 'mannequin')
    shutil.copytree(os.path.join(ROOT, 'examples', 'mannequin'), folder,
                    ignore=shutil.ignore_patterns('out', '__pycache__', '*.blend', 'edits.json'))
    model = os.path.join(folder, 'mannequin.py')
    with open(model, encoding='utf-8') as f:
        source = f.read()
    frozen_model = os.path.join(folder, 'mannequin_frozen.py')

    def write_frozen(text):
        with open(frozen_model, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text + '\n# The frozen mode: build copies Mannequin_Frozen.\nFROZEN = True\n')
    write_frozen(source)

    note('parametric build, freeze, frozen build')
    run.model(model, ('build',))
    for call in (lambda: run.transform(model, 'hand.L', translate=(0.01, 0, 0)),
                 lambda: run.replace(model, 'head'), lambda: run.decimate(model, 'hair', 0.5),
                 lambda: run.subdivide(model, 'foot.L'), lambda: run.smooth(model, 'trunk')):
        assert raises(call) == PARAMETRIC
    run.model(model, ('freeze',))
    assert run.model(frozen_model, ('build',))['build']['frozen']
    names = list(body()['parts'])
    h = health(body().data)
    note('  body: open/non-manifold/zero-area', h)
    msg = raises(run.transform, frozen_model, 'tail')
    assert "no part 'tail'" in msg and 'hand.L' in msg and 'trunk' in msg, msg
    msg = raises(run.replace, frozen_model, 'arm.L')
    assert 'welded to trunk' in msg, msg
    assert raises(run.decimate, frozen_model, 'hair', 0) and raises(run.subdivide, frozen_model, 'hair', 0)

    note('transform hand.L: a separate shell moves alone')
    A = zones.read(body().data)
    rep = run.transform(frozen_model, 'hand.L', translate=(0.01, 0.0, -0.005), scale=1.15, pivot='base')
    h = stored(rep, h)
    B = zones.read(body().data)
    hand = part_of(A, names, 'hand.L')
    rest = np.setdiff1d(np.arange(len(A['co'])), hand)
    assert rep['neighbours_moved'] == {} and np.array_equal(A['co'][rest], B['co'][rest])
    assert np.linalg.norm(B['co'][hand] - A['co'][hand], axis=1).min() > 0
    lo = A['co'][hand][:, 2].min()
    assert abs(B['co'][hand][:, 2].min() - (lo - 0.005)) < 1e-5, 'the base pivot keeps the lowest point'

    note('transform arm.L with falloff 2: the trunk round the armhole follows')
    A = zones.read(body().data)
    rep = run.transform(frozen_model, 'arm.L', rotate=(0.0, 8.0, 0.0), falloff=2)
    h = stored(rep, h)
    B = zones.read(body().data)
    moved = np.linalg.norm(B['co'] - A['co'], axis=1) > 0
    trunk = A['part'] == names.index('trunk')
    assert rep['neighbours_moved'] == {'trunk': int((moved & trunk).sum())} and (moved & trunk).any()
    rings = zones.ring_distances(len(A['co']), A['edges'], part_of(A, names, 'arm.L'), 3)
    assert set(rings[moved & trunk].tolist()) <= {1, 2} and not (moved & (rings == 3)).any()
    assert moved[part_of(A, names, 'arm.L')].all() and not moved[A['part'] == names.index('arm.R')].any()

    note('replace head by the recipe after a head number changed')
    # A new length, too: a module rewritten within the same second at the same size reads its stale bytecode.
    write_frozen(source.replace('NOSE = 0.006', 'NOSE = 0.0140'))
    A = zones.read(body().data)
    rep = run.replace(frozen_model, 'head')
    h = stored(rep, h)
    B = zones.read(body().data)
    assert rep['part_vertices'][0] == rep['part_vertices'][1] and rep['max_displacement_cm'] > 0.5, rep
    assert list(body()['parts']) == names and len(set(B['part'].tolist())) == len(set(A['part'].tolist()))
    assert zones.welded_parts(B['edges'], B['part'], names.index('head')) == [], 'the head stays a shell'
    head_old, head_new = A['co'][part_of(A, names, 'head')], B['co'][part_of(B, names, 'head')]
    assert np.abs(head_new - head_old).max() > 0.005, 'the head took the new shape'
    rest = np.flatnonzero(A['part'] != names.index('head'))
    assert np.array_equal(B['co'][:len(rest)], A['co'][rest]), 'the rest keeps its order and places'

    note('decimate hair 0.5, run twice from the same frozen mesh')
    rep = twice(frozen_model, lambda: run.decimate(frozen_model, 'hair', 0.5))
    h = stored(rep, h)
    assert rep['part_faces'][1] <= rep['target_faces'] + 1 and rep['max_displacement_cm'] == 0.0, rep

    note('subdivide foot.L, run twice')
    rep = twice(frozen_model, lambda: run.subdivide(frozen_model, 'foot.L'))
    h = stored(rep, h)
    assert rep['part_faces'][1] > rep['part_faces'][0] and rep['max_displacement_cm'] == 0.0, rep

    note('smooth trunk: its border pinned')
    A = zones.read(body().data)
    tid = names.index('trunk')
    pin = zones.pinned_vertices(A['polys'], A['part'], tid) & (A['part'] == tid)
    rep = run.smooth(frozen_model, 'trunk', iterations=2, factor=0.5)
    h = stored(rep, h)
    B = zones.read(body().data)
    assert pin.any() and np.array_equal(A['co'][pin], B['co'][pin]) and rep['pinned'] == int(pin.sum())
    assert np.array_equal(A['co'][A['part'] != tid], B['co'][A['part'] != tid])

    note('frozen build and the stages after it')
    out = run.model(frozen_model, ('build',))['build']
    assert out['frozen'] and out['body']['degenerate'] == {}, out['body']
    note('  body', out['body']['tris'], 'tris', out['body']['verts'], 'verts')
    check_export(pipeline(frozen_model), 'after the operations')
    shutil.rmtree(work, ignore_errors=True)
    print('\nall zone-operation checks passed')


if __name__ == '__main__':
    main()
