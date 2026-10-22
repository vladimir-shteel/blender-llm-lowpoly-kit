"""Host test of the skill's worked example skills/lowpoly/references/forms/snout-keys.md: the sizes its
views.json gives match the pictures its snout-keys/draw.py drew, and the example's own code, run on that
drawing, gives the readings the example prints for each pass (the second pass prints what it changes).
bpy, bmesh and mathutils are replaced by stand-ins while the code runs; no picture is drawn and nothing is
built.

python tests/test_snout_keys.py"""
import contextlib
import importlib
import json
import math
import os
import re
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORMS = os.path.join(ROOT, 'skills', 'lowpoly', 'references', 'forms')
DOC = os.path.join(FORMS, 'snout-keys.md')
VIEWS = os.path.join(FORMS, 'snout-keys', 'views.json')
FENCE = re.compile(r'^```(\w*)\n(.*?)^```', re.M | re.S)


class _Vector:
    """The part of mathutils.Vector the calibrations and the head readers touch."""

    def __init__(self, seq=(0.0, 0.0, 0.0)):
        self.v = [float(c) for c in seq]

    x = property(lambda s: s.v[0])
    y = property(lambda s: s.v[1])
    z = property(lambda s: s.v[2])

    def __iter__(self):
        return iter(self.v)

    def __len__(self):
        return len(self.v)

    def __getitem__(self, i):
        return self.v[i]


@contextlib.contextmanager
def _blender_stand_ins():
    """bpy, bmesh and mathutils stand-ins for the module-level imports, and lpk as a bare package over its
    folder; sys.modules is restored afterwards."""
    stand_ins = ('bpy', 'bmesh', 'mathutils', 'mathutils.bvhtree')
    ours = lambda name: name in stand_ins or name == 'lpk' or name.startswith('lpk.')
    saved = {k: v for k, v in sys.modules.items() if ours(k)}
    for k in saved:
        del sys.modules[k]
    mathutils = types.ModuleType('mathutils')
    mathutils.Vector, mathutils.Matrix = _Vector, type('Matrix', (), {})
    bvhtree = types.ModuleType('mathutils.bvhtree')
    bvhtree.BVHTree = type('BVHTree', (), {})
    lpk = types.ModuleType('lpk')
    lpk.__path__ = [os.path.join(ROOT, 'lpk')]
    sys.modules.update({'bpy': types.ModuleType('bpy'), 'bmesh': types.ModuleType('bmesh'), 'mathutils': mathutils,
                        'mathutils.bvhtree': bvhtree, 'lpk': lpk})
    try:
        yield
    finally:
        for k in [k for k in sys.modules if ours(k)]:
            del sys.modules[k]
        sys.modules.update(saved)


def _fences():
    with open(DOC, encoding='utf-8') as f:
        return [(lang, body) for lang, body in FENCE.findall(f.read())]


def _run():
    """The example's code run on its drawing: {pass name: what head_keys returns}."""
    code = next(body for lang, body in _fences() if lang == 'python' and 'def head_keys' in body)
    with _blender_stand_ins():
        views = importlib.import_module('lpk.core.views')
        ns = {}
        exec(compile(code, DOC, 'exec'), ns)
        v = views.Views(VIEWS)
        problems = [(n, views.image_size(v.image(n)), v.size(n)) for n in v.names
                    if views.image_size(v.image(n)) != v.size(n)]
        return problems, {name: ns['head_keys'](v, ns[name]) for name in ('FIRST', 'SECOND')}


PROBLEMS, RUNS = _run()


def _round(x):
    return round(x, 4)


def test_the_views_give_the_sizes_of_the_drawn_pictures():
    assert not PROBLEMS, PROBLEMS


def test_each_pass_gives_the_readings_the_example_prints():
    printed = [json.loads(body) for lang, body in _fences() if lang == 'json']
    assert [p['pass'] for p in printed] == ['FIRST', 'SECOND'], printed
    # The second pass prints only what changed; its keys, centre and apexes are the first pass's.
    printed[1] = dict(printed[0], **printed[1])
    for want in printed:
        got = RUNS[want['pass']]
        assert [_round(c) for c in got['centre']] == want['centre'], (want['pass'], list(got['centre']))
        assert [_round(c) for c in got['nose']] == want['nose'] and [_round(c) for c in got['skull']] == want['skull']
        assert _round(got['eye_height']) == want['eye_height']
        assert [[_round(c) for c in k[:4]] for k in got['keys']] == want['keys'], (want['pass'], got['keys'])
        largest = got['envelope']['largest']
        assert {k: largest[k] for k in ('py', 'px', 'from')} == want['largest'], (want['pass'], largest)
        jaw = max(abs(r['px']) for r in got['envelope']['rows'] if r['px'] is not None and r['py'] >= 160)
        assert math.isclose(jaw, want['jaw_px']), (want['pass'], jaw)


def test_the_second_pass_brings_the_jaw_to_the_drawing():
    jaw = {name: max(abs(r['px']) for r in run['envelope']['rows'] if r['px'] is not None and r['py'] >= 160)
           for name, run in RUNS.items()}
    assert jaw['SECOND'] < jaw['FIRST'] / 3, jaw
    assert RUNS['FIRST']['envelope']['largest']['from'] == 2, 'the crown key sets the jaw rows before the change'


if __name__ == '__main__':
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print('ok     ', name)
            except Exception as e:
                failed += 1
                print('FAILED ', name, type(e).__name__, e)
    sys.exit(1 if failed else 0)
