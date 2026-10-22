"""A prop end to end in Blender (bpy as a Python module, background mode): the barrel example from its
blocks to its export without a rig. Its stages run in the calls the example's docstring gives; the rig
stage refuses a model without SKELETON; the single pack of a model without a face island is settled; both
exports come back with no armature, no bone and no difference; and a second clean build and export gives
the same bytes. Captures need Blender's user interface and are not run.

Not a host test (the host loop runs tests/test_*.py): run it where bpy imports,

    python3 tests/blender/prop.py

It works on a copy of examples/barrel in a temporary folder and prints a short summary; any failed check
raises."""
import hashlib
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

try:
    import bpy
except ImportError:
    print('skipped: bpy does not import here (pip install bpy, or run inside Blender)')
    sys.exit(0)

from lpk import run

NAME = 'Barrel'


def digest(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def export_once(model):
    """Every stage from the blocks to the export, in the example's calls, without the pack cache. Returns
    {profile: the export's digest}."""
    cache = os.path.join(os.path.dirname(model), 'out', NAME + '.pack.json')
    if os.path.exists(cache):
        os.remove(cache)
    rep = run.model(model, stages=('reference', 'blocks'))
    assert rep['blocks']['tris'] > 0
    rep = run.model(model, stages=('build', 'unwrap', 'pack'))
    print('  build:', rep['build']['body']['tris'], 'triangles', rep['build']['body']['by_part'])
    assert [p['settled'] for p in rep['pack']] == [True], 'without a face island the first pack is final'
    assert NAME + '_Rig' not in bpy.data.objects
    try:
        run.model(model, stages=('rig',))
    except AttributeError as e:
        assert 'SKELETON' in str(e), e
    else:
        raise AssertionError('rig ran on a model without SKELETON')
    rep = run.model(model, stages=('bake', 'preview', 'export'))
    out = {}
    for profile, r in rep['export'].items():
        back = r['reimport']
        print('  %s: %d bytes, %d triangles back, diffs %s' % (profile, r['bytes'], back['triangles'], back['diffs']))
        assert back['diffs'] == [] and back['bones'] == 0 and r['renamed'] == {}, (profile, back)
        out[profile] = digest(r['path'])
    return out


def main():
    work = tempfile.mkdtemp(prefix='lpk_prop_')
    folder = os.path.join(work, 'barrel')
    shutil.copytree(os.path.join(ROOT, 'examples', 'barrel'), folder,
                    ignore=shutil.ignore_patterns('out', '__pycache__'))
    model = os.path.join(folder, 'barrel.py')
    first = export_once(model)
    second = export_once(model)
    assert first == second, 'a clean rebuild gives other export bytes: %s %s' % (first, second)
    shutil.rmtree(work, ignore_errors=True)
    print('\nall prop checks passed')


if __name__ == '__main__':
    main()
