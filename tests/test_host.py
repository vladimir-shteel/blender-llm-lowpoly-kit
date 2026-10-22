"""Host tests of the lpk.host commands: each command's function run on small arrays in a temporary model
folder, with the PNG input and output of lpk.host.png replaced by an in-memory store, and the Pillow round
trip of lpk.host.png itself when Pillow is installed (skipped without it)."""
import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lpk import intake  # noqa: E402
from lpk.host import intake as host_intake, overlay as host_overlay, png, sheets as host_sheets  # noqa: E402
from lpk.stages import imaging  # noqa: E402

try:
    import PIL  # noqa: F401
    HAVE_PILLOW = True
except ImportError:
    HAVE_PILLOW = False


class _Store:
    """png.load and png.save replaced by a dict of arrays keyed by absolute path, rounded to 8 bits as a
    PNG holds them."""

    def __enter__(self):
        self.files, self.old = {}, (png.load, png.save)

        def save(arr, path):
            path = os.path.abspath(path)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            Path(path).write_bytes(b'')
            self.files[path] = np.floor(np.clip(imaging.rgba(arr), 0, 1) * 255 + 0.5).astype(np.float32) / 255
            return path
        png.load = lambda path: self.files[os.path.abspath(path)].copy()
        png.save = save
        return self

    def __exit__(self, *exc):
        png.load, png.save = self.old


def _sheet():
    a = np.ones((40, 60, 4), np.float32)
    a[..., 0] = np.arange(60)[None, :] / 59.0
    a[10:30, 5:15, :3] = 0.0
    a[2:5, 40:45, 3] = 0.0
    return a


def test_crop_writes_the_views_and_their_fields():
    with _Store() as st, tempfile.TemporaryDirectory() as d:
        sheet = st.files.setdefault(os.path.abspath(os.path.join(d, 'sheet.png')), _sheet())
        paths = host_intake.crop(os.path.join(d, 'sheet.png'), d, 2, {'front': (0, 0, 20, 40), 'side': (30, 0, 50, 40)})
        assert paths == {v: os.path.abspath(os.path.join(d, 'refs', v + '.png')) for v in ('front', 'side')}
        want = intake.crop_views(sheet, {'front': (0, 0, 20, 40)}, 'sheet.png', 2)['images']['front']
        assert np.allclose(st.files[paths['front']], want, atol=0.5 / 255), 'the L0 crop, written'
        data = json.loads(Path(d, 'views.json').read_bytes())
        assert data['views']['side'] == {'image': 'refs/side.png', 'size': [40, 80],
                                         'source': {'sheet': 'sheet.png', 'box': [30, 0, 50, 40], 'scale': 2}}
        host_intake.crop(os.path.join(d, 'sheet.png'), d, 1, {'side': (30, 0, 50, 40)}, bg=None)
        data = json.loads(Path(d, 'views.json').read_bytes())
        assert list(data['views']) == ['front', 'side'] and data['views']['side']['size'] == [20, 40]
        assert st.files[paths['side']][3, 12, 3] == 0.0, 'bg=None keeps the alpha'


def test_grid_draws_a_view_or_a_box_with_its_marks_and_regions():
    with _Store() as st, tempfile.TemporaryDirectory() as d:
        st.files[os.path.abspath(os.path.join(d, 'sheet.png'))] = _sheet()
        host_intake.crop(os.path.join(d, 'sheet.png'), d, 1, {'front': (0, 0, 30, 40)})
        path = os.path.join(d, 'views.json')
        data = intake.update_views(intake.read_views(path), landmarks={'front': {'crown': [10, 10]}},
                                   traces={'LABEL': {'view': 'front', 'px': [[20, 20], [28, 20], [28, 30], [20, 30]]}},
                                   views={'front': {'ignore': {'LABEL': 'a label'}}})
        intake.write_views(path, data)
        view = st.files[os.path.abspath(os.path.join(d, 'refs', 'front.png'))]
        regions = {'LABEL': {'why': 'a label', 'px': data['traces']['LABEL']['px']}}
        whole = host_intake.grid(d, 'front')
        assert whole == os.path.abspath(os.path.join(d, 'out', 'grids', 'front.png'))
        assert np.allclose(st.files[whole], intake.grid_view(view, None, 50, 1, {'crown': [10, 10]}, regions),
                           atol=0.5 / 255)
        boxed = host_intake.grid(d, 'front', box=(2, 3, 12, 13))
        assert os.path.basename(boxed) == 'front_2_3_12_13_z3_s10_marks.png'
        assert np.allclose(st.files[boxed], intake.grid_view(view, (2, 3, 12, 13), 10, 3, {'crown': [10, 10]},
                                                             regions), atol=0.5 / 255)
        bare = host_intake.grid(d, 'front', 5, (2, 3, 12, 13), 2, marks=False)
        assert os.path.basename(bare) == 'front_2_3_12_13_z2_s5.png'
        assert "'back'" in str(_raises(ValueError, host_intake.grid, d, 'back'))


def _raises(exc, fn, *args, **kw):
    try:
        fn(*args, **kw)
    except exc as e:
        return e
    raise AssertionError('%s not raised' % exc.__name__)


def test_key_writes_the_keyed_sheet_and_sample_reads_its_seeds():
    with _Store() as st, tempfile.TemporaryDirectory() as d:
        a = np.ones((40, 60, 4), np.float32)
        a[..., :3] = np.array((77, 128, 204)) / 255
        a[10:30, 20:40, :3] = 0.0
        a[14:26, 24:36, :3] = np.array((78, 128, 204)) / 255
        st.files[os.path.abspath(os.path.join(d, 'sheet.png'))] = a
        seeds = host_intake.seeds(os.path.join(d, 'sheet.png'), [[2, 2]], step=10, clearance=3)
        assert seeds == imaging.ground_seeds(a, [[2, 2]], step=10, clearance=3)
        got = host_intake.key(os.path.join(d, 'sheet.png'), d, seeds['points'])
        assert got['image'] == os.path.abspath(os.path.join(d, 'refs', 'sheet_keyed.png'))
        assert got['share'] == round(1 - 400 / 2400, 4)
        record = json.loads(Path(got['record']).read_bytes())
        assert record == {'sheet': 'sheet.png', 'radius': 2, 'seeds': json.loads(json.dumps(got['seeds']))}
        host_intake.crop(got['image'], d, 1, {'front': (0, 0, 60, 40)}, bg=None)
        assert host_intake.key_seeds(d, 'front') == record['seeds']
        out = host_intake.sample(d, 'front', {'inside': [30, 20], 'paper': [2, 2]})
        assert out['colours'] == {'inside': (0.306, 0.502, 0.8), 'paper': (1.0, 1.0, 1.0)}
        assert out['ground'] == {'inside': 0.0, 'paper': 1.0}
        assert [k['point'] for k in out['keyed']['inside']], 'the ground key takes a colour this close'
        host_intake.crop(os.path.join(d, 'sheet.png'), d, 1, {'plain': (0, 0, 60, 40)})
        assert host_intake.key_seeds(d, 'plain') == [] and host_intake.sample(d, 'plain', {'x': [2, 2]})['keyed'] == {
            'x': []}


def test_clean_writes_the_cleaned_picture_and_compare_reads_it_against_the_original():
    with _Store() as st, tempfile.TemporaryDirectory() as d, open(os.devnull, 'w') as null:
        a = np.ones((40, 60, 4), np.float32)
        a[5:35, 10:30, :3] = 0.2
        a[3, 50, :3] = 0.0
        a[30:33, 45:48, :3] = 0.5
        st.files[os.path.abspath(os.path.join(d, 'sheet.png'))] = a
        got = host_intake.clean(os.path.join(d, 'sheet.png'), d, 10, keep=[(44, 29, 49, 34)])
        assert got['image'] == os.path.abspath(os.path.join(d, 'refs', 'sheet_clean.png'))
        want = imaging.clean(a, 10, keep=_box_mask(a, (44, 29, 49, 34)))[0]
        assert np.allclose(st.files[got['image']], want, atol=0.5 / 255)
        assert got['dropped'] == [{'box': [50, 3, 51, 4], 'px': 1}] and got['kept'] == 2
        record = json.loads(Path(got['record']).read_bytes())
        assert record == {'picture': 'sheet.png', 'min_px': 10, 'keep': [[44, 29, 49, 34]],
                          'dropped': got['dropped'], 'seeds': []}
        host_intake.crop(got['image'], d, 1, {'front': (0, 0, 60, 40)})
        host_intake.crop(os.path.join(d, 'sheet.png'), d, 1, {'front_original': (0, 0, 60, 40)})
        assert host_intake.key_seeds(d, 'front') == []
        out = host_intake.compare(d, 'front', 'front_original')
        assert out['picture'] == os.path.abspath(os.path.join(d, 'out', 'compare', 'front.png'))
        assert out['metrics']['missing_px'] == 1 and out['metrics']['extra_px'] == 0, out['metrics']
        assert "'back'" in str(_raises(ValueError, host_intake.compare, d, 'front', 'back'))
        old, sys.stdout = sys.stdout, null
        try:
            cli = host_intake.main(['clean', os.path.join(d, 'sheet.png'), d, '--min-px', '10'])
            both = host_intake.main(['compare', d, 'front', 'front_original'])
        finally:
            sys.stdout = old
        assert [p['px'] for p in cli['dropped']] == [1, 9] and both['metrics'] == out['metrics']


def _box_mask(a, box):
    m = np.zeros(a.shape[:2], bool)
    x0, y0, x1, y1 = box
    m[y0:y1, x0:x1] = True
    return m


def test_the_command_line_parses_into_the_functions():
    with _Store() as st, tempfile.TemporaryDirectory() as d, open(os.devnull, 'w') as null:
        st.files[os.path.abspath(os.path.join(d, 'sheet.png'))] = _sheet()
        old, sys.stdout = sys.stdout, null
        try:
            host_intake.main(['crop', os.path.join(d, 'sheet.png'), d, '1', 'front=0,0,30,40'])
            got = host_intake.main(['grid', d, 'front', '5', '0,0,10,10', '--zoom', '2', '--no-marks'])
            colours = host_intake.main(['sample', d, 'front', 'ink=8,20', '--radius', '1'])
        finally:
            sys.stdout = old
        assert os.path.basename(got) == 'front_0_0_10_10_z2_s5.png'
        assert colours['colours'] == {'ink': (0.0, 0.0, 0.0)}


def test_sheets_crops_scales_and_lays_out_with_the_kit_sheet():
    with _Store() as st, tempfile.TemporaryDirectory() as d:
        a, b = np.zeros((40, 60, 4), np.float32), np.ones((20, 40, 4), np.float32)
        a[..., 3] = b[..., 3] = 1.0
        for name, im in (('a.png', a), ('b.png', b)):
            st.files[os.path.abspath(os.path.join(d, name))] = im
        size = host_sheets.sheet(os.path.join(d, 's.png'), 2, 30, 0.5, ['A', ''],
                                 [os.path.join(d, 'a.png'), os.path.join(d, 'b.png') + '@1'])
        want = imaging.sheet([imaging.scale(imaging.crop(a, (15, 0, 45, 40)), 1.0),
                              imaging.scale(b, 30 / 40)], 2, ['A', None])
        assert size == (want.shape[1], want.shape[0])
        assert np.allclose(st.files[os.path.abspath(os.path.join(d, 's.png'))], want, atol=0.5 / 255)
        tall = host_sheets.sheet(os.path.join(d, 't.png'), 1, -10, 1.0, [''], [os.path.join(d, 'b.png')])
        assert tall == tuple(s for s in imaging.sheet([imaging.scale(b, 0.5)], 1).shape[1::-1])


def test_overlay_is_the_kit_overlay_written():
    with _Store() as st, tempfile.TemporaryDirectory() as d:
        ref = np.ones((20, 30, 4), np.float32)
        st.files[os.path.abspath(os.path.join(d, 'ref.png'))] = ref
        faces = {'faces': [[1.0, 'skin', [[5, 5], [15, 5], [10, 15]]]], 'pal': {'skin': [0.9, 0.7, 0.6]},
                 'marks': [[10, 10]]}
        Path(d, 'faces.json').write_text(json.dumps(faces), encoding='utf-8')
        size = host_overlay.overlay(os.path.join(d, 'faces.json'), os.path.join(d, 'ref.png'),
                                    os.path.join(d, 'o.png'), (0, 0, 20, 20), 1)
        want = imaging.overlay(ref, faces, box=(0, 0, 20, 20))
        assert size == (60, 20) and np.allclose(st.files[os.path.abspath(os.path.join(d, 'o.png'))], want,
                                                atol=0.5 / 255)


def test_png_round_trip_through_pillow():
    if not HAVE_PILLOW:
        print('skip test_png_round_trip_through_pillow: Pillow is not installed')
        return
    with tempfile.TemporaryDirectory() as d:
        a = np.random.default_rng(3).integers(0, 256, (7, 5, 4)).astype(np.float32) / 255
        p = png.save(a, os.path.join(d, 'sub', 'a.png'))
        assert p == os.path.abspath(os.path.join(d, 'sub', 'a.png'))
        b = png.load(p)
        assert b.dtype == np.float32 and b.shape == (7, 5, 4) and np.array_equal(a, b), 'exact at 8 bits'
        from lpk.core import views
        assert views.image_size(p) == (5, 7)
        grey = png.save(np.full((3, 4), 0.5, np.float32), os.path.join(d, 'g.png'))
        assert np.allclose(png.load(grey), [128 / 255] * 3 + [1.0])


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print('ok', name)
