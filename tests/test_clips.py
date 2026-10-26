"""Host tests (no Blender) of the pure parts of the clip review (lpk.stages.clips): the fitted rotation
that turns a clip into the rig's frame, the bone map's problems and the tail's sway.

python tests/test_clips.py"""
import importlib
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from blender_stand_ins import stand_ins  # noqa: E402

with stand_ins():
    sys.modules['mathutils'].Quaternion = object
    clips = importlib.import_module('lpk.stages.clips')


def _raises(exc, fn, *args, **kw):
    try:
        fn(*args, **kw)
    except exc as e:
        return str(e)
    raise AssertionError('%s not raised' % exc.__name__)


def test_fit_rotation_turns_directions_onto_their_partners():
    dirs = [(0.0, 0.0, 1.0), (0.0, 0.0, -1.0), (1.0, 0.0, 0.0), (0.6, 0.0, -0.8)]
    turn = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], dtype=np.float64)   # 90 degrees about X
    pairs = [(tuple(turn.T @ np.array(d)), d) for d in dirs]
    r = np.array(clips.fit_rotation(pairs))
    assert np.allclose(r, turn, atol=1e-9), r
    assert np.isclose(np.linalg.det(r), 1.0), 'a rotation, never a reflection'
    same = clips.fit_rotation([(d, d) for d in dirs])
    assert np.allclose(same, np.eye(3), atol=1e-9), 'a clip already in the frame turns by nothing'
    assert clips.fit_rotation([]) == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]


def test_map_problems_name_each_fault():
    rig, clip = {'Hips', 'Spine', 'Head'}, {'c-hips', 'c-spine'}
    assert clips.map_problems({'Hips': ('c-hips', 'delta'), 'Spine': ('c-spine', 'dir')}, rig, clip, 'Hips') == []
    found = clips.map_problems({'Spine': ('c-neck', 'twist'), 'Tail': ('c-hips', 'delta'), 'Head': 'c-head'},
                               rig, clip, 'Hips')
    text = '\n'.join(found)
    for needle in ("no bone 'c-neck'", "'twist'", "the rig has no bone 'Tail'", "give (clip bone, mode)",
                   "map the rig's root 'Hips'"):
        assert needle in text, (needle, found)


def test_tail_sway_turns_the_chain_alone_with_a_lag():
    sway = clips.tail_sway(prefix='Tail.', period=1.0, amp=10.0, lag=0.5, lift=0.0)
    assert sway('Spine', 0.3) is None and sway('Tail.x', 0.3) is None
    one, two = sway('Tail.1', 0.25), sway('Tail.2', 0.25)
    assert math.isclose(one[2], 10.0 * math.sin(2 * math.pi * 0.25 - 0.5))
    assert math.isclose(two[2], 10.0 * math.sin(2 * math.pi * 0.25 - 1.0)) and one[1] == 0.0


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print('ok', name)
