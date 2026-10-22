"""Host tests of the pure array functions of lpk.stages.imaging (no Blender needed)."""
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lpk.stages import imaging as im  # noqa: E402

BLUE = (0.0, 0.47, 1.0)


def _is(px, rgb):
    return np.allclose(px[:3], rgb, atol=1e-6)


def test_glyphs_are_five_rows_of_equal_width():
    for ch, g in im.GLYPHS.items():
        assert g.shape[0] == im.GLYPH_HEIGHT, ch
        assert g.shape[1] >= 1, ch


def test_rgba_accepts_grey_rgb_and_uint8():
    assert im.rgba(np.zeros((2, 3))).shape == (2, 3, 4)
    a = im.rgba(np.full((2, 3, 3), 255, np.uint8))
    assert a.dtype == np.float32 and np.all(a == 1.0)


def test_crop_shape_and_offset_with_fill_outside():
    a = np.zeros((20, 30, 4), np.float32)
    a[5, 7] = (1, 0, 0, 1)
    c = im.crop(a, (4, 3, 14, 9))
    assert c.shape == (6, 10, 4)
    assert _is(c[5 - 3, 7 - 4], (1, 0, 0))
    out = im.crop(a, (-2, -1, 3, 2), fill=(0, 1, 0, 1))
    assert out.shape == (3, 5, 4)
    assert _is(out[0, 0], (0, 1, 0)) and out[0, 0, 3] == 1.0
    assert _is(out[1, 2], (0, 0, 0)) and out[1, 2, 3] == 0.0


def test_scale_nearest_integer_blocks():
    a = np.random.default_rng(1).random((3, 5, 4)).astype(np.float32)
    s = im.scale(a, 3)
    assert s.shape == (9, 15, 4)
    assert np.array_equal(s[::3, ::3], a)
    assert np.array_equal(s[2::3, 2::3], a)


def test_scale_fractional_up_and_down_shapes():
    a = np.ones((10, 7, 4), np.float32)
    assert im.scale(a, 1.5).shape == (15, 11, 4)
    assert im.scale(a, 0.5).shape == (5, 4, 4)
    assert im.scale(a, 0.01).shape == (1, 1, 4)


def test_scale_box_filter_averages_blocks():
    a = np.zeros((4, 4, 4), np.float32)
    a[..., 3] = 1.0
    a[:2, :2, 0] = 1.0
    a[2:, 2:, 1] = 0.5
    s = im.scale(a, 0.5)
    assert s.shape == (2, 2, 4)
    assert np.allclose(s[0, 0], (1, 0, 0, 1)) and np.allclose(s[1, 1], (0, 0.5, 0, 1))
    assert np.allclose(s[0, 1], (0, 0, 0, 1))
    b = np.zeros((1, 3, 4), np.float32)
    b[0, :, 0] = (0.0, 0.3, 0.9)
    b[..., 3] = 1.0
    t = im.scale(b, 2 / 3)
    assert t.shape == (1, 2, 4)
    assert np.allclose(t[0, :, 0], ((0.0 + 0.5 * 0.3) / 1.5, (0.5 * 0.3 + 0.9) / 1.5))


def test_scale_box_filter_ignores_transparent_colour():
    a = np.zeros((1, 2, 4), np.float32)
    a[0, 0] = (1, 0, 0, 1)
    a[0, 1] = (0, 1, 0, 0)
    s = im.scale(a, 0.5)
    assert np.allclose(s[0, 0], (1, 0, 0, 0.5))


def test_text_draws_glyph_rows_at_box_offset():
    a = np.zeros((12, 20, 4), np.float32)
    box = im.text(a, 2, 3, '47', color=(1, 0, 0), bg=(1, 1, 1))
    assert box == (2, 3, 2 + 7 + 2, 3 + 5 + 2)
    gx, gy = 3, 4
    assert [_is(a[gy, gx + i], (1, 0, 0)) for i in range(3)] == [True, False, True]       # '4' top '#.#'
    assert [_is(a[gy, gx + 4 + i], (1, 0, 0)) for i in range(3)] == [True, True, True]   # '7' top '###'
    assert _is(a[gy, gx + 3], (1, 1, 1))
    assert a[0, 0, 3] == 0.0
    assert im.text_size('47', 2) == (14, 10)


def test_grid_lines_and_labels_in_source_coordinates():
    a = np.zeros((100, 120, 4), np.float32)
    a[..., 3] = 1.0
    g = im.grid(a, 10, origin=(37, 50), label_every=1, size=1)
    assert a[..., :3].max() == 0.0
    # x = 60 is array column 23, y = 60 is array row 10
    assert _is(g[55, 23], BLUE) and _is(g[55, 33], BLUE) and _is(g[55, 24], (0, 0, 0))
    assert _is(g[10, 50], BLUE) and _is(g[20, 50], BLUE) and _is(g[15, 50], (0, 0, 0))
    # column label '40' in a white box from (5, 1); its glyphs start at (6, 2)
    assert [_is(g[2, 6 + i], BLUE) for i in range(3)] == [True, False, True]
    assert _is(g[2, 7], (1, 1, 1))
    assert [_is(g[2, 10 + i], BLUE) for i in range(3)] == [True, True, True]
    # row label '60' from (1, 12); '6' second row is '#..'
    assert [_is(g[14, 2 + i], BLUE) for i in range(3)] == [True, False, False]
    assert _is(g[13, 2], BLUE) and _is(g[13, 4], BLUE)


def test_grid_skips_row_label_under_column_label():
    a = np.zeros((40, 60, 4), np.float32)
    g = im.grid(a, 10, origin=(37, 50), label_every=1, size=1)
    # row 0 (y = 50) would put its label over the label of column 40: left out; y = 60 is drawn
    assert g[3, 1, 3] == 0.0
    assert _is(g[13, 1], (1, 1, 1))


def test_grid_with_zoom_puts_lines_on_source_pixel_edges():
    a = np.zeros((30, 30, 4), np.float32)
    a[..., 3] = 1.0
    g = im.grid(im.scale(a, 3), 5, origin=(0, 0), label_every=100, zoom=3, size=1)
    assert g.shape == (90, 90, 4)
    for x in (15, 30, 45):
        assert _is(g[61, x], np.array(BLUE) * 0.4), x
    assert _is(g[61, 16], (0, 0, 0))


def test_grid_auto_label_spacing_avoids_overlap():
    a = np.zeros((50, 400, 4), np.float32)
    g = im.grid(a, 5, origin=(1000, 0), size=2)
    labelled = [c for c in range(20, 400) if g[43, c, 3] > 0.99]
    gaps = np.diff(labelled)
    assert len(labelled) >= 2 and gaps.min() >= im.text_size('1395', 2)[0] + 2 * im.LABEL_PAD + 3


def test_sheet_layout():
    ims = [np.full((10, 20, 4), 1.0, np.float32), np.zeros((6, 8, 4), np.float32), np.zeros((12, 5, 4), np.float32)]
    ims[1][..., 3] = 1.0
    ims[2][..., 0] = 1.0
    ims[2][..., 3] = 1.0
    s = im.sheet(ims, 2, pad=4)
    assert s.shape == (2 * 12 + 3 * 4, 2 * 20 + 3 * 4, 4)
    assert _is(s[4, 4], (1, 1, 1))
    assert _is(s[4, 4 + 24 + 6], (0, 0, 0)) and _is(s[4, 4 + 24 + 5], (1, 1, 1))
    assert _is(s[4 + 12 + 4, 4 + 7], (1, 0, 0)) and _is(s[4 + 12 + 4, 4 + 6], (1, 1, 1))
    lab = im.sheet(ims, 3, labels=['A', None, 'C'], pad=4, size=1)
    lh = 5 + 2 * im.LABEL_PAD + 2
    assert lab.shape == (lh + 12 + 2 * 4, 3 * 20 + 4 * 4, 4)
    assert _is(lab[4 + 1, 4 + 1 + 1], (0, 0, 0))     # 'A' top row '.#.'
    assert _is(lab[4 + lh, 4 + 24 + 6], (0, 0, 0))


def test_fill_polygon_triangle_and_concave():
    a = np.zeros((10, 10, 4), np.float32)
    im.fill_polygon(a, [(1, 1), (8, 1), (1, 8)], (0, 1, 0))
    assert _is(a[2, 2], (0, 1, 0)) and _is(a[1, 8], (0, 1, 0)) and not _is(a[8, 8], (0, 1, 0))
    b = np.zeros((10, 10, 4), np.float32)
    im.fill_polygon(b, [(0, 0), (9, 0), (9, 9), (5, 2), (0, 9)], (1, 0, 0))
    assert _is(b[1, 5], (1, 0, 0)) and not _is(b[8, 5], (1, 0, 0)) and _is(b[7, 1], (1, 0, 0))


def test_overlay_panels_colours_and_marks():
    ref = np.ones((20, 30, 4), np.float32)
    faces = {'faces': [[0.5, 'near', [[2, 2], [12, 2], [2, 12]]], [1.5, 'far', [[0, 0], [20, 0], [0, 15]]]],
             'pal': {'near': [0.2, 0.4, 0.6], 'far': [1.0, 1.0, 0.0]}, 'marks': [[25, 10]]}
    o = im.overlay(ref, faces)
    assert o.shape == (20, 90, 4)
    flat, wire = o[:, 30:60], o[:, 60:]
    assert _is(flat[4, 4], (0.2, 0.4, 0.6))          # near over far, sRGB kept as is
    assert _is(flat[1, 16], (1.0, 1.0, 0.0))
    assert _is(flat[18, 28], (60 / 255,) * 3)
    assert _is(wire[2, 7], (1, 0, 0)) and _is(wire[18, 28], (1, 1, 1))
    assert _is(wire[10, 25], (0, 160 / 255, 1)) and _is(flat[10, 20], (0, 160 / 255, 1))
    z = im.overlay(ref, faces, palette={'near': (0, 0, 0)}, box=(0, 0, 10, 10), zoom=2)
    assert z.shape == (20, 60, 4)
    assert _is(z[8, 28], (0, 0, 0)) and _is(z[2, 38], (1, 0, 1))


def test_overlay_reads_faces_file():
    import tempfile
    ref = np.ones((8, 8, 4), np.float32)
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / 'faces.json'
        p.write_text(json.dumps({'faces': [[0, 'a', [[1, 1], [6, 1], [1, 6]]]], 'pal': {'a': [0, 0, 1]}}))
        o = im.overlay(ref, str(p))
    assert _is(o[2, 8 + 2], (0, 0, 1))


def _refuses(arr, words):
    try:
        im.ink_mask(arr)
    except im.InkMaskError as e:
        assert words in str(e), str(e)
        return str(e)
    raise AssertionError('ink_mask did not refuse')


def _drawing(h=40, w=30, bg=(1.0, 1.0, 1.0)):
    a = np.empty((h, w, 4), np.float32)
    a[...] = bg + (1.0,)
    return a


def test_ink_mask_fills_the_background_from_the_border_by_colour_only():
    a = _drawing()
    a[5:35, 8:22, :3] = (0.2, 0.3, 0.4)                   # a figure
    a[10:20, 12:18, :3] = 1.0                             # a hole inside it, background-white but enclosed
    a[25:30, 10:20, :3] = 254 / 255                       # paint lighter than any 'light means background' rule
    m = im.ink_mask(a)
    assert m.dtype == bool and m.shape == (40, 30)
    assert m[5:35, 8:22].all() and m.sum() == 30 * 14, 'enclosed white and near-white paint stay ink'
    assert im.ink_runs(m, 'x', 7) == [(8, 21)] and im.ink_runs(m, 'y', 9) == [(5, 34)]
    assert im.ink_runs(m, 'x', 2) == []
    assert im.figure_box(a) == (8, 5, 22, 35) and im.figure_box(m) == (8, 5, 22, 35)
    two = m.copy()
    two[7, 25:28] = True
    assert im.ink_runs(two, 'x', 7) == [(8, 21), (25, 27)]


def test_ink_mask_takes_one_level_of_background_noise_and_any_flat_colour():
    rng = np.random.default_rng(3)
    a = _drawing(bg=(61 / 255,) * 3)
    a[..., :3] += rng.integers(0, 2, (40, 30, 1)) / 255   # a render's dither: one level
    a[12:30, 10:20, :3] = (0.8, 0.6, 0.5)
    assert im.figure_box(a) == (10, 12, 20, 30)


def test_ink_mask_reads_alpha_when_the_picture_has_transparent_pixels():
    a = _drawing()
    a[..., 3] = 0.0
    a[4:10, 3:9, 3] = 1.0
    a[4:10, 9, 3] = 0.6                                   # an antialiased edge: covered past half is ink
    a[4:10, 10, 3] = 0.4
    m = im.ink_mask(a)
    assert im.ink_runs(m, 'x', 5) == [(3, 9)] and im.figure_box(m) == (3, 4, 10, 10)
    b = _drawing()
    b[:, :, 3] = 1.0
    b[20, 15, 3] = 0.0                                    # transparent pixels, but an opaque border
    _refuses(b, 'border is transparent')


def test_ink_mask_refuses_a_background_it_cannot_vouch_for():
    g = _drawing()
    g[..., :3] = np.linspace(0.3, 1.0, 40)[:, None, None]  # a graded background
    g[15:25, 10:20, :3] = 0.0
    _refuses(g, 'no background colour')
    s = _drawing(80, 60)
    s[10:50, 10:25, :3] = 0.0
    s[70, 55, :3] = 0.5                                   # one stray speck, more than a block away
    why = _refuses(s, 'lone pixel')
    assert '(55, 70)' in why and 'imaging.key' in why, 'a painted ground may be keyed: ' + why
    keyed = s.copy()
    keyed[..., 3] = np.where((s[..., :3] == 1.0).all(axis=2), 0.0, 1.0)
    why = _refuses(keyed, 'lone pixel')
    assert 'opaque paint on the transparent ground' in why and 'imaging.key' not in why, \
        'a picture read by its alpha has no ground to key: ' + why
    rng = np.random.default_rng(7)
    n = _drawing(80, 60, bg=(0.5, 0.5, 0.5))
    n[..., :3] += rng.integers(-2, 3, (80, 60, 1)) / 255  # paint noise all over the background
    n[30:50, 25:35, :3] = 0.0
    _refuses(n, 'not clean')
    assert im.ink_mask(n, tol=2).sum() == 200, 'a caller may widen the tolerance on purpose'
    try:
        im.figure_box(_drawing())
    except im.InkMaskError as e:
        assert 'no ink' in str(e)
    else:
        raise AssertionError('a blank picture has no figure')



def test_ink_mask_drops_the_specks_compression_leaves_beside_the_drawing():
    a = _drawing(80, 60)
    a[10:50, 10:25, :3] = 0.0                             # the figure
    a[20, 28, :3] = 253 / 255                             # a lone speck 4 px off its right edge
    a[30:32, 30:32, :3] = 250 / 255                       # a 2 x 2 speck reaching 7 px off it
    clean = _drawing(80, 60)
    clean[10:50, 10:25, :3] = 0.0
    r = im.read_ink(a)
    assert (r['mask'] == im.ink_mask(clean)).all() and (im.ink_mask(a) == r['mask']).all()
    assert r['specks'] == 2 and r['noise_px'] == 7
    c = im.read_ink(clean)
    assert c['specks'] == c['noise_px'] == 0
    kept = clean.copy()
    kept[30, 28:29 + im.CODING_BLOCK_PX, :3] = 0.6      # a stroke longer than a block is drawn
    kept[70:72, 50:52, :3] = 0.0                          # a dot more than a block away is drawn
    k = im.read_ink(kept)
    assert k['specks'] == 0 and k['mask'][30, 28:29 + im.CODING_BLOCK_PX].all() and k['mask'][70:72, 50:52].all()
    dots = _drawing()
    dots[5:7, 5:7, :3] = dots[20:22, 20:22, :3] = 0.0     # only small pieces: nothing to be the drawing
    assert im.read_ink(dots)['specks'] == 0 and im.ink_mask(dots).sum() == 8


def test_a_clean_picture_keeps_every_piece_of_its_ink():
    a = _drawing(80, 60)
    a[10:50, 10:25, :3] = 0.0                             # the figure
    a[60:63, 30:35, :3] = 0.1                             # a solid fragment of a label, within a block of it
    a[52:54, 26:28, :3] = 250 / 255                       # a faint 2 x 2 dot beside it
    r = im.read_ink(a)
    assert r['specks'] == 0 and r['noise_px'] == 0, 'no lone pixel: no noise was measured'
    assert r['mask'][60:63, 30:35].all() and r['mask'][52:54, 26:28].all()
    assert r['mask'].sum() == 40 * 15 + 15 + 4


def test_a_line_drawn_in_the_grounds_colour_reads_as_ground_with_no_bound():
    a = _drawing(100, 100, bg=(0.0, 0.0, 0.0))
    a[20:80, 30:70, :3] = 0.5                             # the figure's fill
    a[20:80, 30:34, :3] = a[20:80, 66:70, :3] = 0.0       # its outline, drawn in the ground's colour
    r = im.read_ink(a)
    cols = np.flatnonzero(r['mask'].any(axis=0))
    assert r['noise_px'] == 0 and (cols[0], cols[-1]) == (34, 65), 'the edge sits at the line\'s inner side'


def test_components_label_pieces_in_first_pixel_order():
    m = np.zeros((6, 8), bool)
    m[0, 5] = m[1, 6] = True           # diagonal neighbours: one piece at 8, two at 4
    m[2, 0:3] = True                   # a run
    m[3, 3] = True                     # touches the run's end diagonally
    m[5, 7] = True                     # alone
    labels, sizes = im.components(m)
    assert labels[0, 5] == labels[1, 6] == 1
    assert labels[2, 0] == labels[3, 3] == 2 and labels[5, 7] == 3
    assert sizes.tolist() == [m.size - 7, 2, 4, 1]
    four, sizes4 = im.components(m, 4)
    assert four[0, 5] == 1 and four[1, 6] == 2 and four[2, 0] == 3 and four[3, 3] == 4 and four[5, 7] == 5
    assert sizes4.tolist() == [m.size - 7, 1, 1, 3, 1, 1]
    assert not im.components(np.zeros((3, 3), bool))[0].any()
    rows, starts, ends = im.runs(m)
    assert rows.tolist() == [0, 1, 2, 3, 5] and starts.tolist() == [5, 6, 0, 3, 7] and ends.tolist() == [6, 7, 3, 4, 8]
    try:
        im.components(m, 6)
    except ValueError as e:
        assert '4 or 8' in str(e)
    else:
        raise AssertionError('connectivity 6 accepted')


def test_ink_mask_background_is_what_reaches_the_border_side_by_side():
    rng = np.random.default_rng(5)
    for _ in range(40):
        free = rng.random((30, 40)) < 0.7
        border = np.zeros_like(free)
        border[0] = border[-1] = True
        border[:, 0] = border[:, -1] = True
        reached = border & free
        while True:                    # a plain flood, one side-step at a time
            grown = reached.copy()
            grown[1:] |= reached[:-1]
            grown[:-1] |= reached[1:]
            grown[:, 1:] |= reached[:, :-1]
            grown[:, :-1] |= reached[:, 1:]
            grown &= free
            if np.array_equal(grown, reached):
                break
            reached = grown
        labels, _ = im.components(free, 4)
        edge = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
        assert np.array_equal(np.isin(labels, edge[edge > 0]), reached)


def test_ink_runs_rejects_a_bad_axis_or_index():
    m = np.zeros((4, 6), bool)
    for args in (('z', 0), ('x', 4), ('y', 6), ('x', -1), ('x', 1.0)):
        try:
            im.ink_runs(m, *args)
        except ValueError:
            continue
        raise AssertionError('ink_runs accepted %r' % (args,))
    try:
        im.ink_runs(np.zeros(5, bool), 'x', 0)
    except ValueError:
        pass
    else:
        raise AssertionError('a 1-D mask is not a picture')


def test_sheet_crops_to_the_figures_on_one_floor_line():
    tall, short, blank = _drawing(40, 60), _drawing(40, 60), _drawing(40, 60)
    tall[5:35, 10:20, :3] = 0.0                           # a figure 30 px tall, 10 wide
    short[15:35, 40:46, :3] = 0.0                         # one 20 px tall, 6 wide, on the same floor
    s = im.sheet([tall, short], 2, pad=2, crop=True)
    assert s.shape == (2 + 34 + 2, 3 * 2 + 2 * 14, 4), 'the rows of both figures, each its own columns'
    col = 2 + 14 + 2 + (14 - 10) // 2                     # the short figure's cut, centred in its cell
    assert _is(s[2 + 2 + 29, col + 2], (0, 0, 0)) and _is(s[2 + 2 + 30, col + 2], (1, 1, 1)), (
        'both figures end on one row: the floor line holds')
    assert _is(s[2 + 2 + 9, col + 2], (1, 1, 1)) and _is(s[2 + 2 + 10, col + 2], (0, 0, 0))
    whole = im.sheet([tall, blank], 2, pad=2, crop=True)
    assert whole.shape == (2 + 40 + 2, 3 * 2 + 2 * 60, 4), 'a picture without a figure keeps its frame'
    assert np.array_equal(im.sheet([blank], 1, pad=2, crop=True), im.sheet([blank], 1, pad=2))


def test_sheet_scales_each_figure_to_one_height():
    small, big = _drawing(30, 20), _drawing(60, 40)
    small[5:15, 5:10, :3] = 0.0                           # a figure 10 px tall
    big[10:30, 10:20, :3] = 0.0                           # one 20 px tall
    s = im.sheet([small, big], 2, pad=2, height=20)
    assert s.shape == (60 + 2 * 2, 2 * 40 + 3 * 2, 4), 'the small picture doubled, the big one kept'
    assert _is(s[2 + 10, 2 + 10], (0, 0, 0)) and _is(s[2 + 29, 2 + 10], (0, 0, 0)) and _is(s[2 + 30, 2 + 10], (1, 1, 1))
    t = im.sheet([small, big], 2, pad=2, height=20, figure_px=[None, 40])
    assert t.shape == (60 + 2 * 2, 2 * 40 + 3 * 2, 4)
    x0 = 2 + 40 + 2 + (40 - 20) // 2                     # the halved big picture, centred in its cell
    assert _is(t[2 + 5, x0 + 5], (0, 0, 0)) and _is(t[2 + 15, x0 + 5], (1, 1, 1))
    assert np.array_equal(im.sheet([small, big], 2, pad=2), im.sheet([small, big], 2, pad=2, figure_px=[1, 1]))
    painted = _drawing(30, 20)
    painted[..., :3] = np.linspace(0.2, 0.9, 30)[:, None, None]
    try:
        im.sheet([small, painted], 2, height=20)
    except im.InkMaskError as e:
        assert str(e).startswith('image 1:') and 'figure_px' in str(e)
    else:
        raise AssertionError('a painted picture has no figure box')
    assert im.sheet([small, painted], 2, pad=2, height=20, figure_px=[None, 20]).shape[0] == 60 + 4
    for kw in ({'height': 0}, {'height': 20, 'figure_px': [None]}, {'height': 20, 'figure_px': [None, 0]}):
        try:
            im.sheet([small, big], 2, **kw)
        except ValueError:
            continue
        raise AssertionError('sheet accepted %r' % kw)



def test_read_ink_leaves_an_ignore_region_unread():
    a = _drawing(80, 60)
    a[10:50, 10:25, :3] = 0.0                             # the figure
    a[20:30, 25:50, :3] = 0.3                             # a second figure overlapping it
    a[70, 40, :3] = 0.5                                   # a stray pixel under a label
    ignore = np.zeros((80, 60), bool)
    ignore[18:32, 25:52] = True
    ignore[66:74, 36:44] = True
    _refuses(a, 'lone pixel')
    r = im.read_ink(a, ignore=ignore)
    assert (r['ignored'] == ignore).all() and not (r['mask'] & ignore).any()
    assert r['mask'][10:50, 10:25].all() and r['mask'].sum() == 40 * 15
    assert (im.ink_mask(a, ignore=ignore) == r['mask']).all()
    assert not im.read_ink(_drawing())['ignored'].any(), 'no region: every pixel is read'
    b = a.copy()
    b[65, 40, :3] = 0.5                                   # alone, but beside a region: it may go on under it
    assert im.read_ink(b, ignore=ignore)['mask'][65, 40]
    painted = _drawing(80, 60)
    painted[10:50, 10:25, :3] = 0.0
    painted[:, 40:, :3] = (0.2, 0.4, 0.6)                 # a painted panel reaching the border
    cover = np.zeros((80, 60), bool)
    cover[:, 38:] = True
    assert im.ink_mask(painted)[:, 40:].all(), 'read, the panel is ink'
    assert im.ink_mask(painted, ignore=cover).sum() == 40 * 15, 'its border pixels left out of the background too'
    ring = np.ones((80, 60), bool)
    ring[5:75, 5:55] = False
    try:
        im.read_ink(a, ignore=ring)
    except im.InkMaskError as e:
        assert 'whole border' in str(e)
    else:
        raise AssertionError('a region over the whole border leaves no background')
    try:
        im.read_ink(a, ignore=np.zeros((10, 10), bool))
    except ValueError as e:
        assert '60 x 80' in str(e)
    else:
        raise AssertionError('an ignore mask of another shape')


def test_a_stroke_the_crop_or_a_region_cut_is_neither_noise_nor_a_speck():
    edge = _drawing(80, 60)
    edge[10:50, 10:25, :3] = 0.0
    edge[0, 45, :3] = 0.2                                 # one pixel of a frame line the crop cut
    r = im.read_ink(edge)
    assert r['mask'][0, 45] and r['noise_px'] == 0, 'on the border: no lone pixel'
    a = _drawing(80, 60)
    a[10:50, 10:25, :3] = 0.0
    a[20, 28, :3] = 253 / 255                             # a lone speck: the noise
    a[30:32, 30:32, :3] = 250 / 255                       # a 2 x 2 speck reaching 7 px off the figure
    assert (im.read_ink(a)['specks'], im.read_ink(a)['noise_px']) == (2, 7)
    ignore = np.zeros((80, 60), bool)
    ignore[28:34, 32:40] = True                           # a region the 2 x 2 piece touches
    r = im.read_ink(a, ignore=ignore)
    assert r['mask'][30:32, 30:32].all() and (r['specks'], r['noise_px']) == (1, 4), r


def test_polygon_masks_regions_and_their_hatching():
    square = [(2, 2), (8, 2), (8, 6), (2, 6)]
    m = im.polygon_mask((10, 12), square)
    assert m[2:7, 2:9].all() and m.sum() == 35
    b = np.zeros((10, 12, 4), np.float32)
    im.fill_polygon(b, square, (1.0, 0.0, 0.0))
    assert ((b[..., 0] == 1.0) == m).all(), 'fill_polygon paints the mask'
    lab = im.region_labels((10, 12, 4), [square, [(6, 4), (10, 4), (10, 8), (6, 8)]])
    assert lab.dtype == np.int32 and lab[3, 3] == 1 and lab[5, 7] == 1 and lab[7, 9] == 2 and lab[0, 0] == 0
    assert not im.region_labels((10, 12), []).any()
    a = np.ones((10, 12, 4), np.float32)
    im.hatch(a, m)
    drawn = (a[..., :3] != 1.0).any(axis=2)
    assert not drawn[~m].any() and drawn[2, 2:9].all() and drawn[2:7, 2].all(), 'the outline'
    assert drawn[m].sum() < m.sum(), 'the inside shows through between the lines'
    assert np.allclose(a[2, 2], im.HATCH_COLOR)


def _gridded(h=90, w=80):
    """A painted ground graded from top to bottom with a darker grid line every 10 pixels, a figure with
    a dark outline, light paint inside it as light as the ground, and a grain pixel on the paper."""
    a = np.empty((h, w, 4), np.float32)
    a[..., 3] = 1.0
    a[..., :3] = (np.linspace(150, 200, h)[:, None, None] + np.array([0, 25, 50])) / 255.0
    a[::10, :, :3] -= 30 / 255.0
    a[:, ::10, :3] -= 30 / 255.0
    a[20:70, 25:55, :3] = 0.1                             # the outline
    a[22:68, 27:53, :3] = a[22:68, 0:26, :3]              # paint inside it, coloured like the ground
    a[85, 64, :3] = 0.9                                   # one pixel of grain
    return a


def test_key_makes_a_painted_gridded_ground_transparent():
    a = _gridded()
    _refuses(a, 'key the ground to transparent with lpk.stages.imaging.key')
    points = [[5, 5], [5, 84], [10, 10], [10, 50], [10, 80]]   # paper at both ends, grid crossings down the grade
    keyed, seeds = im.key(a, points)
    ground = keyed[..., 3] == 0
    figure = np.zeros_like(ground)
    figure[20:70, 25:55] = True
    assert keyed.dtype == np.float32 and np.allclose(keyed[..., :3], a[..., :3]), 'the colours stay'
    assert not ground[figure].any(), 'the outline holds the flood out of the paint inside it'
    assert not (~ground & ~figure)[1:].any() and (~ground[0]).sum() == 8, \
        'the grid crossings on the top border, darker than any patch, stay: a stroke the border cut'
    assert ground[85, 64], 'a grain pixel the ground encloses is ground'
    assert [s['point'] for s in seeds] == points
    assert seeds[0]['tolerance'] < seeds[2]['tolerance'], 'a patch on a grid crossing holds the lines'
    assert all(s['pixels'] > 0 for s in seeds) and seeds[0]['colour'] == tuple(round(v, 3) for v in a[5, 5, :3])
    r = im.read_ink(keyed)
    assert r['mask'][figure].all() and r['mask'].sum() == 50 * 30 + 8, 'read by its alpha'
    paper = im.key(a, [[5, 5], [5, 84]])[0][..., 3] == 0
    assert not paper[30:90:10, :25].any(), 'without a point on a line the lines stay'
    inside = im.key(a, [[30, 40]])[0][..., 3] == 0
    assert inside[40, 30] and not inside[~figure].any(), 'a point inside the outline keys the paint, not the ground'
    for bad in ([], [[100, 5]], [['a', 5]], [[5]]):
        try:
            im.key(a, bad)
        except ValueError:
            continue
        raise AssertionError('key accepted %r' % (bad,))
    try:
        im.key(a, [[5, 5]], radius=1.5)
    except ValueError as e:
        assert 'radius' in str(e)
    else:
        raise AssertionError('a fractional radius')



def _noisy_gridded(h=120, w=120):
    """A ground graded from top to bottom with seeded compression-like noise and a darker one-pixel grid
    line every 8 pixels, two outlined figures 6 pixels apart, and light paint inside one of them as light
    as the ground. Returns (the picture, the figures' mask)."""
    rng = np.random.default_rng(7)
    a = np.empty((h, w, 4), np.float32)
    a[..., 3] = 1.0
    levels = np.linspace(150, 200, h)[:, None, None] + np.array([0, 25, 50]) + rng.integers(-5, 6, (h, w, 1))
    levels[::8] -= 8
    levels[:, ::8] -= 8
    figure = np.zeros((h, w), bool)
    for x0, x1 in ((30, 60), (66, 96)):
        figure[40:100, x0:x1] = True
        levels[40:100, x0:x1] = 25
    paint = levels[44:96, 2:24].copy()
    levels[44:96, 34:56] = paint                          # inside the first outline, coloured like the ground
    a[..., :3] = np.clip(levels, 0, 255) / 255.0
    return a, figure


def test_ground_seeds_proposes_points_on_the_ground_the_samples_reach():
    a, figure = _noisy_gridded()
    samples = [[4, 4], [4, 60], [4, 115]]
    got = im.ground_seeds(a, samples, step=8, clearance=4)
    assert got == im.ground_seeds(a, samples, step=8, clearance=4), 'the same picture gives the same points'
    pts = got['points']
    assert len(pts) > 40 and got['cells'] == 15 * 15 and [s['point'] for s in got['samples']] == samples
    near = np.zeros_like(figure)
    for x, y in pts:
        near[max(y - 4, 0):y + 5, max(x - 4, 0):x + 5] = True
    assert not (near & figure).any(), 'every point keeps its clearance from the figures'
    assert not any(34 <= x < 56 and 44 <= y < 96 for x, y in pts),         'paint as light as the ground inside an outline holds no sample, so it gets no point'
    assert not any(60 <= x < 66 and 40 <= y < 100 for x, y in pts), 'a gap narrower than the clearance gets none'
    keyed, seeds = im.key(a, pts)
    ground = keyed[..., 3] == 0
    assert not ground[figure].any(), 'the key from the points leaves the figures'
    assert ground[~figure].mean() > 0.95, 'and takes the noisy, gridded ground'
    assert max(s['tolerance'] for s in seeds) <= im.GROUND_DEVIATION
    one = im.ground_seeds(a, [[4, 4]], step=8, clearance=4)
    assert one['ground'] < got['ground'], 'one sample at one end of the gradient reaches less of it'
    for bad in ({'samples': []}, {'samples': [[200, 4]]}, {'step': 0}, {'clearance': -1}, {'tolerance': 0},
                {'deviation': True}):
        kw = dict({'samples': samples}, **bad)
        try:
            im.ground_seeds(a, kw.pop('samples'), **kw)
        except ValueError:
            continue
        raise AssertionError('ground_seeds accepted %r' % (bad,))



def test_texel_levels_round_blender_pixels_to_the_levels_they_store():
    levels = np.arange(256, dtype=np.uint8)
    assert np.array_equal(im.texel_levels(levels.astype(np.float32) / 255.0), levels)
    assert np.array_equal(im.texel_levels([-0.1, 0.0019, 0.0021, 1.2]), [0, 0, 1, 255])


def _atlas(h=6, w=8, level=100):
    a = np.full((h, w, 4), level, np.uint8)
    a[..., 3] = 255
    return a


def test_a_composite_changes_only_hit_texels_and_the_margin_outside_the_islands():
    base = _atlas()
    base[0, 0, :3] = (1, 2, 3)                       # a hand-painted texel
    layer = np.zeros_like(base)
    layer[..., :3] = (200, 10, 20)
    hit = np.zeros(base.shape[:2], bool)
    hit[2:4, 2:4] = True
    inside = np.zeros_like(hit)
    inside[1:5, 1:5] = True                          # one island; hit lies in it
    out, counts = im.composite_layer(base, layer, hit, inside, margin=2)
    assert counts == {'hit': 4, 'margin': 0, 'changed': 4}, 'inside an island nothing spreads'
    assert np.array_equal(out[hit, :3], np.tile([200, 10, 20], (4, 1)))
    assert np.array_equal(out[~hit], base[~hit]), 'every other texel keeps its levels'
    assert (out[..., 3] == 255).all()
    edge = np.zeros_like(hit)
    edge[1:5, 1] = True                              # hit along the island's left border
    out, counts = im.composite_layer(base, layer, edge, inside, margin=1)
    ring = (out != base).any(axis=2) & ~edge
    assert counts['margin'] == int(ring.sum()) and ring.any(), counts
    assert not (ring & inside).any(), 'the margin never enters an island'
    # The column left of it, and the texels above and below its ends with their diagonals.
    assert ring[:, 0].all() and ring[[0, 0, 5, 5], [1, 2, 1, 2]].all() and ring.sum() == 10, ring.astype(int)
    assert out[0, 0, 0] == 200, 'a margin texel takes the hit colour, over what it held'
    assert np.array_equal(out[:, 3:], base[:, 3:])
    same, counts = im.composite_layer(out, layer, edge, inside, margin=1)
    assert np.array_equal(same, out) and counts['changed'] == 0, 'compositing the same source again changes nothing'


def test_the_margin_takes_its_neighbours_in_a_fixed_order():
    vals = np.zeros((3, 3, 1), np.int64)
    filled = np.zeros((3, 3), bool)
    vals[1, 0], vals[0, 1] = 5, 7
    filled[1, 0] = filled[0, 1] = True
    out, ring = im.extend_margin(vals, filled, np.ones((3, 3), bool), 1)
    assert out[1, 1, 0] == 5, 'the left neighbour comes before the one above'
    assert out[0, 0, 0] == 7 and ring.sum() == 6 and not ring[2, 2], (out[..., 0], ring)
    assert np.array_equal(im.extend_margin(vals, filled, np.zeros((3, 3), bool), 3)[0], vals)


def test_texels_at_read_the_nearest_texel_in_blenders_order_and_wrap():
    px = np.arange(4 * 2 * 1).reshape(2, 4, 1)       # rows bottom first: row 0 at v = 0
    got = im.texels_at(px, [(0.1, 0.1), (0.9, 0.9), (0.5, 0.25), (1.1, -0.4), (1.0, 1.0)])
    assert got[:, 0].tolist() == [0, 7, 2, 4, 0], got[:, 0]



def test_the_uv_raster_holds_every_texel_a_triangle_shares_an_area_with():
    tri = np.array([[[1.0, 1.0], [5.0, 1.0], [1.0, 5.0]]])
    got = im.uv_raster(tri, (8, 8))
    assert got[1, 1] and got[1, 4] and got[4, 1] and got[3, 1] and got[2, 2]
    assert not got[4, 4] and not got[0, :].any() and not got[:, 0].any() and not got[1, 5]
    assert got[3, 2] and got[2, 3], 'the hypotenuse x + y = 6 crosses the texels at rows 3, 2 and columns 2, 3'
    assert not got[3, 3] and got.sum() == 10, 'texel (3, 3) only touches it at a corner'
    sliver = np.array([[[2.2, 0.1], [2.3, 0.1], [2.25, 7.9]]])
    assert im.uv_raster(sliver, (8, 8))[:, 2].all() and im.uv_raster(sliver, (8, 8)).sum() == 8, \
        'a sliver between texel centres still takes the texels it crosses'
    assert not im.uv_raster(tri + 100, (8, 8)).any() and not im.uv_raster(np.zeros((1, 3, 2)) + 2, (8, 8)).any()


def test_free_spot_finds_the_lowest_then_leftmost_free_rectangle():
    occ = np.zeros((6, 8), bool)
    occ[0, :5] = True
    occ[1:3, 2] = True
    assert im.free_spot(occ, 3, 2) == (5, 0)
    assert im.free_spot(occ, 4, 2) == (3, 1)
    assert im.free_spot(occ, 8, 3) == (0, 3)
    assert im.free_spot(occ, 9, 1) is None and im.free_spot(np.ones((4, 4), bool), 1, 1) is None


def test_rectangles_are_placed_one_after_another():
    occ = np.zeros((4, 6), bool)
    spots, placed = im.place_rects([(3, 2), (3, 2), (3, 2), (6, 4)], occ)
    assert spots == [(0, 0), (3, 0), (0, 2), None], spots
    assert placed.sum() == 18 and not placed[2:, 3:].any() and not occ.any()


def test_outline_picture_colours_each_mask():
    a = np.array([[True, True, False, False]])
    b = np.array([[True, False, True, False]])
    pic = im.outline_picture(a, b)
    assert pic.shape == (1, 4, 4) and pic.dtype == np.float32
    assert np.allclose(pic[0, :, :3], [im.BOTH_COLOR, im.FIRST_COLOR, im.SECOND_COLOR, (1, 1, 1)])


def _raises(exc, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except exc as e:
        return e
    raise AssertionError('%s did not raise %s' % (fn.__name__, exc.__name__))


def _sheet_with_specks():
    a = np.ones((40, 60, 4), np.float32)
    a[5:35, 10:30, :3] = 0.2                     # the figure, 600 px
    a[15:20, 15:25, :3] = 1.0                    # paper colour the figure encloses: stays ink
    a[17, 20, :3] = 0.0                          # a dot inside that pocket joins the figure
    a[3, 50, :3] = 0.0                           # a speck, 1 px
    a[30:33, 45:48, :3] = 0.5                    # a dot, 9 px
    a[10:25, 40:42, :3] = 0.3                    # a line, 30 px
    return a


def test_clean_removes_the_pieces_under_its_size_and_lists_them():
    a = _sheet_with_specks()
    out, rec = im.clean(a, min_px=10)
    assert rec['dropped'] == [{'box': [50, 3, 51, 4], 'px': 1}, {'box': [45, 30, 48, 33], 'px': 9}], rec
    assert rec['dropped_px'] == 10 and rec['kept'] == 2 and rec['by_alpha'] is False and rec['min_px'] == 10
    assert np.allclose(out[3, 50], 1.0) and np.allclose(out[31, 46], 1.0)
    assert np.allclose(out[10:25, 40:42, :3], 0.3) and np.allclose(out[17, 20, :3], 0.0), 'the line and the pocket stay'
    assert np.allclose(a[3, 50, :3], 0.0), 'the input is not changed'
    keep = np.zeros((40, 60), bool)
    keep[31, 46] = True
    assert [d['px'] for d in im.clean(a, min_px=10, keep=keep)[1]['dropped']] == [1]
    assert [d['px'] for d in im.clean(a)[1]['dropped']] == [1, 30, 9], 'the default size takes the line too'


def test_clean_makes_pieces_transparent_on_a_keyed_picture():
    a = _sheet_with_specks()
    a[..., 3] = np.where((a[..., :3] == 1.0).all(axis=2), 0.0, 1.0)
    out, rec = im.clean(a, min_px=10)
    assert rec['by_alpha'] is True and out[3, 50, 3] == 0.0 and np.allclose(out[3, 50, :3], 0.0)
    for bad in (0, 2.5, True):
        assert 'min_px' in str(_raises(ValueError, im.clean, a, bad))
    assert 'keep' in str(_raises(ValueError, im.clean, a, 10, keep=np.zeros((2, 2), bool)))


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print('ok', name)
