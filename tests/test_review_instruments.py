"""Host tests of the measurements of lpk.stages.review that compare the build with a drawing and with its
play size: the fit's viewport rotation (lpk.stages.view.rotation), silhouette_report's edges, bands and
widths, a width the drawing shares with other parts, the fit's own error, fit_silhouette recovering a
known yaw and pitch, the landmarks' depths, the pitch limit, a head key's deviation at the read size, and
the plain-argument measurements (outline_diff, concept_fit, play_size) over a stand-in model, on the worked
example's drawing too (no Blender needed: bpy and mathutils are replaced by stand-ins while the modules are
imported, the mathutils stand-in turns vectors with numpy, and the example's pictures are read by a host PNG
reader).

python tests/test_review_instruments.py"""
import contextlib
import importlib
import json
import math
import os
import shutil
import struct
import sys
import tempfile
import types
import zlib

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE = os.path.join(ROOT, 'examples', 'mannequin')


class _Vector(tuple):
    """The part of mathutils.Vector the review module uses at import and in the fits."""

    def __new__(cls, seq=(0.0, 0.0, 0.0)):
        return super().__new__(cls, (float(v) for v in seq))

    x = property(lambda s: s[0])
    y = property(lambda s: s[1])
    z = property(lambda s: s[2])


class _Matrix:
    def __init__(self, a):
        self.a = np.asarray(a, dtype=np.float64)

    def __matmul__(self, v):
        return _Vector(self.a @ np.asarray(v, dtype=np.float64))


def _axis_turn(axis, angle):
    c, s = math.cos(angle), math.sin(angle)
    return {'X': [[1, 0, 0], [0, c, -s], [0, s, c]],
            'Y': [[c, 0, s], [0, 1, 0], [-s, 0, c]],
            'Z': [[c, -s, 0], [s, c, 0], [0, 0, 1]]}[axis]


class _Euler:
    """mathutils.Euler: angles (x, y, z) in radians; the order names the axes in the order their turns
    apply, so 'XYZ' is Rz @ Ry @ Rx and 'ZXY' is Ry @ Rx @ Rz."""

    def __init__(self, angles, order='XYZ'):
        self.angles, self.order = tuple(angles), order

    def to_matrix(self):
        m = np.eye(3)
        for axis in self.order:
            m = np.asarray(_axis_turn(axis, self.angles['XYZ'.index(axis)])) @ m
        return _Matrix(m)


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
    mathutils.Vector, mathutils.Euler, mathutils.Matrix = _Vector, _Euler, _Matrix
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


with _blender_stand_ins():
    review = importlib.import_module('lpk.stages.review')
    view = importlib.import_module('lpk.stages.view')
    checks = importlib.import_module('lpk.stages.checks')
    V = importlib.import_module('lpk.core.views')
    head = importlib.import_module('lpk.forms.head')


def _raises(exc, fn, *args, **kw):
    try:
        fn(*args, **kw)
    except exc as e:
        return str(e)
    raise AssertionError('%s not raised' % exc.__name__)


def _box(lo, hi):
    """(8 corners, 12 triangles) of an axis-aligned box."""
    (x0, y0, z0), (x1, y1, z1) = lo, hi
    co = [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]
    quads = ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3))
    return co, [t for a, b, c, d in quads for t in ((a, b, c), (a, c, d))]


def _figure():
    """(co, tris, tri_part, part names) of a blocky figure 1.7 m tall at the origin: legs, torso, head,
    arms held out at different depths and a nose forward, so its outline differs at each turn and from
    its mirror."""
    boxes = [('leg.L', (0.04, -0.06, 0.0), (0.16, 0.06, 0.8)), ('leg.R', (-0.16, -0.06, 0.0), (-0.04, 0.06, 0.8)),
             ('torso', (-0.2, -0.1, 0.8), (0.2, 0.1, 1.4)), ('head', (-0.1, -0.1, 1.45), (0.1, 0.12, 1.7)),
             ('arm.L', (0.2, -0.2, 1.1), (0.55, -0.08, 1.3)), ('arm.R', (-0.45, 0.02, 0.95), (-0.2, 0.12, 1.35)),
             ('nose', (-0.02, -0.16, 1.52), (0.02, -0.1, 1.58)), ('neck', (-0.05, -0.05, 1.4), (0.05, 0.05, 1.45))]
    co, tris, part = [], [], []
    for k, (name, lo, hi) in enumerate(boxes):
        c, t = _box(lo, hi)
        tris += [[len(co) + i for i in tri] for tri in t]
        part += [k] * len(t)
        co += c
    return np.asarray(co, float), np.asarray(tris), np.asarray(part), [b[0] for b in boxes]


def _drawn(fit, shape=(920, 640)):
    """The figure painted through a fit, and its outline as ink."""
    co, tris, part, names = _figure()
    build = review._paint(co, tris, part, fit, shape)
    return build, build >= 0


TRUE = {'yaw': 30, 'pitch': 8, 's': 500.0, 'ox': 320.0, 'oy': 895.0}


def test_rotation_turns_the_viewport_like_the_fit():
    for yaw, pitch in ((0, 0), (30, 8), (-90, 0), (145, -12), (35, 10)):
        a, b, c = view.rotation(yaw, pitch)
        m = _Euler([math.radians(x) for x in (a, b, c)], 'XYZ').to_matrix().a
        r = review._turn(yaw, pitch).a
        assert np.allclose(m[:, 0], r[0]) and np.allclose(m[:, 1], r[2]), (yaw, pitch)
        assert np.allclose(review._turn_array(yaw, pitch), r), (yaw, pitch)
    for name, (a, b, c) in view.VIEWS.items():
        assert view.rotation(-c, 90 - a) == (a, 0.0, c), name


def _figure_of(ink, build):
    """The drawing's figure: the 8-connected pieces of the ink that the build's outline overlaps."""
    labels, _ = review.imaging.components(ink)
    return np.isin(labels, np.unique(labels[np.asarray(build, bool) & (labels > 0)]))


def _scene():
    """A build (head rows 10-29 over a torso, rows 32-79, a gap between them) and a drawing whose head is
    4 px wider each side, whose torso matches, with a neck in the gap, plus a separate figure."""
    build = np.full((100, 120), -1, np.int32)
    build[10:30, 40:60] = 0
    build[32:80, 30:70] = 1
    ink = np.zeros((100, 120), bool)
    ink[10:30, 36:64] = True
    ink[30:32, 45:55] = True
    ink[32:80, 30:70] = True
    ink[20:90, 100:110] = True
    return build, ink


def test_silhouette_report_points_where_the_build_leaves_the_drawing():
    build, ink = _scene()
    figure = _figure_of(ink, build >= 0)
    assert not figure[:, 100:].any() and figure[30, 50]
    rep = review.silhouette_report(build, figure, ['head', 'torso'])
    assert rep['size'] == [120, 100]
    assert rep['top']['offset'] == 0 and rep['bottom']['offset'] == 0
    edges = {r: (col, left, right) for r, col, left, right in rep['edges']}
    assert edges[15] == (36, -4, -4) and edges[50] == (30, 0, 0) and 30 not in edges
    assert rep['floor'] == {'edge': review.EDGE_PX, 'width': review.EXTENT_PX} and rep['fit_px'] == 0.0
    bands = {(b['side'], tuple(b['rows'])): b for b in rep['bands']}
    assert set(bands) == {('left', (10, 29)), ('right', (10, 29)), ('drawing_only', (30, 31))}
    left = bands[('left', (10, 29))]
    assert (left['offset'], left['mean'], left['part'], left['region']) == (-4, -4.0, 'head', [36, 10, 41, 30])
    tall = rep['height_px']
    assert left['relative'] == round(80 / (20 * 28 / 2), 3) and left['share'] == round(20 / tall, 3), \
        "an edge band's area over half the drawn ink across its rows, its rows over the drawing's height"
    gap = bands[('drawing_only', (30, 31))]
    assert gap['relative'] == round(gap['area'] / (2 * 10), 3), 'a one-sided band over the whole drawn ink'
    assert (rep['top']['relative'], rep['top']['share']) == (0.0, 0.0)
    assert bands[('drawing_only', (30, 31))]['offset'] == 2 and bands[('drawing_only', (30, 31))]['part'] is None
    head, torso = rep['parts']['head'], rep['parts']['torso']
    assert (head['build_px'], head['drawn_px'], head['rows'], head['scale']) == (20, 28, 20, 0.714)
    assert head['region'] == [36, 10, 64, 30]
    assert torso['scale'] == 1.0


def test_silhouette_compares_each_run_with_the_run_it_overlaps():
    names = ['torso', 'arm']
    build = np.full((40, 60), -1, np.int32)
    build[5:35, 20:40] = 0
    build[8:30, 10:16] = 1                      # the arm 4 px off the torso
    ink = np.zeros((40, 60), bool)
    ink[5:35, 20:40] = True
    ink[8:30, 12:20] = True                     # the drawn arm touches the torso
    rep = review.silhouette_report(build, ink, names)
    assert rep['parts']['torso']['scale'] == 1.0, 'the torso is not measured against the arm drawn onto it'
    assert rep['parts']['arm']['scale'] is None, 'the drawn run holds the arm and the torso: not a width'
    bands = {(b['side'], tuple(b['rows'])): b for b in rep['bands']}
    assert set(bands) == {('left', (8, 29)), ('drawing_only', (8, 29))}, bands
    assert bands[('left', (8, 29))]['offset'] == 2 and bands[('left', (8, 29))]['part'] == 'arm'
    gap = bands[('drawing_only', (8, 29))]
    assert gap['width'] == 4 and gap['region'] == [16, 8, 20, 30], 'the gap the drawing closes'
    build = np.full((40, 60), -1, np.int32)
    build[5:20, 20:40] = 0
    build[5:30, 5:9] = 1                        # the hand reaches lower than drawn, beside a drawn leg
    ink = np.zeros((40, 60), bool)
    ink[5:20, 20:40] = True
    ink[5:24, 5:9] = True
    ink[20:35, 25:30] = True
    rep = review.silhouette_report(build, ink, names)
    got = [(b['side'], b['rows'], b['part']) for b in rep['bands']]
    assert got == [('build_only', [24, 29], 'arm'), ('drawing_only', [20, 29], None)], \
        'the hand is never compared with the leg beside it'


def test_silhouette_bands_follow_an_edge_while_its_offset_keeps_its_sign():
    build = np.full((60, 60), -1, np.int32)
    ink = np.zeros((60, 60), bool)
    for r in range(5, 55):                      # a slanted edge, 1 and 2 px past the drawing in turn
        x = 10 + r // 2
        build[r, x - (2 if r % 2 else 1):40] = 0
        ink[r, x:40] = True
    rep = review.silhouette_report(build, ink, ['body'])
    assert [(b['side'], b['rows'], b['offset'], b['mean']) for b in rep['bands']] == [('left', [5, 54], 2, 1.5)]
    legs = np.full((30, 40), -1, np.int32)
    legs[0:10, 10:31] = 0                       # a torso that splits into two legs
    legs[10:20, 10:19] = 1
    legs[10:20, 22:31] = 2
    drawn = legs >= 0
    drawn[10:20, 22:25] = False                 # the right leg's inner edge drawn 3 px further out
    split = review.silhouette_report(legs, drawn, ['torso', 'leg.L', 'leg.R'])
    assert [(b['side'], b['rows'], b['offset'], b['part']) for b in split['bands']] == [
        ('left', [10, 19], 3, 'leg.R')], 'the outer edges go on down the legs; the inner ones start their own'
    loose = review.silhouette_report(build, ink, ['body'], fit_px=1.0)
    noisy = review.silhouette_report(build, ink, ['body'], fit_px=1.0, noise_px=3)
    assert noisy['noise_px'] == 3 and noisy['floor'] == {'edge': review.EDGE_PX + 4.0,
                                                         'width': review.EXTENT_PX + 8.0}
    assert loose['bands'] == [] and loose['floor'] == {'edge': 2.0, 'width': 4.0}, 'within the fit\'s own error'
    assert review.fit_px({'err': [3.0, 4.0]}) == math.sqrt(12.5) and review.fit_px({'err': []}) == 0.0
    assert review.fit_px(None) == 0.0


def test_silhouette_offsets_of_one_pixel_make_no_band_and_a_moved_top_is_measured():
    build = np.full((60, 60), -1, np.int32)
    build[5:50, 20:40] = 0
    ink = np.zeros((60, 60), bool)
    ink[8:50, 19:41] = True
    rep = review.silhouette_report(build, ink, ['body'])
    assert rep['bands'] == [] and rep['top']['offset'] == 3 and rep['top']['region'] == [19, 5, 41, 9]
    assert rep['bottom']['offset'] == 0 and rep['parts']['body']['drawn_px'] - rep['parts']['body']['build_px'] == 2


def test_silhouette_bands_measure_the_pixels_between_the_outlines():
    build = np.full((60, 60), -1, np.int32)
    build[5:55, 20:40] = 0
    ink = np.zeros((60, 60), bool)
    ink[5:55, 20:40] = True
    ink[5:10, 17:20] = True                     # the drawing 3 px wider on the left over 5 rows: 15 px
    ink[30:50, 40:42] = True                    # and 2 px wider on the right over 20 rows: 40 px
    ink[20:24, 28:32] = False                   # a hole the build covers: 16 px
    rep = review.silhouette_report(build, ink, ['body'])
    assert [(b['side'], b['area']) for b in rep['bands']] == [('left', 15), ('right', 40), ('build_only', 16)], \
        'the report keeps the order it finds them in'


def test_a_width_whose_drawn_ink_goes_on_to_another_part_is_not_read():
    names = ['head', 'ear.L', 'nose']
    build = np.full((60, 60), -1, np.int32)
    build[20:50, 20:41] = 0
    build[5:20, 36:43] = 1                      # the ear built short, ending above the head
    build[30:35, 28:33] = 2                     # a nose inside the head's front outline
    ink = np.zeros((60, 60), bool)
    ink[20:50, 20:41] = True
    ink[5:30, 36:45] = True                     # the drawn ear goes on down the head's side
    rep = review.silhouette_report(build, ink, names)
    head = rep['parts']['head']
    assert head['scale'] is None and head['shared'] == ['ear.L'] and head['rows'] == [20, 49], head
    assert head['region'] == [20, 20, 45, 50], head
    own = ink.copy()
    own[20:30, 41:45] = False                   # the drawn ear ends where the head starts
    alone = review.silhouette_report(build, own, names)['parts']['head']
    assert alone['scale'] == 1.0 and 'shared' not in alone, 'the nose inside the head shares nothing'


def test_silhouette_reads_neither_outline_under_an_ignore_region():
    names = ['torso', 'arm']
    build = np.full((40, 60), -1, np.int32)
    build[5:35, 20:40] = 0                      # the torso; the arm is left out (exclude_parts)
    ink = np.zeros((40, 60), bool)
    ink[5:35, 20:40] = True
    ink[8:14, 2:20] = True                      # the arm drawn held out, in another pose than the build's
    ink[20:30, 40:46] = True                    # a bulge the build lacks
    ink[30:34, 5:15] = True                     # a piece of the drawing apart from the torso, by a label
    plain = review.silhouette_report(build, ink, names)
    assert [(b['side'], b['rows'], b['offset']) for b in plain['bands']] == [
        ('left', [8, 13], -18), ('right', [20, 29], -6), ('drawing_only', [30, 33], 4)]
    assert plain['cuts'] == {} and plain['top']['cut'] is None
    ignored = np.zeros((40, 60), np.int32)
    ignored[6:16, 0:20] = 1                     # the arm's region, up to the torso's side
    ignored[28:36, 0:5] = 2                     # the label's region, touching the separate piece
    ignored[0:5, 25:35] = 3                     # a frame line over the crown
    rep = review.silhouette_report(build, ink, names, ignored=ignored, regions=['arm', 'label', 'frame'])
    assert [(b['side'], b['rows'], b['offset']) for b in rep['bands']] == [('right', [20, 29], -6)]
    assert rep['cuts'] == {'arm': {'rows': [6, 15], 'region': [20, 6, 40, 16]},
                           'label': {'rows': [30, 33], 'region': [5, 30, 15, 34]},
                           'frame': {'rows': [5, 5], 'region': [25, 5, 35, 6]}}, rep['cuts']
    assert rep['top']['cut'] == 'frame' and rep['bottom']['cut'] is None
    edges = {r: (left, right) for r, _, left, right in rep['edges']}
    assert edges[10] == (None, 0) and edges[20] == (0, -6)
    assert rep['parts']['torso']['drawn_px'] == 26 and plain['parts']['torso']['drawn_px'] == 44, \
        'a row cut by a region gives no width'
    pic = review.imaging.outline_picture(build >= 0, ink & ~(ignored > 0), ignored > 0)
    assert np.allclose(pic[6, 0, :3], review.imaging.HATCH_COLOR[:3]) and np.allclose(pic[20, 50, :3], 1.0)


def test_fit_silhouette_leaves_an_ignore_region_out_of_the_score():
    co, tris, _, _ = _figure()
    _, ink = _drawn(TRUE)
    q = co @ review._turn_array(TRUE['yaw'], TRUE['pitch']).T
    feet = TRUE['oy'] - TRUE['s'] * q[:, 2].min()
    posed = ink.copy()
    posed[600:900, 400:560] = True              # a limb drawn out to the side, which the mesh lacks
    region = np.zeros_like(ink)
    region[595:905, 405:565] = True
    pulled = review.fit_silhouette(co, tris, posed, TRUE['s'], feet)
    fit = review.fit_silhouette(co, tris, posed, TRUE['s'], feet, ignored=region)
    assert (fit['yaw'], fit['pitch']) == (TRUE['yaw'], TRUE['pitch']), fit
    assert fit['mismatch'] < 0.02 < pulled['mismatch'], (fit['mismatch'], pulled['mismatch'])


def test_fit_silhouette_holds_the_kept_parts_at_their_height_on_the_model():
    co, tris, part, names = _figure()
    build, ink = _drawn(TRUE)
    q = co @ review._turn_array(TRUE['yaw'], TRUE['pitch']).T
    feet = TRUE['oy'] - TRUE['s'] * q[:, 2].min()
    whole = np.unique(tris)
    legs = [names.index('leg.L'), names.index('leg.R')]
    kept = tris[~np.isin(part, legs)]
    dropped = review.fit_silhouette(co, kept, ink, TRUE['s'], feet)
    assert dropped['oy'] > TRUE['oy'] + 300, 'anchored on what is kept, the pelvis drops onto the sole row'
    fit = review.fit_silhouette(co, kept, ink, TRUE['s'], feet, anchor=whole)
    assert (fit['yaw'], fit['pitch']) == (TRUE['yaw'], TRUE['pitch']) and math.isclose(fit['oy'], TRUE['oy']), fit
    assert fit['mismatch'] > 0.2, "the legs' drawn ink is still scored"
    region = review.imaging.grown(np.isin(build, legs))
    both = review.fit_silhouette(co, kept, ink, TRUE['s'], feet, ignored=region, anchor=whole)
    assert (both['yaw'], both['pitch']) == (TRUE['yaw'], TRUE['pitch']) and both['mismatch'] < 0.01, both
    group = [names.index('head'), names.index('nose')]
    rest = review.imaging.grown(ink & ~np.isin(build, group))       # the rest of the figure, another group
    head = review.fit_silhouette(co, tris[np.isin(part, group)], ink, TRUE['s'], feet, (0, 60), (0, 20),
                                 ignored=rest, anchor=whole)
    assert abs(head['yaw'] - TRUE['yaw']) <= 1 and head['pitch'] == TRUE['pitch'], head
    assert abs(head['oy'] - TRUE['oy']) < 1, 'the head alone stays over the sole row where the model has it'
    assert 'no vertex' in _raises(ValueError, review.fit_silhouette, co, kept, ink, anchor=[])


def test_fit_silhouette_without_a_calibration_needs_the_figures_ends():
    co, tris, _, _ = _figure()
    _, ink = _drawn(TRUE)
    rows = np.flatnonzero(ink.any(axis=1))
    region = np.zeros_like(ink)
    region[rows[-1] - 100:, :] = True           # the legs' ink left unread: the soles are not drawn
    why = _raises(ValueError, review.fit_silhouette, co, tris, ink, ignored=region)
    assert 'below its bottom row' in why, why
    q = co @ review._turn_array(TRUE['yaw'], TRUE['pitch']).T
    feet = TRUE['oy'] - TRUE['s'] * q[:, 2].min()
    assert review.fit_silhouette(co, tris, ink, TRUE['s'], feet, ignored=region)['s'] == TRUE['s']
    soles = review.fit_silhouette(co, tris, ink[:rows[-1] + 1])
    assert (soles['yaw'], soles['pitch']) == (TRUE['yaw'], TRUE['pitch']), \
        "a figure on the picture's border is fitted as it is drawn: no region hides its ends"
    side = np.zeros_like(ink)
    side[rows[0] + 300:rows[0] + 400, :120] = True  # a region beside the figure, within its rows
    assert review.fit_silhouette(co, tris, ink | side, ignored=side)['yaw'] == TRUE['yaw']


def test_fit_silhouette_without_a_calibration_sees_a_region_past_the_figures_ends():
    boxes = [('leg.L', (0.04, -0.06, 0.0), (0.16, 0.06, 0.8)), ('leg.R', (-0.16, -0.06, 0.0), (-0.04, 0.06, 0.8)),
             ('torso', (-0.2, -0.1, 0.8), (0.2, 0.1, 1.4)), ('head', (-0.1, -0.1, 1.45), (0.1, 0.12, 1.7)),
             ('arm.L', (0.2, -0.05, 0.6), (0.28, 0.05, 1.38)), ('arm.R', (-0.28, -0.05, 0.6), (-0.2, 0.05, 1.38))]
    co, tris, part = [], [], []
    for k, (name, lo, hi) in enumerate(boxes):
        c, t = _box(lo, hi)
        tris += [[len(co) + i for i in tri] for tri in t]
        part += [k] * len(t)
        co += c
    co, tris, part = np.asarray(co, float), np.asarray(tris), np.asarray(part)
    build = review._paint(co, tris, part, dict(TRUE, yaw=10, pitch=0), (920, 640))
    legs = np.isin(build, [0, 1])
    kept = tris[part > 1]
    # The hands hang below the hips, so the figure left after the legs' region ends at the hands, not
    # next to the region: the region still reaches below that bottom row and may hide the soles.
    why = _raises(ValueError, review.fit_silhouette, co, kept, build >= 0, None, None, (-30, 30), (0, 0),
                  ignored=review.imaging.grown(legs), anchor=np.unique(tris))
    assert 'below its bottom row' in why and 'top' not in why, why


def test_silhouette_without_overlap_says_why():
    build = np.full((20, 20), -1, np.int32)
    build[2:5, 2:5] = 0
    ink = np.zeros((20, 20), bool)
    ink[10:15, 10:15] = True
    assert 'overlaps none' in review.silhouette_report(build, ink, ['a'])['why']
    assert 'no pixel' in review.silhouette_report(np.full((4, 4), -1), np.ones((4, 4), bool), ['a'])['why']


def test_fit_silhouette_recovers_the_drawn_turn():
    co, tris, part, names = _figure()
    _, ink = _drawn(TRUE)
    q = co @ review._turn_array(TRUE['yaw'], TRUE['pitch']).T
    feet = TRUE['oy'] - TRUE['s'] * q[:, 2].min()
    fit = review.fit_silhouette(co, tris, ink, TRUE['s'], feet)
    assert (fit['yaw'], fit['pitch']) == (TRUE['yaw'], TRUE['pitch']), fit
    assert fit['s'] == TRUE['s'] and math.isclose(fit['oy'], TRUE['oy'])
    assert abs(fit['ox'] - TRUE['ox']) <= 1.0 and fit['err'] == []
    assert fit['mismatch'] < 0.02 < fit['mismatch_mirrored']
    assert fit['at_range_edge'] is False and fit['pitch_at_range_edge'] is False and fit['pitch_step'] == 1
    assert fit['level_mismatch'] > 2 * fit['mismatch'] and abs(fit['level_yaw'] - TRUE['yaw']) <= 5, \
        'the best level camera covers the pitched drawing worse'
    level = review.fit_silhouette(co, tris, ink, TRUE['s'], feet, pitch_range=(0, 0))
    assert level['pitch'] == 0 and level['pitch_step'] == 0
    assert (level['level_yaw'], level['level_mismatch']) == (level['yaw'], level['mismatch'])
    assert (level['yaw'], level['mismatch']) == (fit['level_yaw'], fit['level_mismatch'])
    free = review.fit_silhouette(co, tris, ink)
    assert (free['yaw'], free['pitch']) == (TRUE['yaw'], TRUE['pitch']), free
    assert abs(free['s'] / TRUE['s'] - 1) < 0.01 and free['mismatch'] < 0.01
    edge = review.fit_silhouette(co, tris, ink, TRUE['s'], feet, yaw_range=(-10, 10))
    assert edge['yaw'] == 10 and edge['at_range_edge'] is True
    thin = np.zeros((600, 20), bool)
    thin[:, 10] = True                      # gone when shrunk: searched at its own pixels
    assert review._shrink(thin, 3).sum() == 0 and review.fit_silhouette(co, tris, thin)['mismatch'] > 0
    assert 'no ink' in _raises(ValueError, review.fit_silhouette, co, tris, np.zeros((20, 20), bool))
    assert 'empty range' in _raises(ValueError, review.fit_silhouette, co, tris, ink, yaw_range=(5, 0))
    assert 'no triangles' in _raises(ValueError, review.fit_silhouette, co, np.zeros((0, 3), int), ink)


def test_landmark_depths_read_the_nearest_face():
    co, tris, part, names = _figure()
    fit = dict(TRUE)
    R = review._turn_array(fit['yaw'], fit['pitch'])
    d0 = (co @ review._turn_array(fit['yaw'], 0).T)[:, 1]

    def pixel(p):
        q = R @ np.asarray(p, float)
        return [fit['ox'] + fit['s'] * q[0], fit['oy'] - fit['s'] * q[2]]
    front = (0.375, -0.2, 1.2)                   # on the front face of arm.L
    marks = {'hand.L': pixel(front), 'off': [5.0, 5.0]}
    got = review.landmark_depths(co, tris, fit, marks)
    assert list(got) == ['hand.L', 'off']
    want = (review._turn_array(fit['yaw'], 0) @ np.asarray(front))[1]
    assert got['hand.L']['hit'] is True and math.isclose(got['hand.L']['depth'], round(want, 4), abs_tol=1e-4)
    assert got['off']['hit'] is False and got['off']['off_px'] > 0
    moved = review.landmark_depths(co, tris, fit, marks, origin=(0.1, 0.2, 0.0))
    shift = (review._turn_array(fit['yaw'], 0) @ np.array([0.1, 0.2, 0.0]))[1]
    assert math.isclose(moved['hand.L']['depth'], round(want - shift, 4), abs_tol=1e-4)
    u = fit['ox'] + fit['s'] * (co @ R.T)[:, 0]
    v = fit['oy'] - fit['s'] * (co @ R.T)[:, 2]
    i = int(np.argmin(np.hypot(u - 5.0, v - 5.0)))
    assert math.isclose(got['off']['depth'], round(d0[i], 4))


def test_pitch_limit_is_one_pixel_of_the_figures_depth():
    assert math.isclose(review.pitch_limit(1000.0, 0.2), math.degrees(math.asin(1 / 200)))
    assert review.pitch_limit(10.0, 0.05) == 90.0
    assert math.isclose(1000.0 * 0.2 * math.sin(math.radians(review.pitch_limit(1000.0, 0.2))), review.PITCH_SHIFT_PX)


def test_profile_key_deviation_reads_in_metres_and_screen_pixels():
    keys = ((1.0, 1.0, -1.0, 1.0, 2.0), (0.5, 1.1, -1.0, 1.0, 2.0), (0.0, 1.0, -0.9, 0.6, 2.0))
    (i, d), = head.profile_key_deviation(keys)
    assert i == 1 and math.isclose(d, 0.2), 'the half width sits 0.2 off the line between its neighbours'
    (_, _, m), = head.profile_key_deviation(keys, height=0.1, width=0.05)
    assert math.isclose(m, 0.01), 'top 0.1 x 0.1 m against half width 0.2 x 0.05 m: the larger in metres'
    (_, _, m, px), = head.profile_key_deviation(keys, height=0.1, width=0.05, read_mpp=0.009)
    assert px == round(0.01 / 0.009, 2)
    assert 'both' in _raises(ValueError, head.profile_key_deviation, keys, height=0.1)
    assert 'needs height' in _raises(ValueError, head.profile_key_deviation, keys, read_mpp=0.01)
    assert 'positive' in _raises(ValueError, head.profile_key_deviation, keys, height=0.1, width=0.05, read_mpp=0)


def test_fit_and_helpers_check_their_input():
    assert 'yaw' in _raises(ValueError, review._fit_of, {'pitch': 0, 's': 1.0, 'ox': 0, 'oy': 0})
    assert 's' in _raises(ValueError, review._fit_of, {'yaw': 0, 'pitch': 0, 's': True, 'ox': 0, 'oy': 0})
    assert 'yaw' in _raises(ValueError, review._fit_of, None)
    fit = {'yaw': 0, 'pitch': 0, 's': 1.0, 'ox': 0.0, 'oy': float('nan')}
    assert 'oy' in _raises(ValueError, review._fit_of, fit)
    assert review._steps(-90, 90, 5)[-1] == 90 and review._steps(-20, 21, 2)[-1] == 21
    m = np.zeros((5, 7), bool)
    m[0:2, 0:2] = True
    m[4, 6] = True
    assert review._shrink(m, 2).tolist() == [[True, False, False, False], [False] * 4, [False] * 4]


@contextlib.contextmanager
def _scene_readers(ink):
    """The review module's scene and image readers replaced: the default object is the blocky figure,
    the drawing's ink is `ink`, saving an image writes nothing."""
    co, tris, part, names = _figure()
    saved = {k: getattr(review, k) for k in ('_geometry', 'load_image', 'save_image')}
    read_ink = review.imaging.read_ink
    review._geometry = lambda objects: (co, tris, part, list(names))
    review.load_image = lambda path: np.zeros(ink.shape + (4,), np.float32)
    review.save_image = lambda arr, path: path
    review.imaging.read_ink = lambda arr, ignore=None: {'mask': ink & ~ignore, 'ignored': ignore, 'specks': 0,
                                                        'noise_px': 0}
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(review, k, v)
        review.imaging.read_ink = read_ink


def _model(ink, calibration, landmarks):
    """A stand-in model of the figure 'Figure' over a views.json with one view, 'concept', whose image
    header matches ink: SimpleNamespace(name, out, views)."""
    d = tempfile.mkdtemp()
    H, W = ink.shape
    with open(os.path.join(d, 'concept.png'), 'wb') as f:
        f.write(bytes([137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13]) + b'IHDR' + W.to_bytes(4, 'big')
                + H.to_bytes(4, 'big'))
    data = {'views': {'concept': {'image': 'concept.png', 'size': [W, H], 'calibration': calibration}},
            'landmarks': {'concept': landmarks}}
    with open(os.path.join(d, 'views.json'), 'w', encoding='utf-8', newline='\n') as f:
        json.dump(data, f)
    return types.SimpleNamespace(name='Figure', out=os.path.join(d, 'out'),
                                 views=V.Views(os.path.join(d, 'views.json')))


def _outline(m, view, fit, exclude_parts=(), images=True, target=None):
    """review.outline_diff of the figure 'Figure' of the stand-in model m, the picture in m's review folder
    with images."""
    picture = os.path.join(m.out, 'review', 'silhouette', '%s_silhouette_%s.png' % (m.name, view)) if images else None
    return review.outline_diff(m.views, view, fit, ['Figure'], exclude_parts=exclude_parts, picture=picture,
                               target=target)


def test_outline_diff_and_concept_fit_read_the_view_and_the_scene():
    build, ink = _drawn(TRUE)
    q = _figure()[0] @ review._turn_array(TRUE['yaw'], TRUE['pitch']).T
    feet = TRUE['oy'] - TRUE['s'] * q[:, 2].min()
    cal = {'mode': 'rows', 'height_m': 1.7, 'crown_px': feet - 1.7 * TRUE['s'], 'feet_px': feet}
    m = _model(ink, cal, {'hand.L': [500.0, 400.0], 'crown': [320.0, 50.0]})
    with _scene_readers(ink):
        whole = _outline(m, 'concept', TRUE, images=False)
        assert whole['picture'] is None and whole['bands'] == [] and whole['metrics']['iou'] == 1.0, \
            'the build over its own drawing'
        assert whole['metrics']['extra_px'] == whole['metrics']['missing_px'] == 0
        got = _outline(m, 'concept', TRUE, exclude_parts=['arm.R', 'tail'])
        assert got['view'] == 'concept' and got['excluded'] == ['arm.R', 'tail'] and 'arm.R' not in got['parts']
        assert got['unknown_excluded'] == ['tail']
        assert math.isclose(got['mpp'], 1 / TRUE['s']) and got['picture'].endswith('Figure_silhouette_concept.png')
        assert any(b['side'] == 'drawing_only' for b in got['bands']), "the drawn arm.R the build leaves out"
        assert got['metrics']['missing_px'] > 0 and got['metrics']['iou'] < 1
        aimed = _outline(m, 'concept', TRUE, exclude_parts=['arm.R'], target=build >= 0)
        assert aimed['bands'] == got['bands'], 'the same figure given as a mask'
        assert 'target of shape' in _raises(ValueError, _outline, m, 'concept', TRUE, target=np.zeros((3, 3), bool))
        assert 'not in views.json' in _raises(ValueError, _outline, m, 'side', TRUE)
        no_oy = {'yaw': 0, 'pitch': 0, 's': 1, 'ox': 0}
        assert 'oy' in _raises(ValueError, _outline, m, 'concept', no_oy)
        con = review.concept_fit(m.views, 'concept', ['Figure'])
        assert (con['fit']['yaw'], con['fit']['pitch'], con['fit']['s']) == (30, 8, TRUE['s'])
        assert con['pitch_limit'] < 8 and set(con['landmarks']) == {'hand.L', 'crown'}
        hand = con['landmarks']['hand.L']
        assert hand['shift_px'] == round(TRUE['s'] * hand['depth'] * math.sin(math.radians(8)), 2)
        legless = review.concept_fit(m.views, 'concept', ['Figure'], exclude_parts=['leg.L', 'leg.R'])['fit']
        assert (legless['yaw'], legless['pitch']) == (30, 8) and math.isclose(legless['oy'], TRUE['oy']), \
            'the parts left out keep the sole row where the calibration puts it'
        def refuse(arr, ignore=None):
            raise ValueError('half the border is painted')
        review.imaging.read_ink = refuse
        bad = _outline(m, 'concept', TRUE)
        assert bad['picture'] is None and 'half the border' in bad['why'] and bad['size'] == [640, 920]
        assert 'metrics' not in bad
        assert 'half the border' in _raises(ValueError, review.concept_fit, m.views, 'concept', ['Figure'])
        review.imaging.read_ink = lambda arr, ignore=None: {'mask': np.zeros((40, 30), bool),
                                                            'ignored': np.zeros((40, 30), bool), 'specks': 0,
                                                            'noise_px': 0}
        empty = _model(np.zeros((40, 30), bool), {'mode': 'none'}, {}).views
        assert 'no ink' in _raises(ValueError, review.concept_fit, empty, 'concept', ['Figure'])


def test_play_size_scales_each_capture_to_the_declared_height():
    names = ('_viewport', '_hidden', '_shoot', '_screen_height', 'framing', '_world', '_relief', 'load_image',
             'save_image')
    saved = {k: getattr(review, k) for k in names}
    bpy_data = getattr(review.bpy, 'data', None)
    heights = iter([800.0, 790.0, 0.0])
    calls = []
    try:
        review._viewport = lambda: contextlib.nullcontext(('r3', 'region'))
        review._hidden = lambda keep: contextlib.nullcontext()
        review._shoot = lambda rot, shade, loc, dist, path, width, measure=None: (
            calls.append((rot, path)), measure())[1]
        review._screen_height = lambda r3, region, width, co: next(heights)
        review.framing = lambda name, views: {'centre': [0.0, 0.0, 0.85], 'height': 1.7, 'width': 0.6, 'distance': 2.5}
        review._world = lambda name: np.zeros((3, 3))
        review._relief = lambda name: {'torso': 0.3, 'button': 0.004, 'lone': None}
        review.load_image = lambda path: np.ones((900, 600, 4), np.float32)
        review.save_image = lambda arr, path: path
        review.bpy.data = types.SimpleNamespace(objects={'Figure': types.SimpleNamespace(type='MESH')})
        d = tempfile.mkdtemp()
        got = review.play_size('Figure', 100, objects=['Figure'], out=os.path.join(d, 'review', 'read'))
        assert 'out' in _raises(ValueError, review.play_size, 'Figure', 100), 'images need the folder'
        assert [c[0] for c in calls] == ['front', 'side', 'q34']
        assert got['read_px'] == 100 and got['mpp'] == 0.017 and got['figure_px'] == {
            'front': 800.0, 'side': 790.0, 'q34': 0.0}
        assert got['skipped'] == ['q34'] and len(got['files']) == 2
        assert got['files'][0].endswith('Figure_read_front.png') and got['sheet'].endswith('Figure_read_sheet.png')
        assert got['relief']['button'] == {'m': 0.004, 'px': round(0.004 / 0.017, 2)} and got['relief']['lone'] is None
        before_calls = len(calls)
        numeric = review.play_size('Figure', 100, objects=['Figure'], images=False)
        assert len(calls) == before_calls and numeric['captures'] == [] and numeric['sheet'] is None
        assert numeric['relief'] == got['relief']
        assert 'positive' in _raises(ValueError, review.play_size, 'Figure', None, out=d)
        assert 'positive' in _raises(ValueError, review.play_size, 'Figure', 0, out=d)
        assert 'positive' in _raises(ValueError, review.play_size, 'Figure', True, out=d)
        assert 'VIEWS' in _raises(ValueError, review.play_size, 'Figure', 100, views=('front', 'nowhere'), out=d)
    finally:
        for k, v in saved.items():
            setattr(review, k, v)
        if bpy_data is None:
            del review.bpy.data
        else:
            review.bpy.data = bpy_data


def _png(path):
    """An 8-bit PNG (RGB or RGBA, not interlaced) as lpk.stages.imaging.load gives it: float32 RGBA holding
    the stored values / 255, the top row first."""
    with open(path, 'rb') as f:
        data = f.read()
    pos, idat = 8, []
    while pos < len(data):
        n, kind = struct.unpack('>I4s', data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        pos += 12 + n
        if kind == b'IHDR':
            w, h, depth, ctype, _, _, interlace = struct.unpack('>IIBBBBB', body)
        elif kind == b'IDAT':
            idat.append(body)
    assert depth == 8 and interlace == 0 and ctype in (2, 6), path
    ch = 4 if ctype == 6 else 3
    stride, raw = w * ch, zlib.decompress(b''.join(idat))
    out, prev = np.zeros((h, stride), np.uint8), np.zeros(stride, np.int64)
    for y in range(h):
        f, line = raw[y * (stride + 1)], np.frombuffer(raw, np.uint8, stride, y * (stride + 1) + 1).astype(np.int64)
        if f == 2:
            line = (line + prev) & 255
        elif f in (1, 3, 4):
            line = line.copy()
            for i in range(stride):
                a, b, c = (line[i - ch] if i >= ch else 0), prev[i], (prev[i - ch] if i >= ch else 0)
                if f == 1:
                    line[i] = (line[i] + a) & 255
                elif f == 3:
                    line[i] = (line[i] + (a + b) // 2) & 255
                else:
                    pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                    line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        out[y], prev = line, line
    rgba = out.reshape(h, w, ch).astype(np.float32) / 255.0
    return rgba if ch == 4 else np.concatenate([rgba, np.ones((h, w, 1), np.float32)], axis=2)


@contextlib.contextmanager
def _fixture_readers(pictures):
    """The review module's scene readers replaced as _scene_readers does, the drawings read from their
    files (`pictures`: {path: array}), saving writing nothing; the ink reader is the real one."""
    co, tris, part, names = _figure()
    saved = {k: getattr(review, k) for k in ('_geometry', 'load_image', 'save_image')}
    review._geometry = lambda objects: (co, tris, part, list(names))
    review.load_image = lambda path: pictures[os.path.abspath(path)].copy()
    review.save_image = lambda arr, path: path
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(review, k, v)


def test_the_outline_reads_the_worked_examples_drawing():
    d = tempfile.mkdtemp()
    shutil.copytree(os.path.join(EXAMPLE, 'refs'), os.path.join(d, 'refs'))
    shutil.copy(os.path.join(EXAMPLE, 'views.json'), d)
    views = V.Views(os.path.join(d, 'views.json'))
    cal = views.calib('front')
    fit = review.calib_fit(cal, views.view('front')['mid_px'])
    image = os.path.abspath(views.image('front'))
    front = _png(image)
    ink = review.imaging.read_ink(front)['mask']
    picture = os.path.join(d, 'out', 'review', 'silhouette', 'Figure_silhouette_front.png')
    with _fixture_readers({image: front}):
        got = review.outline_diff(views, 'front', fit, ['Figure'], exclude_parts=['arm.R'], picture=picture)
        assert got['bands'] and got['picture'] == picture and got['metrics']['iou'] > 0
        again = review.outline_diff(views, 'front', fit, ['Figure'], exclude_parts=['arm.R'], picture=picture)
        assert json.dumps(again, sort_keys=True) == json.dumps(got, sort_keys=True), 'the same inputs, the same report'
        bare = review.outline_diff(views, 'front', fit, ['Figure'])
        assert bare['picture'] is None and bare['bands']
        aimed = review.outline_diff(views, 'front', fit, ['Figure'], target=ink)
        assert aimed['noise_px'] == 0 and aimed['metrics']['target_px'] <= int(ink.sum())
        assert 'no views.json' in _raises(ValueError, review.outline_diff, None, 'front', fit, ['Figure'])
        assert 'at least one' in _raises(ValueError, review.outline_diff, views, 'front', fit, [])


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print('ok', name)
