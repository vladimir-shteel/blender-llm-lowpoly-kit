"""Host tests of lpk.core.edits (no Blender needed: bpy, bmesh and mathutils are replaced by the stand-ins of
blender_stand_ins while the modules are imported): a captured edit replays on the next build of the same
part, offsets add up over captures and scale with the unit, moves that no part keeps are reported, an
entry whose count, topology or unit no longer fits raises naming the part, the topology key ignores the
face order, and the edit file is plain sorted JSON with LF line ends.

python tests/test_edits.py"""
import importlib
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from blender_stand_ins import stand_ins as _blender_stand_ins  # noqa: E402

with _blender_stand_ins():
    builder = importlib.import_module('lpk.core.builder')
    edits = importlib.import_module('lpk.core.edits')

PALETTE = {'skin': (0.8, 0.6, 0.5)}
CORNERS = [(i, j, k) for i in (-1, 1) for j in (-1, 1) for k in (-1, 1)]
QUADS = (((-1, -1, -1), (-1, 1, -1), (-1, 1, 1), (-1, -1, 1)), ((1, -1, -1), (1, -1, 1), (1, 1, 1), (1, 1, -1)),
         ((-1, -1, -1), (-1, -1, 1), (1, -1, 1), (1, -1, -1)), ((-1, 1, -1), (1, 1, -1), (1, 1, 1), (-1, 1, 1)),
         ((-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1)), ((-1, -1, 1), (-1, 1, 1), (1, 1, 1), (1, -1, 1)))


def _raises(exc, fn, *args, **kw):
    try:
        fn(*args, **kw)
    except exc as e:
        return str(e)
    raise AssertionError('%s not raised' % exc.__name__)


def _box(b, part, centre, half, quads=QUADS):
    pid = b.pid(part)
    vs = {c: b.vert(tuple(m + s * h for m, s, h in zip(centre, c, half)), pid) for c in CORNERS}
    for q in quads:
        b.face([vs[k] for k in q], 'skin')


def _build(data, P, unit=1.0, quads=QUADS):
    """A body of two boxes, the edits applied to 'head' only; the positions of every vertex in mesh order."""
    b = builder.Builder(PALETTE)
    _box(b, 'trunk', (0.0, 0.0, 1.0), (0.2, 0.1, 0.3))
    _box(b, 'head', (0.0, 0.0, 1.5), (0.1, 0.1, 0.1), quads)
    moved = edits.apply(b, P, 'head', data, unit=unit, unit_name='head')
    return b, moved, [tuple(v.co) for v in b.bm.verts]


def test_a_captured_edit_replays_on_the_next_build():
    P = {}
    _, moved, generated = _build({}, P)
    assert moved == 0 and set(P[edits.REFS]) == {'head'} and P[edits.REFS]['head']['count'] == 8
    edited = list(generated)
    edited[9] = (edited[9][0] + 0.01, edited[9][1], edited[9][2])        # head vertex 1
    edited[2] = (edited[2][0], edited[2][1], edited[2][2] + 0.02)        # a trunk vertex: no part keeps it
    data = {}
    report = edits.capture_positions(edited, generated, P[edits.REFS], data)
    assert report == {'parts': {'head': 1}, 'moved': 2, 'untracked': 1, 'stored': {'head': 1}}, report
    entry = data['head']
    assert entry['count'] == 8 and entry['unit'] == 'head' and list(entry['deltas']) == ['1']
    assert abs(entry['deltas']['1'][0] - 0.01) < 1e-12 and entry['deltas']['1'][1:] == [0.0, 0.0]
    again = {}
    b, moved, rebuilt = _build(data, again)
    assert moved == 1 and rebuilt[9] == edited[9] and rebuilt[:8] == generated[:8], 'the head edit, nothing else'
    # a second capture on the replayed build adds to the offset already stored
    edited = list(rebuilt)
    edited[9] = (edited[9][0] + 0.01, edited[9][1], edited[9][2])
    edits.capture_positions(edited, rebuilt, again[edits.REFS], data)
    assert abs(data['head']['deltas']['1'][0] - 0.02) < 1e-12
    # a capture with nothing moved since keeps the stored offsets and says so
    report = edits.capture_positions(list(rebuilt), list(rebuilt), again[edits.REFS], data)
    assert report['parts'] == {'head': 0} and report['stored'] == {'head': 1}


def test_offsets_scale_with_the_unit():
    P = {}
    _, _, generated = _build({}, P, unit=0.5)
    edited = list(generated)
    edited[8] = (edited[8][0], edited[8][1] - 0.01, edited[8][2])
    data = {}
    edits.capture_positions(edited, generated, P[edits.REFS], data)
    assert abs(data['head']['deltas']['0'][1] + 0.02) < 1e-12, 'stored in units of 0.5 m'
    _, _, rebuilt = _build(data, {}, unit=2.0)
    assert abs(rebuilt[8][1] - (generated[8][1] - 0.04)) < 1e-12, 'replayed at the unit of this build'


def test_an_entry_that_no_longer_fits_raises_naming_the_part():
    P = {}
    _, _, generated = _build({}, P)
    edited = list(generated)
    edited[10] = (edited[10][0], edited[10][1], edited[10][2] + 0.01)
    data = {}
    edits.capture_positions(edited, generated, P[edits.REFS], data)
    assert _build(data, {}, quads=QUADS[1:] + QUADS[:1])[1] == 1, 'the same faces in another order: the key holds'
    rewound = (QUADS[0][::-1],) + QUADS[1:]
    assert "'head'" in _raises(ValueError, _build, data, {}, quads=rewound), 'another winding is another topology'
    short = dict(data, head=dict(data['head'], count=7))
    assert "'head'" in _raises(ValueError, _build, short, {})
    other = dict(data, head=dict(data['head'], unit='m'))
    assert "'head'" in _raises(ValueError, _build, other, {})
    assert edits.conflict({'count': 8}, 8, 'k') == 'topology'


def test_capture_refuses_meshes_of_different_vertex_counts():
    assert 'topology' in _raises(ValueError, edits.capture_positions, [(0, 0, 0)], [(0, 0, 0), (1, 0, 0)], {}, {})


def test_the_edit_file_is_sorted_json_with_lf_line_ends():
    data = {'z': {'count': 1, 'deltas': {'0': [0.1, 0.0, 0.0]}, 'topology': 'k', 'unit': 'm'}, 'a': {}}
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'edits.json')
        assert edits.load(path) == {}
        edits.save(path, data)
        raw = open(path, 'rb').read()
        assert b'\r' not in raw and raw.endswith(b'\n')
        assert raw.decode('utf-8') == json.dumps(data, indent=1, sort_keys=True) + '\n'
        assert edits.load(path) == data


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print('ok', name)
