"""Host tests of the views.json calibrations, the ignore regions and part traces of lpk.core.views, the
landmark measurements (measure), and lpk.intake on plain arrays and views.json dicts (no Blender and no
Pillow needed)."""
import json
import math
import os
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lpk.core import views as V  # noqa: E402
from lpk import intake  # noqa: E402
from lpk.stages import imaging  # noqa: E402

H, CROWN, FEET = 1.9, 130, 1465


def _raises(exc, fn, *args, **kw):
    try:
        fn(*args, **kw)
    except exc as e:
        return str(e)
    raise AssertionError('%s not raised' % exc.__name__)


def _data():
    """A views.json of four views the way a turnaround sheet gives them: a rows front, a front of
    shared rows, a side 10 rows lower and a 3x crop of the head."""
    return {
        'views': {
            'front': {'image': 'refs/front.png', 'size': [680, 1490],
                      'calibration': {'mode': 'rows', 'height_m': H, 'crown_px': CROWN, 'feet_px': FEET},
                      'mid_px': 338, 'facing': 'front'},
            'clothed': {'image': 'refs/clothed.png', 'size': [720, 1490],
                        'calibration': {'mode': 'rows_of', 'of': 'front', 'row_offset_px': 0}, 'mid_px': 360},
            'side': {'image': 'refs/side.png', 'size': [650, 1500],
                     'calibration': {'mode': 'rows_of', 'of': 'front', 'row_offset_px': -10},
                     'zero_px': 400, 'facing': 'right'},
            'head_front': {'image': 'refs/head_front.png', 'size': [540, 630],
                           'calibration': {'mode': 'crop_of', 'of': 'front', 'origin_px': [260, 120], 'zoom': 3}},
        },
        'landmarks': {'front': {'crown': [338, 130], 'chin': [338, 330]}, 'side': {'chin': [250, 340]}},
        'widths_px': {'front': {'skull': 140}},
        'traces': {'MASK': {'view': 'head_front', 'px': [[40, 275], [230, 290]]}},
    }


def _views(data):
    d = tempfile.mkdtemp()
    p = os.path.join(d, 'views.json')
    with open(p, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(data, f)
    return V.Views(p)


def test_rows_is_the_formula_and_a_calib():
    v = _views(_data())
    c = v.calib('front')
    assert type(c).__name__ == 'Calib' and type(c) is V.Calib
    mpp = H / (FEET - CROWN)
    assert c.mpp == mpp
    for py in (0, 130, 700.5, 1465):
        assert c.z(py) == (FEET - py) * mpp
    assert c.m(37) == 37 * mpp
    assert tuple(c.model(500, 700)) == ((500 - 680 / 2) * mpp, 0.0, (FEET - 700) * mpp)
    assert tuple(c.model(500, 700, 0.2, 338)) == ((500 - 338) * mpp, 0.2, (FEET - 700) * mpp)
    assert v.calib('front') is c


def test_rows_of_shares_scale_and_shifts_rows():
    v = _views(_data())
    f, s, cl = v.calib('front'), v.calib('side'), v.calib('clothed')
    assert s.mpp == f.mpp and s.feet_px == FEET + 10
    for py in (0, 340, 812.25):
        assert s.z(py) == f.z(py - 10)
    # The depth mapping a model would write by hand: (zero_px - px) * mpp, z of the shifted row.
    for px, py in ((250, 340), (612, 1100)):
        assert s.side(px, py) == ((400 - px) * f.mpp, f.z(py + -10))
    assert s.side_y(450) < 0
    # Own midline from views.json, the same numbers as the front calibration given that midline.
    assert tuple(cl.model(410, 600, 0)) == tuple(f.model(410, 600, 0, 360))
    d = _data()
    del d['views']['clothed']['mid_px']
    assert tuple(_views(d).calib('clothed').model(410, 600)) == tuple(f.model(410, 600, 0, 720 / 2))


def test_side_facing_left_and_missing_side_fields():
    d = _data()
    d['views']['side']['facing'] = 'left'
    s = _views(d).calib('side')
    assert s.side_y(450) == (450 - 400) * s.mpp
    _raises(V.CalibrationError, _views(_data()).calib('front').side, 300, 300)
    _raises(V.CalibrationError, _views(_data()).calib('clothed').side_y, 300)


def test_crop_of_maps_to_its_source():
    v = _views(_data())
    f, h = v.calib('front'), v.calib('head_front')
    for px, py in ((0, 0), (40, 275), (539, 629), (100.5, 7)):
        fx, fy = 260 + px / 3, 120 + py / 3
        assert h.to_of(px, py) == (fx, fy)
        assert h.z(py) == f.z(fy)
        assert tuple(h.model(px, py, -0.6)) == tuple(f.model(fx, fy, -0.6))
    assert h.m(30) == f.m(30 / 3) and h.mpp == f.mpp / 3
    assert h.feet_px == (FEET - 120) * 3
    assert tuple(h.model(40, 275, 0, 234)) == tuple(f.model(260 + 40 / 3, 120 + 275 / 3, 0, 260 + 234 / 3))


def test_crop_of_a_side_view_keeps_its_depth():
    d = _data()
    d['views']['head_side'] = {'image': 'refs/head_side.png', 'size': [300, 300],
                               'calibration': {'mode': 'crop_of', 'of': 'side', 'origin_px': [200, 100], 'zoom': 2}}
    v = _views(d)
    s, hs = v.calib('side'), v.calib('head_side')
    assert hs.side(50, 80) == s.side(200 + 50 / 2, 100 + 80 / 2)
    assert hs.facing == 'right' and hs.zero_px == (400 - 200) * 2


def test_scale_figure_scale_and_ground():
    d = _data()
    d['views']['sheet'] = {'image': 'refs/sheet.png', 'size': [1000, 800], 'mid_px': 420,
                           'calibration': {'mode': 'scale_figure', 'figure_top_px': 200, 'ground_px': 740,
                                           'figure_height_m': 1.8}}
    c = _views(d).calib('sheet')
    assert type(c) is V.ScaleFigureCalib
    assert c.mpp == 1.8 / (740 - 200) and c.z(740) == 0
    assert math.isclose(c.z(200), 1.8)
    assert tuple(c.model(520, 740)) == ((520 - 420) * c.mpp, 0.0, 0.0)


def test_known_span_scales_from_two_landmarks():
    d = _data()
    d['views']['wing'] = {'image': 'refs/wing.png', 'size': [900, 600],
                          'calibration': {'mode': 'known_span', 'a': 'tip.R', 'b': 'tip.L', 'metres': 2.4,
                                          'ground_px': 560, 'axis': 'x'}}
    d['landmarks']['wing'] = {'tip.R': [100, 200], 'tip.L': [700, 230]}
    c = _views(d).calib('wing')
    assert type(c) is V.KnownSpanCalib and c.mpp == 2.4 / 600 and c.z(560) == 0
    d['views']['wing']['calibration']['axis'] = 'y'
    assert _views(d).calib('wing').mpp == 2.4 / 30
    del d['views']['wing']['calibration']['axis']
    assert _views(d).calib('wing').mpp == 2.4 / math.hypot(600, 30)
    d['views']['wing']['calibration'].update(a=[0, 10], b=[0, 410])
    assert _views(d).calib('wing').mpp == 2.4 / 400
    d['views']['wing']['calibration'].update(a=[5, 5], b=[5, 5])
    _raises(V.CalibrationError, _views(d).calib, 'wing')
    d['views']['wing']['calibration'].update(a='nose')
    assert 'nose' in _raises(V.CalibrationError, _views(d).calib, 'wing')


def test_none_and_bad_calibrations_raise_clearly():
    d = _data()
    d['views']['photo'] = {'image': 'refs/photo.png', 'size': [100, 100], 'calibration': {'mode': 'none'}}
    msg = _raises(V.CalibrationError, _views(d).calib, 'photo')
    assert 'dimensions' in msg and 'metres' in msg
    assert isinstance(V.CalibrationError('x'), ValueError)
    d['views']['photo']['calibration'] = {'mode': 'guess'}
    assert 'guess' in _raises(V.CalibrationError, _views(d).calib, 'photo')
    d['views']['photo']['calibration'] = {'mode': 'rows_of', 'of': 'front'}
    assert 'row_offset_px' in _raises(V.CalibrationError, _views(d).calib, 'photo')
    d['views']['photo']['calibration'] = {'mode': 'rows_of', 'of': 'nowhere', 'row_offset_px': 0}
    assert 'nowhere' in _raises(V.CalibrationError, _views(d).calib, 'photo')
    d['views']['photo']['calibration'] = {'mode': 'crop_of', 'of': 'photo', 'origin_px': [0, 0], 'zoom': 2}
    assert 'photo -> photo' in _raises(V.CalibrationError, _views(d).calib, 'photo')


def test_a_calibration_gives_plain_points():
    d = _data()
    d['views'] = {'sheet': {'image': 'refs/sheet.png', 'size': [1000, 800],
                            'calibration': {'mode': 'scale_figure', 'figure_top_px': 200, 'ground_px': 740,
                                            'figure_height_m': 1.8}}, **d['views']}
    c = _views(d).calib('sheet')
    mpp = 1.8 / (740 - 200)
    assert type(c.model(300, 400)) is tuple, 'a calibration gives plain points, which P may hold'
    assert c.model(300, 400) == ((300 - 500) * mpp, 0.0, (740 - 400) * mpp)


def test_measure_turns_landmarks_into_metres():
    cal = V.Calib(1.8, 100, 1000, (800, 1100))
    landmarks = {'crown': (400, 100), 'hip.L': (460, 600), 'hip.R': (340, 600), 'knee.L': (450, 790)}
    m = V.measure(cal, landmarks, {'waist': 180})
    mpp = 1.8 / 900
    assert m['z'] == {k: (1000 - p[1]) * mpp for k, p in landmarks.items()}
    assert m['w'] == {'waist': 180 * mpp}
    assert m['dist']('hip.L', 'knee.L') == math.hypot(10, 190) * mpp
    assert m['span']('hip.R', 'hip.L') == 120 * mpp and math.isclose(m['span']('hip.R', 'hip.L', k=0.5), 60 * mpp)
    turned = V.measure(cal, landmarks, {}, width_k=0.92)
    assert turned['span']('hip.R', 'hip.L') == 120 * mpp * 0.92, 'width_k scales the horizontal spans back'
    assert turned['dist']('hip.L', 'knee.L') == m['dist']('hip.L', 'knee.L'), 'and leaves the distances'
    assert all(type(v) is float for v in m['z'].values()), 'plain numbers, which P may hold'



def test_the_reader_gives_each_views_data():
    v = _views(_data())
    assert v.names == ['front', 'clothed', 'side', 'head_front']
    assert v.size('side') == (650, 1500) and v.view('side')['zero_px'] == 400
    assert v.image('front') == os.path.join(v.root, 'refs/front.png')
    assert v.landmarks('side') == {'chin': [250, 340]} and v.landmarks('clothed') == {}
    assert v.widths('front') == {'skull': 140} and v.widths('side') == {}
    assert v.calibration('side') == {'mode': 'rows_of', 'of': 'front', 'row_offset_px': -10}
    assert v.trace('MASK')['view'] == 'head_front'


def test_ignore_regions_are_traces_of_their_view_with_a_reason():
    d = _data()
    d['traces']['ARMS'] = {'view': 'front', 'px': [[0, 300], [200, 300], [200, 360], [0, 360]]}
    d['traces']['LINE'] = {'view': 'front', 'px': [[0, 0], [5, 5]]}
    d['views']['front']['ignore'] = {'ARMS': 'the arms drawn in a T-pose'}
    v = _views(d)
    assert v.ignore('front') == {'ARMS': {'why': 'the arms drawn in a T-pose', 'px': d['traces']['ARMS']['px']}}
    assert v.ignore('side') == {}
    d['views']['side']['ignore'] = {'ARMS': 'x', 'LINE': 'a line', 'NOPE': 'gone', 'MASK': ''}
    d['views']['clothed']['ignore'] = ['ARMS']
    text = _raises(ValueError, _views(d).ignore, 'side')
    for needle in ("ignore names trace 'ARMS', which is drawn on view 'front'",
                   "ignore names trace 'LINE', which is drawn on view 'front'",
                   "ignore names trace 'NOPE', which the traces section lacks",
                   "ignore names trace 'MASK', which is drawn on view 'head_front'",
                   "ignore: trace 'MASK' needs its reason"):
        assert needle in text, (needle, text)
    assert 'ignore must be {trace name: the reason}' in _raises(ValueError, _views(d).ignore, 'clothed')
    d['views']['side']['ignore'] = {'LINE': 'a line'}
    d['traces']['LINE']['view'] = 'side'
    assert 'fewer than three points' in _raises(ValueError, _views(d).ignore, 'side')


def test_image_size_reads_the_png_header():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, 'a.png')
        Path(p).write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00\x00\x00\rIHDR' + (37).to_bytes(4, 'big')
                            + (21).to_bytes(4, 'big') + b'\x08\x06\x00\x00\x00')
        assert V.image_size(p) == (37, 21)
        Path(p).write_bytes(b'GIF89a' + bytes(20))
        assert 'not a PNG' in _raises(ValueError, V.image_size, p)


def _sheet():
    a = np.zeros((40, 60, 4), np.float32)
    a[..., 0] = np.arange(60)[None, :] / 59.0
    a[..., 1] = np.arange(40)[:, None] / 39.0
    a[..., 3] = 1.0
    a[5:8, 5:8, 3] = 0.0
    return a


def test_crop_views_cuts_the_views_and_gives_their_fields():
    sheet = _sheet()
    r = intake.crop_views(sheet, {'front': (0, 0, 20, 30), 'side': (30, 4, 50, 34)}, 'sheet.png')
    assert list(r['images']) == list(r['views']) == ['front', 'side']
    assert r['views']['front'] == {'image': 'refs/front.png', 'size': [20, 30],
                                   'source': {'sheet': 'sheet.png', 'box': [0, 0, 20, 30], 'scale': 1}}
    front = r['images']['front']
    assert front.shape == (30, 20, 4) and np.all(front[6, 6] == 1.0), 'transparent pixels flattened white'
    assert np.allclose(front[10, 12], sheet[10, 12])
    keep = intake.crop_views(sheet, {'front': (0, 0, 20, 30)}, 'sheet.png', bg=None)['images']['front']
    assert keep[6, 6, 3] == 0.0, 'bg=None keeps the alpha'
    big = intake.crop_views(sheet, {'front': (-2, 0, 20, 30)}, 'sheet.png', scale=2)
    assert big['views']['front']['size'] == [44, 60]
    assert np.all(big['images']['front'][:, :4] == 1.0), 'outside the sheet: bg'
    assert np.array_equal(big['images']['front'][20:22, 24:26].reshape(-1, 4)[0], front[10, 10])
    _raises(ValueError, intake.crop_views, sheet, {'bad name': (0, 0, 1, 1)}, 'sheet.png')
    _raises(ValueError, intake.crop_views, sheet, {'x': (5, 0, 5, 1)}, 'sheet.png')
    _raises(ValueError, intake.crop_views, sheet, {'x': (0, 0, 1.5, 1)}, 'sheet.png')
    _raises(ValueError, intake.crop_views, sheet, {'x': (0, 0, 1, 1)}, 'sheet.png', scale=0)


def test_update_views_merges_in_place_and_removes_with_none():
    data = _data()
    out = intake.update_views(data, landmarks={'front': {'chin': [338, 331], 'nose': np.array([338, 250])},
                                               'side': None},
                              widths_px={'front': {'neck': np.int64(60)}},
                              traces={'MASK': None, 'TEETH': {'view': 'head_front', 'px': [(1, 2), (3, 4)]}},
                              views={'side': {'note': 'profile', 'zero_px': None, 'facing': None}})
    assert out is data and list(out) == ['views', 'landmarks', 'widths_px', 'traces']
    assert list(out['landmarks']) == ['front'] and list(out['landmarks']['front']) == ['crown', 'chin', 'nose']
    assert out['landmarks']['front']['chin'] == [338, 331] and out['landmarks']['front']['nose'] == [338, 250]
    assert out['widths_px']['front'] == {'skull': 140, 'neck': 60} and type(out['widths_px']['front']['neck']) is int
    assert out['traces'] == {'TEETH': {'view': 'head_front', 'px': [[1, 2], [3, 4]]}}
    assert list(out['views']['side']) == ['image', 'size', 'calibration', 'note']
    before = json.dumps(out)
    _raises(ValueError, intake.update_views, out, landmark={})
    _raises(ValueError, intake.update_views, out, landmarks={'front': [1, 2]})
    _raises(ValueError, intake.update_views, out, views={'front': {'note': 'x'}}, traces=[])
    assert json.dumps(out) == before, 'a refused update changes nothing'


def test_views_json_is_written_with_lf_and_read_back():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, 'views.json')
        assert intake.read_views(p) == {'views': {}}
        assert intake.write_views(p, _data()) == p
        raw = Path(p).read_bytes()
        assert b'\r\n' not in raw and raw.endswith(b'}\n') and raw.startswith(b'{\n "views"')
        assert intake.read_views(p) == _data() and not os.path.exists(p + '.tmp')


def test_derived_calibrations_from_crop_sources():
    sheet = _sheet()
    data = intake.read_views(os.path.join(tempfile.mkdtemp(), 'views.json'))
    intake.update_views(data, views=intake.crop_views(sheet, {'front': (0, 0, 20, 30), 'side': (30, 4, 50, 34)},
                                                      'sheet.png', scale=2)['views'])
    intake.update_views(data, views=intake.crop_views(sheet, {'head': (6, 2, 14, 10)}, 'sheet.png', scale=6)['views'])
    assert intake.rows_of_calibration(data, 'side', 'front') == {'mode': 'rows_of', 'of': 'front',
                                                                 'row_offset_px': 8}
    c = intake.crop_of_calibration(data, 'head', 'front')
    assert c == {'mode': 'crop_of', 'of': 'front', 'origin_px': [12, 4], 'zoom': 3}
    assert 'scales' in _raises(ValueError, intake.rows_of_calibration, data, 'head', 'front')
    other = json.loads(json.dumps(data))
    other['views']['head']['source']['sheet'] = 'other.png'
    assert 'different sheets' in _raises(ValueError, intake.crop_of_calibration, other, 'head', 'front')
    assert 'crop source' in _raises(ValueError, intake.crop_of_calibration, data, 'head', 'nowhere')
    intake.update_views(data, views={'front': {'calibration': {'mode': 'rows', 'height_m': 1.0, 'crown_px': 2,
                                                               'feet_px': 58}},
                                     'side': {'calibration': intake.rows_of_calibration(data, 'side', 'front')},
                                     'head': {'calibration': c}})
    with tempfile.TemporaryDirectory() as d:
        v = V.Views(intake.write_views(os.path.join(d, 'views.json'), data))
        # A sheet pixel seen through the head crop and through the front crop measures the same.
        sx, sy = 9.5, 7.25
        hx, hy = (sx - 6) * 6, (sy - 2) * 6
        fx, fy = (sx - 0) * 2, (sy - 0) * 2
        assert math.isclose(v.calib('head').z(hy), v.calib('front').z(fy))
        assert math.isclose(v.calib('head').model(hx, hy)[0], v.calib('front').model(fx, fy)[0])
        assert math.isclose(v.calib('side').z((sy - 4) * 2), v.calib('front').z(fy))


def test_rows_calibration_takes_the_crown_and_the_sole_landmarks():
    data = _data()
    data['landmarks']['side']['sole'] = [250, 1475]
    data['landmarks']['side']['crown'] = [250, 140]
    assert intake.rows_calibration(data, 'side', 1.9) == {'mode': 'rows', 'height_m': 1.9, 'crown_px': 140,
                                                          'feet_px': 1475}
    assert intake.rows_calibration(data, 'side', 2)['height_m'] == 2
    assert 'no landmark sole' in _raises(ValueError, intake.rows_calibration, data, 'front', 1.9)
    for bad in (0, -1, 'tall', float('nan'), True):
        assert 'height_m' in _raises(ValueError, intake.rows_calibration, data, 'side', bad)
    data['landmarks']['side']['sole'] = [250, 140]
    assert 'below' in _raises(ValueError, intake.rows_calibration, data, 'side', 1.9)


def test_marks_sit_on_zoomed_pixel_centres():
    a = np.ones((30, 30, 4), np.float32)
    intake.marks(a, {'p': [12, 4], 'bad': [1]}, (10, 2), 3)
    cx, cy = (12 - 10) * 3 + 1, (4 - 2) * 3 + 1
    assert np.allclose(a[cy, cx], intake.MARK_COLOR) and np.allclose(a[cy, cx - 3], intake.MARK_COLOR)
    assert np.allclose(a[cy - 3, cx], intake.MARK_COLOR) and np.allclose(a[cy - 4, cx], 1.0)


def _is(g, colour):
    return np.isclose(g[..., :3], colour[:3], atol=1 / 255).all(axis=2)


def test_a_grid_of_a_box_is_labelled_and_marked_in_view_pixels():
    view = intake.crop_views(_sheet(), {'front': (0, 0, 20, 30)}, 'sheet.png')['images']['front']
    whole = intake.grid_view(view, step=10)
    assert whole.shape == (30, 20, 4)
    assert np.array_equal(whole, imaging.grid(imaging.flatten(view), 10, (0, 0))), 'no marks, no regions: the grid'
    g = intake.grid_view(view, box=(2, 3, 12, 13), step=5, zoom=3, landmarks={'p': [7, 8]})
    assert g.shape == (30, 30, 4)
    plain = imaging.grid(imaging.scale(imaging.crop(imaging.flatten(view), (2, 3, 12, 13)), 3), 5, (2, 3), zoom=3)
    cx, cy = (7 - 2) * 3 + 1, (8 - 3) * 3 + 1
    marked = _is(g, intake.MARK_COLOR)
    assert marked[cy, cx] and marked[cy, cx - 3] and not _is(plain, intake.MARK_COLOR)[cy, cx]
    assert intake.grid_view(view, box=(2, 3, 12, 13), step=5, zoom=3).tolist() == plain.tolist()
    assert intake.grid_view(view, box=(-5, 0, 5, 10), step=5, zoom=1).shape == (10, 10, 4)
    assert intake.grid_view(view, box=(-5, 0, 5, 10)).shape == (10 * intake.BOX_GRID_ZOOM, 10 * intake.BOX_GRID_ZOOM, 4)
    _raises(ValueError, intake.grid_view, view, box=(2, 3, 2, 13))


def test_grids_draw_the_ignore_regions_hatched():
    view = intake.crop_views(_sheet(), {'front': (0, 0, 20, 30)}, 'sheet.png')['images']['front']
    regions = {'LABEL': {'why': 'a label beside the figure', 'px': [[10, 10], [18, 10], [18, 20], [10, 20]]}}
    assert not _is(intake.grid_view(view), imaging.HATCH_COLOR).any()
    hatch = _is(intake.grid_view(view, regions=regions), imaging.HATCH_COLOR)
    assert hatch[10, 10:19].any() and not hatch[:9].any(), 'drawn on the region only'
    zh = _is(intake.grid_view(view, box=(8, 8, 20, 22), zoom=2, regions=regions), imaging.HATCH_COLOR)
    assert zh[(10 - 8) * 2:, (10 - 8) * 2:].any() and not zh[:(10 - 8) * 2 - 1].any()


def test_sample_colours_takes_the_median_of_each_patch():
    a = np.zeros((20, 30, 4), np.float32)
    a[...] = (0.2, 0.4, 0.6, 1.0)
    a[:, 15:] = (1.0, 0.0, 0.0, 1.0)
    a[10, 5] = (0.0, 0.0, 0.0, 1.0)                    # a stray line pixel inside the blue area
    a[0:3, 27:30, 3] = 0.0                             # a transparent corner
    got = intake.sample_colours(a, {'shirt': [5, 10], 'cape': (25.4, 10.2), 'corner': [0, 0],
                                    'paper': np.array([29, 0])})
    assert got['colours'] == {'shirt': (0.2, 0.4, 0.6), 'cape': (1.0, 0.0, 0.0), 'corner': (0.2, 0.4, 0.6),
                              'paper': (1.0, 1.0, 1.0)}, got
    # Paint to the border with a transparent corner: no background to read, so no ground is measured.
    assert got['ground'] is None and got['ink_refused'], got
    assert got['keyed'] == {'shirt': [], 'cape': [], 'corner': [], 'paper': []}
    assert intake.sample_colours(a, {'ink': [5, 10]}, radius=0)['colours'] == {'ink': (0.0, 0.0, 0.0)}
    assert 'outside' in _raises(ValueError, intake.sample_colours, a, {'x': [30, 0]})
    _raises(ValueError, intake.sample_colours, a, {'x': [1]})
    _raises(ValueError, intake.sample_colours, a, {'x': [1, 1]}, radius=-1)
    _raises(ValueError, intake.sample_colours, a, {'x': [1, 1]}, radius=1.5)


def test_sample_colours_measures_the_ground_in_a_patch_and_the_seeds_that_key_a_colour():
    paper, line, fill = (0.8, 0.85, 0.9), (0.4, 0.45, 0.5), (0.75, 0.8, 0.85)
    a = np.ones((40, 60, 4), np.float32)
    a[..., :3] = paper
    a[35, :, :3] = line                                # a floor line, one pixel thick
    a[10:31, 18:43, :3] = 0.0                          # a figure: a closed black outline
    a[13:28, 21:40, :3] = fill                         # painted in a light colour near the paper's
    a[2:7, 46:57, :3] = (0.9, 0.1, 0.1)                # a swatch printed on the ground
    keyed, seeds = imaging.key(a, [[2, 2], [5, 35]])
    assert seeds[1]['tolerance'] > 50, 'the patch on the thin line mixes the line and the paper'
    view = intake.crop_views(keyed, {'front': (0, 0, 60, 40)}, 'refs/sheet_keyed.png', bg=None)['images']['front']
    points = {'fill': [30, 20], 'outline': [19, 20], 'paper': [10, 20], 'swatch': [51, 4], 'swatch_edge': [51, 6]}
    got = intake.sample_colours(view, points, seeds=seeds)
    assert got['ink_refused'] is None and got['colours']['paper'] == (1.0, 1.0, 1.0), 'the keyed ground flattens white'
    assert got['ground'] == {'fill': 0.0, 'outline': 0.2, 'paper': 1.0, 'swatch': 0.0, 'swatch_edge': 0.4}, got
    assert [k['point'] for k in got['keyed']['fill']] == [[5, 35]], got['keyed']
    assert got['keyed']['outline'] == [] and got['keyed']['swatch'] == [], 'black and red lie beyond every tolerance'
    strip = {'strip': {'why': 'the palette strip', 'px': [[44, 0], [59, 0], [59, 9], [44, 9]]}}
    ignored = intake.sample_colours(view, {'swatch_edge': [51, 6], 'paper': [10, 20]}, regions=strip)
    assert ignored['ground'] == {'swatch_edge': 0.0, 'paper': 1.0}, 'pixels in an ignore region are never ground'
    _, far = imaging.key(a, [[2, 2], [5, 38]])
    assert far[1]['tolerance'] == 1.0, 'farther from the line than the radius: the paper alone'
    assert intake.sample_colours(view, {'fill': [30, 20]}, seeds=far)['keyed'] == {'fill': []}


def test_compare_copy_reports_what_a_copy_removed_and_what_it_drew():
    original = np.ones((30, 40, 4), np.float32)
    original[5:25, 5:15, :3] = 0.2                   # the figure
    original[2, 30, :3] = 0.0                        # a speck the copy removes
    original[10:12, 15:20, :3] = 0.4                 # an arrow touching the figure, removed too
    copy = np.ones_like(original)
    copy[5:25, 5:15, :3] = 0.2
    copy[25:27, 5:15, :3] = 0.2                      # two rows the tool drew below the feet
    picture, out = intake.compare_copy(original, copy)
    m = out['metrics']
    assert out['size'] == [40, 30] and picture.shape == (30, 40, 4)
    assert m['extra_px'] == 20 and m['missing_px'] == 11 and m['overlap_px'] == 200, m
    assert [(r['kind'], r['box']) for r in m['regions']] == [('extra', [5, 25, 15, 27]), ('missing', [15, 10, 20, 12]),
                                                             ('missing', [30, 2, 31, 3])], m['regions']
    assert np.allclose(picture[26, 6, :3], imaging.FIRST_COLOR)
    assert np.allclose(picture[2, 30, :3], imaging.SECOND_COLOR)
    regions = {'arrow': {'px': [[14, 9], [21, 9], [21, 13], [14, 13]]}}
    m = intake.compare_copy(original, copy, regions=regions)[1]['metrics']
    assert m['missing_px'] == 1 and m['unread_px'] > 0 and m['symmetric_px'] is None, m
    assert 'same box' in _raises(ValueError, intake.compare_copy, original, copy[:20])


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print('ok', name)
