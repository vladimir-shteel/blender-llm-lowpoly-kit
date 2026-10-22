"""Host tests of the view fits of lpk.stages.review: calib_fit's side, back and front projections against
the calibrations of lpk.core.views (a model point projected through the fit lands on the calibration's
pixel), view_fit recovering them and its at_range_edge, and lpk.stages.view.VIEWS against view_fit's yaw
and pitch (no Blender needed: bpy and mathutils are replaced by stand-ins while the modules are imported,
and the mathutils stand-in turns vectors with numpy).

python tests/test_review_fit.py"""
import importlib
import json
import math
import os
import sys
import tempfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from blender_stand_ins import Euler as _Euler, Vector as _Vector, stand_ins as _blender_stand_ins  # noqa: E402


with _blender_stand_ins():
    review = importlib.import_module('lpk.stages.review')
    view = importlib.import_module('lpk.stages.view')
    V = importlib.import_module('lpk.core.views')

H, CROWN, FEET = 1.75, 100, 900


def _raises(exc, fn, *args, **kw):
    try:
        fn(*args, **kw)
    except exc as e:
        return str(e)
    raise AssertionError('%s not raised' % exc.__name__)


def _data():
    """Views of one figure: a rows front, a front and a back of shared rows, profiles facing either way
    (one of shifted rows, one a 3x crop of it, one with its own rows, one scaled by a figure) and a
    profile without zero_px."""
    rows_of = lambda off=0: {'mode': 'rows_of', 'of': 'front', 'row_offset_px': off}
    return {'views': {
        'front': {'image': 'refs/front.png', 'size': [700, 1000], 'facing': 'front', 'mid_px': 350,
                  'calibration': {'mode': 'rows', 'height_m': H, 'crown_px': CROWN, 'feet_px': FEET}},
        'clothed': {'image': 'refs/clothed.png', 'size': [720, 1000], 'facing': 'front', 'mid_px': 360,
                    'calibration': rows_of()},
        'back': {'image': 'refs/back.png', 'size': [700, 1000], 'facing': 'back', 'mid_px': 352,
                 'calibration': rows_of()},
        'left': {'image': 'refs/left.png', 'size': [500, 1000], 'facing': 'left', 'zero_px': 250,
                 'calibration': rows_of()},
        'right': {'image': 'refs/right.png', 'size': [650, 1010], 'facing': 'right', 'zero_px': 400,
                  'calibration': rows_of(-10)},
        'right_head': {'image': 'refs/right_head.png', 'size': [450, 400],
                       'calibration': {'mode': 'crop_of', 'of': 'right', 'origin_px': [300, 50], 'zoom': 3}},
        'profile': {'image': 'refs/profile.png', 'size': [600, 1200], 'facing': 'left', 'zero_px': 310.5,
                    'calibration': {'mode': 'rows', 'height_m': 1.6, 'crown_px': 140, 'feet_px': 1100}},
        'figure_side': {'image': 'refs/figure_side.png', 'size': [800, 900], 'facing': 'right', 'zero_px': 512,
                        'calibration': {'mode': 'scale_figure', 'figure_top_px': 120, 'ground_px': 860,
                                        'figure_height_m': 1.8}},
        'no_zero': {'image': 'refs/no_zero.png', 'size': [500, 1000], 'facing': 'left', 'calibration': rows_of()},
    }}


def _views(data=None):
    d = tempfile.mkdtemp()
    p = os.path.join(d, 'views.json')
    with open(p, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(data or _data(), f)
    return V.Views(p)


def _pixel(fit, p):
    """The pixel of model point p under a fit, as view_fit solves it and project draws it (unrounded)."""
    q = review._turn(fit['yaw'], fit['pitch']) @ _Vector(p)
    return fit['ox'] + fit['s'] * q.x, fit['oy'] - fit['s'] * q.z


def _close(a, b, tol=1e-6):
    return all(math.isclose(x, y, abs_tol=tol) for x, y in zip(a, b))


SIDES = (('left', -90), ('right', 90), ('right_head', 90), ('profile', -90), ('figure_side', 90))
MARKS = ((0, 0), (37.5, 412), (123, 980.25), (420, 64))


def test_side_fit_lands_on_the_calibration_pixel():
    v = _views()
    for name, yaw in SIDES:
        cal = v.calib(name)
        fit = review.calib_fit(cal)
        assert (fit['yaw'], fit['pitch'], fit['err']) == (yaw, 0, []), name
        assert fit == review.calib_fit(cal, 123), name
        for px, py in MARKS:
            y, z = cal.side(px, py)
            for x in (-0.3, 0.0, 0.21):
                assert _close(_pixel(fit, (x, y, z)), (px, py)), (name, px, py, x)
        u = _pixel(fit, (0.0, -0.1, 1.0))[0]
        assert (u > cal.zero_px) == (cal.facing == 'right'), name


def test_view_fit_finds_the_side_fit_and_its_range_edge():
    v = _views()
    xs = (0.12, -0.2, 0.05, -0.07)
    for name in ('left', 'right'):
        cal = v.calib(name)
        fit = review.calib_fit(cal)
        points = [(x,) + cal.side(px, py) for x, (px, py) in zip(xs, MARKS)]
        for kw, edge in (({}, True), ({'yaw_range': (-180, 180)}, False)):
            got = review.view_fit(points, MARKS, **kw)
            assert (got['yaw'], got['pitch']) == (fit['yaw'], 0), (name, kw)
            assert math.isclose(got['s'], fit['s'], rel_tol=1e-9), (name, kw)
            assert _close((got['ox'], got['oy']), (fit['ox'], fit['oy'])), (name, kw)
            assert max(got['err']) == 0.0 and got['at_range_edge'] is edge, (name, kw)


def test_back_fit_mirrors_the_front_reading():
    v = _views()
    cal = v.calib('back')
    fit = review.calib_fit(cal)
    assert (fit['yaw'], fit['pitch']) == (180, 0) and math.isclose(fit['ox'], 352)
    assert review.calib_fit(cal, 352)['ox'] == 352
    points = []
    for px, py in MARKS:
        a = cal.model(px, py)
        p = (-a[0], 0.1, a[2])
        points.append(p)
        assert _close(_pixel(fit, p), (px, py)), (px, py)
    assert _pixel(fit, (0.2, 0.0, 1.0))[0] < 352
    got = review.view_fit(points, MARKS, yaw_range=(-180, 180))
    assert got['yaw'] in (-180, 180) and got['pitch'] == 0 and got['at_range_edge'] is False
    assert max(got['err']) == 0.0


def test_front_fit_keeps_its_formula():
    v = _views()
    cal = v.calib('front')
    for mid in (350, 338.5):
        a = cal.model(mid, 0, 0, mid); b = cal.model(mid + 100, 100, 0, mid)
        s = 100 / (b[0] - a[0])
        assert review.calib_fit(cal, mid) == dict(yaw=0, pitch=0, s=s, ox=mid - s * a[0], oy=s * a[2], err=[])
        fit = review.calib_fit(cal, mid)
        for px, py in MARKS:
            assert _close(_pixel(fit, cal.model(px, py, -0.15, mid)), (px, py)), (mid, px, py)
    assert math.isclose(review.calib_fit(cal)['ox'], cal.w / 2)
    clothed = v.calib('clothed')
    fit = review.calib_fit(clothed)
    assert fit['yaw'] == 0 and math.isclose(fit['ox'], 360) and math.isclose(fit['oy'], FEET)
    for px, py in MARKS:
        assert _close(_pixel(fit, clothed.model(px, py)), (px, py)), (px, py)


def test_side_view_without_zero_px_raises():
    cal = _views().calib('no_zero')
    assert cal.facing == 'left' and cal.zero_px is None
    assert 'zero_px' in _raises(V.CalibrationError, review.calib_fit, cal)
    assert 'zero_px' in _raises(ValueError, review.calib_fit, cal, 250)


def test_a_turned_view_has_no_calibrated_fit():
    d = _data()
    d['views']['front']['facing'] = 'turned'
    d['views']['clothed']['facing'] = 'turned'
    v = _views(d)
    for name in ('front', 'clothed'):
        why = _raises(V.CalibrationError, review.calib_fit, v.calib(name))
        assert 'turned view' in why and 'concept_fit' in why and 'view_fit' in why, why
    assert review.calib_fit(v.calib('back'))['yaw'] == 180
    d['views']['front']['facing'] = 'three_quarter_left'
    why = _raises(V.CalibrationError, review.calib_fit, _views(d).calib('front'))
    assert "got 'three_quarter_left'" in why and 'turned' in why, 'an unknown turn is never read as a front: ' + why


def test_at_range_edge_marks_a_search_that_stops_short():
    true = dict(yaw=30, pitch=4, s=480.0, ox=310.0, oy=905.0)
    points = [(0.2, 0.1, 1.6), (-0.25, -0.05, 1.2), (0.1, 0.15, 0.4), (-0.05, -0.12, 0.9), (0.3, 0.0, 1.0)]
    pixels = [_pixel(true, p) for p in points]
    got = review.view_fit(points, pixels)
    assert (got['yaw'], got['pitch'], got['at_range_edge']) == (30, 4, False)
    assert review.view_fit(points, pixels, yaws=range(0, 21))['yaw'] == 20
    assert review.view_fit(points, pixels, yaws=range(0, 21))['at_range_edge'] is True
    assert review.view_fit(points, pixels, yaws=range(40, 61))['yaw'] == 40
    assert review.view_fit(points, pixels, yaws=range(40, 61))['at_range_edge'] is True
    assert review.view_fit(points, pixels, yaws=[30])['at_range_edge'] is True
    assert review.view_fit(points, pixels, yaw_range=(-180, 180))['at_range_edge'] is False
    assert review._at_range_edge(175, range(-180, 180, 5)) is False
    assert review._at_range_edge(-180, range(-180, 180, 5)) is False
    assert review._at_range_edge(177, range(-173, 180, 7)) is True
    assert review._at_range_edge(-90, range(-90, 91)) is True and review._at_range_edge(0, range(-90, 91)) is False


def test_capture_views_turn_the_model_like_view_fit():
    for name, (a, b, c) in view.VIEWS.items():
        m = _Euler([math.radians(x) for x in (a, b, c)], 'XYZ').to_matrix().a
        r = review._turn(-c, 90 - a).a
        # screen right and up of the viewport against the fit's image right (q.x) and image up (q.z)
        assert np.allclose(m[:, 0], r[0]) and np.allclose(m[:, 1], r[2]), name
    left = review.calib_fit(_views().calib('left'))
    assert left['yaw'] == -view.VIEWS['side'][2]


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print('ok', name)
