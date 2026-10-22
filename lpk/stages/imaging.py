"""Image arrays without Pillow (numpy): crops, scaling, pixel grids labelled in the source image's
coordinates, the ink of a drawing told from its background (ink_mask, ink_runs, figure_box), contact
sheets and the build-over-reference overlay. PNG input and output and showing a picture in Blender go
through lpk.stages.view (load_image, save_image).

An image is a float32 RGBA array of shape (H, W, 4), top row first, holding the PNG's own
(sRGB-encoded) channel values from 0 to 1: an 8-bit value b loads as b / 255 and saves back as b, so a
load/save round trip of an 8-bit PNG is exact. Palette colours (sRGB tuples) go into arrays as they
are. Pixel coordinates are (x, y) from the top-left corner with pixel centres on integers, as in the
reference views' landmarks."""
import json
import math
import os

import numpy as np

_GLYPH_ROWS = {
    '0': ('###', '#.#', '#.#', '#.#', '###'), '1': ('.#.', '##.', '.#.', '.#.', '###'),
    '2': ('###', '..#', '###', '#..', '###'), '3': ('###', '..#', '.##', '..#', '###'),
    '4': ('#.#', '#.#', '###', '..#', '..#'), '5': ('###', '#..', '###', '..#', '###'),
    '6': ('###', '#..', '###', '#.#', '###'), '7': ('###', '..#', '..#', '.#.', '.#.'),
    '8': ('###', '#.#', '###', '#.#', '###'), '9': ('###', '#.#', '###', '..#', '###'),
    'A': ('.#.', '#.#', '###', '#.#', '#.#'), 'B': ('##.', '#.#', '##.', '#.#', '##.'),
    'C': ('.##', '#..', '#..', '#..', '.##'), 'D': ('##.', '#.#', '#.#', '#.#', '##.'),
    'E': ('###', '#..', '##.', '#..', '###'), 'F': ('###', '#..', '##.', '#..', '#..'),
    'G': ('.##', '#..', '#.#', '#.#', '.##'), 'H': ('#.#', '#.#', '###', '#.#', '#.#'),
    'I': ('###', '.#.', '.#.', '.#.', '###'), 'J': ('..#', '..#', '..#', '#.#', '.#.'),
    'K': ('#.#', '#.#', '##.', '#.#', '#.#'), 'L': ('#..', '#..', '#..', '#..', '###'),
    'M': ('#...#', '##.##', '#.#.#', '#...#', '#...#'), 'N': ('#..#', '##.#', '#.##', '#..#', '#..#'),
    'O': ('.#.', '#.#', '#.#', '#.#', '.#.'), 'P': ('##.', '#.#', '##.', '#..', '#..'),
    'Q': ('.#.', '#.#', '#.#', '##.', '.##'), 'R': ('##.', '#.#', '##.', '#.#', '#.#'),
    'S': ('.##', '#..', '.#.', '..#', '##.'), 'T': ('###', '.#.', '.#.', '.#.', '.#.'),
    'U': ('#.#', '#.#', '#.#', '#.#', '###'), 'V': ('#.#', '#.#', '#.#', '#.#', '.#.'),
    'W': ('#...#', '#...#', '#.#.#', '##.##', '#...#'), 'X': ('#.#', '#.#', '.#.', '#.#', '#.#'),
    'Y': ('#.#', '#.#', '.#.', '.#.', '.#.'), 'Z': ('###', '..#', '.#.', '#..', '###'),
    ' ': ('..', '..', '..', '..', '..'), '-': ('...', '...', '###', '...', '...'),
    '+': ('...', '.#.', '###', '.#.', '...'), '=': ('...', '###', '...', '###', '...'),
    '.': ('.', '.', '.', '.', '#'), ':': ('.', '#', '.', '#', '.'), '_': ('...', '...', '...', '...', '###'),
    '/': ('..#', '..#', '.#.', '#..', '#..'), '(': ('.#', '#.', '#.', '#.', '.#'), ')': ('#.', '.#', '.#', '.#', '#.'),
    '%': ('#.#', '..#', '.#.', '#..', '#.#'), '?': ('###', '..#', '.#.', '...', '.#.'),
    ',': ('..', '..', '..', '.#', '#.'), '|': ('#', '#', '#', '#', '#'), '!': ('#', '#', '#', '.', '#'),
    "'": ('#', '#', '.', '.', '.'), '[': ('##', '#.', '#.', '#.', '##'), ']': ('##', '.#', '.#', '.#', '##'),
    '<': ('..#', '.#.', '#..', '.#.', '..#'), '>': ('#..', '.#.', '..#', '.#.', '#..'),
    '*': ('...', '#.#', '.#.', '#.#', '...'), '#': ('.#.#.', '#####', '.#.#.', '#####', '.#.#.'),
}
GLYPHS = {ch: np.array([[c == '#' for c in row] for row in rows], bool) for ch, rows in _GLYPH_ROWS.items()}
GLYPH_HEIGHT = 5
LABEL_PAD = 1
# Levels of an 8-bit channel by which ink_mask lets a background pixel differ from the border's colour:
# a flat background stored losslessly holds one value, and a render's dither or the rounding of a
# colour conversion moves it by one level; compression noise and paint move it further.
INK_TOLERANCE = 1
# Pixels a side of the largest block a lossy picture is coded in: JPEG codes brightness in blocks of
# 8 pixels and, with colour stored at half resolution (its usual 4:2:0), colour in blocks of 16. The
# error compression leaves beside an edge stays inside the blocks the edge crosses, so a speck of it
# fits in one block and lies less than a block from the drawing.
CODING_BLOCK_PX = 16
# ground_seeds' defaults. The side of a lattice cell, in pixels: each cell of ground gets a point, and
# key's flood joins the points through the ground between them.
GROUND_STEP = 30
# Pixels of ground every proposed point keeps round it: past half a coding block, so its patch lies
# outside the compression error that stays inside the blocks an edge of the drawing crosses.
GROUND_CLEARANCE = CODING_BLOCK_PX // 2 + 1
# The largest tolerance a proposed point's patch may measure, in levels: the grain of a compressed ground.
# A patch over a line or an edge measures their contrast instead, which key would take as ground.
GROUND_DEVIATION = 14
# Levels by which a ground-like pixel may differ from a sample's colour, in every channel: wider than the
# ground's grain (GROUND_DEVIATION), so a sample covers the stretch of a gradient round it.
GROUND_TOLERANCE = 24
# The colour grids and outline pictures draw the pixels an ignore region leaves unread in (hatch).
HATCH_COLOR = (1.0, 0.45, 0.0, 1.0)
# Pixels between the diagonals of hatch: a drawing choice that leaves the picture readable under them.
HATCH_STEP = 6
# clean's default smallest piece of ink it keeps, in pixels: a quarter of a coding block's area, the size of
# a speck, a stray dot or a fragment of a letter. Larger marks (a label, a line) are an ignore region's.
CLEAN_MIN_PX = CODING_BLOCK_PX * CODING_BLOCK_PX // 4
# The colours outline_picture draws: where both masks cover a pixel, where only the first does and where
# only the second does.
BOTH_COLOR = (0.55, 0.55, 0.55)
FIRST_COLOR = (0.9, 0.15, 0.1)
SECOND_COLOR = (0.1, 0.45, 0.95)


def _color(c):
    c = tuple(float(x) for x in c)
    return np.array(c + (1.0,) if len(c) == 3 else c, np.float32)


def rgba(arr):
    """arr as float32 RGBA (H, W, 4), the array every function here takes: uint8 is scaled to 0..1, grey
    and RGB get an opaque alpha. Returns the input itself when it already is float32 RGBA: copy before
    drawing."""
    a = np.asarray(arr)
    a = a.astype(np.float32) / 255.0 if a.dtype == np.uint8 else a.astype(np.float32, copy=False)
    if a.ndim == 2:
        a = a[..., None]
    if a.shape[2] == 1:
        a = np.concatenate([a, a, a], axis=2)
    if a.shape[2] == 3:
        a = np.concatenate([a, np.ones(a.shape[:2] + (1,), np.float32)], axis=2)
    return a


def flatten(arr, bg=(1.0, 1.0, 1.0)):
    """A new opaque array: arr composited over the colour bg (sRGB 0..1, alpha ignored)."""
    a = rgba(arr)
    al = a[..., 3:4]
    out = np.empty_like(a)
    out[..., :3] = a[..., :3] * al + _color(bg)[:3] * (1.0 - al)
    out[..., 3] = 1.0
    return out


def crop(arr, box, fill=(0.0, 0.0, 0.0, 0.0)):
    """A new array of the pixels in box = (x0, y0, x1, y1), x1 and y1 exclusive, in arr's pixels.
    Parts of the box outside the image take `fill`, so crop pixel (i, j) is always source pixel
    (x0 + j, y0 + i): pass (x0, y0) as grid's origin to label the crop in the source's coordinates."""
    a = rgba(arr)
    H, W = a.shape[:2]
    x0, y0, x1, y1 = (int(v) for v in box)
    if x1 <= x0 or y1 <= y0:
        raise ValueError('empty crop box %r' % (box,))
    out = np.empty((y1 - y0, x1 - x0, 4), np.float32)
    out[...] = _color(fill)
    sx0, sy0, sx1, sy1 = max(x0, 0), max(y0, 0), min(x1, W), min(y1, H)
    if sx1 > sx0 and sy1 > sy0:
        out[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = a[sy0:sy1, sx0:sx1]
    return out


def _round(x):
    return int(math.floor(x + 0.5))


def _box_axis(a, n_out, axis):
    """Area-average resampling of axis `axis` to n_out samples: every output sample is the mean of
    the input over its share of the axis, fractional pixels weighted by their covered part (the
    integral of the piecewise-constant signal, read off a cumulative sum)."""
    a = np.moveaxis(a, axis, 0)
    n_in = a.shape[0]
    C = np.concatenate([np.zeros((1,) + a.shape[1:]), np.cumsum(a, axis=0)], axis=0)
    a_ext = np.concatenate([a, np.zeros((1,) + a.shape[1:])], axis=0)
    edges = np.arange(n_out + 1) * (n_in / n_out)
    f = np.minimum(np.floor(edges).astype(np.int64), n_in)
    frac = (edges - f).reshape((-1,) + (1,) * (a.ndim - 1))
    S = C[f] + frac * a_ext[f]
    return np.moveaxis(np.diff(S, axis=0) / (n_in / n_out), 0, axis)


def scale(arr, k):
    """A new array scaled by k (> 0). k >= 1: nearest neighbour, so an integer k turns every pixel into
    a k x k block and pixel edges stay sharp for reading coordinates (a fractional k repeats some
    rows and columns once more than others). k < 1: a box (area-average) filter over premultiplied
    alpha. The size is round(H * k) x round(W * k), at least 1 x 1."""
    a = rgba(arr)
    if k <= 0:
        raise ValueError('scale factor must be positive, got %r' % (k,))
    H, W = a.shape[:2]
    h, w = max(1, _round(H * k)), max(1, _round(W * k))
    if k >= 1:
        ys = (np.arange(h) * H) // h
        xs = (np.arange(w) * W) // w
        return a[ys][:, xs].copy()
    pm = a.astype(np.float64)
    pm[..., :3] *= pm[..., 3:4]
    pm = _box_axis(_box_axis(pm, h, 0), w, 1)
    al = pm[..., 3:4]
    pm[..., :3] = np.where(al > 0, pm[..., :3] / np.maximum(al, 1e-12), 0.0)
    return pm.astype(np.float32)


def _text_mask(s, size):
    cols = []
    for i, ch in enumerate(str(s).upper()):
        if i:
            cols.append(np.zeros((GLYPH_HEIGHT, 1), bool))
        cols.append(GLYPHS.get(ch, GLYPHS['?']))
    m = np.hstack(cols) if cols else np.zeros((GLYPH_HEIGHT, 0), bool)
    return m.repeat(size, axis=0).repeat(size, axis=1)


def text_size(s, size=1):
    """(width, height) in pixels of the string s in the built-in 5-pixel font at integer scale `size`,
    without the label padding."""
    m = _text_mask(s, int(size))
    return m.shape[1], m.shape[0]


def _blend(dst, col, k=1.0):
    """col over dst in place (straight alpha), col's alpha scaled by k."""
    a = float(col[3]) * k
    A = dst[..., 3:4]
    oa = a + A * (1.0 - a)
    dst[..., :3] = np.where(oa > 0, (col[:3] * a + dst[..., :3] * A * (1.0 - a)) / np.maximum(oa, 1e-12), 0.0)
    dst[..., 3:4] = oa


def _paint(arr, x, y, mask, col):
    H, W = arr.shape[:2]
    h, w = mask.shape
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, W), min(y + h, H)
    if x1 <= x0 or y1 <= y0:
        return
    m = mask[y0 - y:y1 - y, x0 - x:x1 - x]
    region = arr[y0:y1, x0:x1]
    sel = region[m]
    _blend(sel, col)
    region[m] = sel


def text(arr, x, y, s, color=(0.0, 0.0, 0.0, 1.0), bg=None, size=1, pad=LABEL_PAD):
    """Draw s into arr in place with the built-in font (digits, A-Z with lower case drawn as upper
    case, space and - + = . , : _ / | ( ) [ ] < > % ? ! ' * #; anything else draws as ?), clipped to
    the array.

    x, y: the top-left corner of the label box in pixels; the glyphs start `pad` pixels inside it.
    color, bg: RGB or RGBA 0..1; bg fills the box when given. size: integer pixel scale of the
    5-pixel-high font. Returns the box (x0, y0, x1, y1), x1 and y1 exclusive."""
    size = int(size)
    m = _text_mask(s, size)
    h, w = m.shape
    box = (x, y, x + w + 2 * pad, y + h + 2 * pad)
    if bg is not None:
        _paint(arr, x, y, np.ones((h + 2 * pad, w + 2 * pad), bool), _color(bg))
    _paint(arr, x + pad, y + pad, m, _color(color))
    return box


def _overlaps(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def grid(arr, step, origin=(0, 0), label_every=None, color=(0.0, 0.47, 1.0, 1.0), zoom=1, size=2):
    """A new array with a pixel grid over arr, labelled in the source image's pixel coordinates.

    step: grid spacing in source pixels (int). origin: the source pixel at arr's top-left corner, the
    crop box's (x0, y0) for a crop. zoom: arr's pixels per source pixel when arr was scaled after
    cropping (scale(crop(...), k) -> zoom=k), so the lines fall on source pixel edges and the labels
    stay in source pixels. A line for source coordinate v is drawn on the array column (row)
    round((v - origin) * zoom): over the pixel v itself at zoom 1, along its left (top) edge when
    zoomed. Lines run at every multiple of step; the multiples of step * label_every are drawn
    solid and labelled, the rest at 40 % opacity. label_every None picks the smallest value that keeps
    labels from overlapping. Column labels sit along the top edge right of their line, row labels
    along the left edge under it (each flips to the other side of its line at the far edge); a row
    label that would cover a column label is left out. color: line and label colour (labels on
    white boxes); size: integer font scale."""
    out = rgba(arr).copy()
    H, W = out.shape[:2]
    step = int(step)
    ox, oy = (int(v) for v in origin)
    col = _color(color)
    solid = col.copy()
    solid[3] = 1.0
    white = _color((1.0, 1.0, 1.0, 1.0))

    def pos(v, o):
        return _round((v - o) * zoom)

    def coords(o, n):
        v, vs = -(-o // step) * step, []
        while pos(v, o) < n:
            vs.append(v)
            v += step
        return vs

    xs, ys = coords(ox, W), coords(oy, H)
    if label_every is None:
        widest = max((text_size(v, size)[0] for v in xs + ys), default=0)
        need = max(widest, GLYPH_HEIGHT * size) + 2 * LABEL_PAD + 3
        label_every = max(1, math.ceil(need / (step * zoom)))
    period = step * int(label_every)
    for v in xs:
        _blend(out[:, pos(v, ox)], col, 1.0 if v % period == 0 else 0.4)
    for v in ys:
        _blend(out[pos(v, oy)], col, 1.0 if v % period == 0 else 0.4)
    boxes = []
    for v in xs:
        if v % period == 0:
            c = pos(v, ox)
            bw = text_size(v, size)[0] + 2 * LABEL_PAD
            x = c + 2 if c + 2 + bw <= W else c - 1 - bw
            boxes.append(text(out, x, 1, v, solid, white, size))
    for v in ys:
        if v % period == 0:
            r = pos(v, oy)
            w, h = text_size(v, size)
            bw, bh = w + 2 * LABEL_PAD, h + 2 * LABEL_PAD
            y = r + 2 if r + 2 + bh <= H else r - 1 - bh
            if not any(_overlaps((1, y, 1 + bw, y + bh), b) for b in boxes):
                text(out, 1, y, v, solid, white, size)
    return out


class InkMaskError(ValueError):
    """A picture whose ink ink_mask cannot tell from its background: its border has no background
    colour (a painted or graded background, a figure filling the frame), or lone pixels stand off the
    background away from the drawing (noise or paint in the background), so no edge read from it can
    be trusted. A picture with a transparent background is read by its alpha instead: key makes a sheet's
    ground transparent, and lpk.intake.crop_views(bg=None) keeps that alpha."""

# The route the refusals name: a picture whose ground is transparent is read by its alpha.
_ALPHA_ROUTE = ('; a picture with a transparent background is read by its alpha instead: key the ground '
                'to transparent with lpk.stages.imaging.key (python -m lpk.host.intake key) and cut the view '
                'from the keyed sheet with its alpha kept (lpk.intake.crop_views(bg=None), crop --alpha)')


def _border(a):
    """The values on the edge of a 2-D grid (pixels of an image, or a mask), each once."""
    H, W = a.shape[:2]
    if H <= 2 or W <= 2:
        return a.reshape((H * W,) + a.shape[2:])
    return np.concatenate([a[0], a[-1], a[1:-1, 0], a[1:-1, -1]])


def runs(mask):
    """(rows, starts, ends) of the runs of True along each row of a (H, W) mask, ends exclusive, in row
    order and then column order."""
    m = np.asarray(mask, bool)
    pad = np.zeros((m.shape[0], m.shape[1] + 2), np.int8)
    pad[:, 1:-1] = m
    d = np.diff(pad, axis=1)
    rows, starts = np.nonzero(d == 1)
    _, ends = np.nonzero(d == -1)
    return rows, starts, ends


def components(mask, connectivity=8):
    """(labels, sizes) of the connected pieces of a (H, W) mask: labels (H, W) int32, 0 off the mask and
    1, 2, ... per piece in the order of its first pixel (row by row); sizes[label] its pixel count,
    sizes[0] the pixels off the mask. connectivity: 8, pixels touching at a corner join, or 4, only
    pixels sharing a side do. Raises ValueError for another connectivity."""
    if connectivity not in (4, 8):
        raise ValueError('connectivity must be 4 or 8, got %r' % (connectivity,))
    m = np.asarray(mask, bool)
    H, W = m.shape
    rows, s, e = runs(m)
    k = 1 if connectivity == 8 else 0
    n = len(rows)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    start = np.searchsorted(rows, np.arange(H + 1)).tolist()
    s_, e_ = s.tolist(), e.tolist()
    for r in range(H - 1):
        i, i1, j, j1 = start[r], start[r + 1], start[r + 1], start[r + 2]
        while i < i1 and j < j1:
            if s_[j] < e_[i] + k and s_[i] < e_[j] + k:
                a, b = find(i), find(j)
                if a != b:
                    parent[max(a, b)] = min(a, b)
            if e_[i] < e_[j]:
                i += 1
            else:
                j += 1
    labels = np.zeros((H, W), np.int32)
    ids = {}
    for k in range(n):
        root = find(k)
        if root not in ids:
            ids[root] = len(ids) + 1
        labels[rows[k], s_[k]:e_[k]] = ids[root]
    return labels, np.bincount(labels.ravel(), minlength=len(ids) + 1)


def _lone(ink, unseen=None):
    """The ink pixels none of whose eight neighbours is ink, leaving out those next to a pixel that is
    not seen (unseen, a (H, W) mask, True where a neighbour lies past the picture's border or in an
    ignore region): what lies there may be ink."""
    H, W = ink.shape
    p = np.pad(ink, 1)
    n = np.zeros((H, W), np.int32)
    for dy in range(3):
        for dx in range(3):
            if (dy, dx) != (1, 1):
                n += p[dy:dy + H, dx:dx + W]
    lone = ink & (n == 0)
    return lone if unseen is None else lone & ~unseen


def grown(mask):
    """A (H, W) bool mask grown by one pixel in all eight directions: its pixels and every pixel touching
    one of them, corners included."""
    p = np.pad(mask, 1)
    row = p[:, :-2] | p[:, 1:-1] | p[:, 2:]
    return row[:-2] | row[1:-1] | row[2:]


def _unseen(unread):
    """The pixels of a picture with a neighbour that is not read: past the picture's border, or in the
    unread mask (H, W), an ignore region."""
    out = grown(unread)
    out[0] = out[-1] = True
    out[:, 0] = out[:, -1] = True
    return out


def _specks(ink, dev, unseen=None):
    """(the ink without its compression specks, the number of specks, how far the farthest pixel of one
    lies from the drawing, 0 without specks). dev: (H, W) each pixel's difference from the background
    in levels of an 8-bit channel. unseen: _unseen's mask, None for a picture whose every pixel is read.

    A lone pixel is noise (nothing drawn is a single pixel), so the largest difference a lone pixel
    shows is a difference noise reaches. A picture without a lone pixel shows no noise, and nothing is
    dropped from it: a small solid piece beside the drawing (a fragment of a label the crop cut, a dot)
    is drawn as far as anything can tell. The drawing is every 8-connected piece of ink that does not
    fit inside one coding block (CODING_BLOCK_PX a side) and holds a pixel differing by more than the
    noise: a large piece no brighter than the noise is noise grown together. A speck is a piece that
    fits inside a block and comes within a block of the drawing: what compression leaves beside an edge.
    Distances are in pixels, the larger of the row and column steps; a speck reaches as far as its
    farthest pixel, which a block's width may put a block further. A pixel next to one that is not seen
    is no lone pixel, and a piece touching what is not seen is no speck: it may go on past the picture's
    border or under an ignore region (a stroke the crop cut), so neither its size nor its noise is
    known."""
    lone = _lone(ink, unseen)
    if not lone.any():
        return ink, 0, 0
    labels, sizes = components(ink, 8)
    n = len(sizes) - 1
    ys, xs = np.nonzero(labels)
    lab = labels[ys, xs]
    lo_x, hi_x = np.full(n + 1, ink.shape[1]), np.full(n + 1, -1)
    lo_y, hi_y = np.full(n + 1, ink.shape[0]), np.full(n + 1, -1)
    np.minimum.at(lo_x, lab, xs)
    np.maximum.at(hi_x, lab, xs)
    np.minimum.at(lo_y, lab, ys)
    np.maximum.at(hi_y, lab, ys)
    small = (hi_x - lo_x < CODING_BLOCK_PX) & (hi_y - lo_y < CODING_BLOCK_PX)
    small[0] = False
    noise = float(dev[lone].max())
    peak = np.full(n + 1, -1.0)
    np.maximum.at(peak, lab, dev[ys, xs])
    drawn = ~small & (peak > noise)
    drawn[0] = False
    if not small.any() or not drawn.any():
        return ink, 0, 0
    reach = np.zeros(ink.shape, np.int32)
    within = drawn[labels]
    near = None
    for d in range(1, 2 * CODING_BLOCK_PX - 1):
        more = grown(within)
        reach[more & ~within] = d
        within = more
        if d == CODING_BLOCK_PX - 1:
            near = within & small[labels]
    speck = np.zeros(n + 1, bool)
    speck[np.unique(labels[near])] = True
    if unseen is not None:
        speck[np.unique(labels[unseen & ink])] = False
    speck[0] = False
    if not speck.any():
        return ink, 0, 0
    drop = speck[labels]
    return ink & ~drop, int(speck.sum()), int(reach[drop].max())


def _ground(a, seen, tol):
    """(ink, dev, by_alpha, bg) of an RGBA array whose seen pixels (a (H, W) mask) are read, as read_ink
    tells them, before it drops specks and looks for lone pixels: ink a (H, W) mask; dev each pixel's
    difference from the background in levels of an 8-bit channel; by_alpha whether the picture is read by
    its alpha; bg the border's median (r, g, b), None when read by alpha. Raises InkMaskError when the
    seen pixels leave no border, or the border has no background."""
    edge = _border(seen)
    if not edge.any():
        raise InkMaskError('ignore regions cover the whole border: there is no background to tell the ink from')
    if bool(((a[..., 3] < 0.5) & seen).any()):
        ink = (a[..., 3] >= 0.5) & seen
        share = float((~_border(ink))[edge].mean())
        if share <= 0.5:
            raise InkMaskError('the picture has transparent pixels, but only %.0f%% of its border is transparent: '
                               'it has no background to tell its ink from' % (100 * share))
        return ink, a[..., 3] * 255.0, True, None
    rgb = a[..., :3].astype(np.float64)
    bg = np.median(_border(rgb)[edge], axis=0)
    dev = np.abs(rgb - bg).max(axis=2) * 255.0
    free = (dev <= tol + 0.5) & seen
    share = float(_border(free)[edge].mean())
    if share <= 0.5:
        raise InkMaskError(
            'only %.0f%% of the border is within %g level(s) of its median colour %s: a painted or graded '
            'background, or a figure filling the frame, leaves no background colour to tell the ink from%s'
            % (100 * share, tol, tuple(int(round(c * 255)) for c in bg), _ALPHA_ROUTE))
    labels, _ = components(free, 4)
    ring = _border(labels)
    return seen & ~np.isin(labels, np.unique(ring[ring > 0])), dev, False, tuple(float(c) for c in bg)


def read_ink(arr, tol=INK_TOLERANCE, ignore=None):
    """The ink of a picture with what its reading dropped: {'mask': ink_mask's mask, 'ignored': the
    pixels left unread (ignore, all False without it), 'specks': the pieces of compression noise left out
    (ink_mask), 'noise_px': how far from the drawing the farthest of them reaches, in pixels (the larger
    of the row and column steps), 0 without one}.

    noise_px is the reach of the specks dropped, how far compression noise reaches from the drawing.
    Noise clings to the drawing's edges too, where it cannot be told from the drawing and stays ink, so
    an edge may sit out to noise_px pixels outside the drawn one; faint pieces of a line that drop with
    the specks put it at most as far inside. The checks reading edges add noise_px to the precision of
    their readings. Ink within tol of the ground's colour reads as background, and nothing bounds that:
    a line drawn in the ground's colour (dark line art on a dark ground) is lost up to its whole width,
    the edge read at its inner side, whatever noise_px says.

    ignore: None, or a (H, W) bool mask of the pixels not to read: the ignore regions of a view
    (lpk.core.views.Views.ignore, rasterised with region_labels). An ignored pixel is neither ink nor
    background: the border's colour, the alpha test, the background's flood and the lone-pixel test
    leave it out, and a pixel or a piece of ink next to it is no lone pixel and no speck, as next to
    the picture's border. A background pocket the figure and a region enclose together reads as ink, as
    a hole the figure encloses does. A reader of the mask finds no edge where ink meets an ignored pixel:
    the drawing may go on under it. Raises InkMaskError as ink_mask does, and when the regions cover the
    whole border; ValueError for an ignore mask of another shape than the picture. arr and tol as
    ink_mask's."""
    a = rgba(arr)
    H, W = a.shape[:2]
    unread = np.zeros((H, W), bool) if ignore is None else np.asarray(ignore, bool)
    if unread.shape != (H, W):
        raise ValueError('ignore must be a mask of the picture, %d x %d pixels; got shape %r'
                         % (W, H, unread.shape))
    ink, dev, by_alpha, _ = _ground(a, ~unread, tol)
    unseen = _unseen(unread)
    ink, specks, noise_px = _specks(ink, dev, unseen)
    lone = _lone(ink, unseen)
    if lone.any():
        ys, xs = np.nonzero(lone)
        route = ("; read by its alpha, such a pixel is opaque paint on the transparent ground: leave it out with "
                 "the view's ignore regions" if by_alpha else
                 "; leave marks that are no part of the figure out with the view's ignore regions, or remove small "
                 "ones with lpk.stages.imaging.clean (python -m lpk.host.intake clean)" + _ALPHA_ROUTE)
        raise InkMaskError('%d lone pixel(s) off the background with no drawing within a coding block (%d px), '
                           'the first at (%d, %d): the background is not clean (noise or paint), so no edge read '
                           'from this picture can be trusted%s' % (len(xs), CODING_BLOCK_PX, xs[0], ys[0], route))
    return {'mask': ink, 'ignored': unread, 'specks': specks, 'noise_px': noise_px}


def ink_mask(arr, tol=INK_TOLERANCE, ignore=None):
    """The ink of a picture: a bool array (H, W), True where something is drawn (the figure, a label),
    False on the background and on the pixels `ignore` leaves unread (read_ink).

    A picture with transparent pixels (alpha under one half anywhere) is read by its alpha: ink is
    alpha of one half or more, the pixels whose centres the drawn shape covers. Any other picture is
    read by its border's colour: the background is every pixel 4-connected to the border through pixels
    within `tol` levels of an 8-bit channel (rounded, every channel) of the border's median colour, and
    the ink is the rest. Lightness and saturation decide nothing: light paint inside a closed outline
    stays ink, and so does a background hole the figure encloses (an arm touching the hip). A
    background of more than one colour (shapes behind the figure) reads as ink where it differs from
    the border's median colour.

    Compression specks are left out of a picture with lone pixels (noise): an 8-connected piece of ink
    that fits inside one coding block (CODING_BLOCK_PX a side) and comes within a block of the drawing,
    a larger piece holding a pixel that differs from the background by more than any lone pixel does.
    Compression leaves such specks beside an edge, and nothing drawn that small can be told from them
    (read_ink counts them); a picture without a lone pixel keeps every piece. Raises InkMaskError,
    saying why, instead of returning a mask it cannot vouch for: when half or more of the border is not
    background (a painted or graded background, or a figure filling the frame), and when an ink pixel
    stands alone farther from the drawing, none of its eight neighbours ink (noise or paint in the
    background: nothing drawn is a single pixel, and an edge read beside one could be the noise's). A
    pixel on the picture's border is never alone: the stroke it belongs to may go on past the border.
    arr: an image array (grey, RGB and uint8 are accepted). tol: INK_TOLERANCE by default; a larger one
    lets a noisier background through, and moves edges inward across soft outlines. ignore: read_ink's."""
    return read_ink(arr, tol, ignore)['mask']


def ground_ink(arr, tol=INK_TOLERANCE, ignore=None):
    """The ink of a picture as read_ink tells it from the ground, before read_ink drops specks or refuses
    lone pixels: a (H, W) bool mask, so a picture with stray marks is read whole, its marks as ink. arr,
    tol and ignore as read_ink's. Raises InkMaskError for a picture without a background, ValueError for
    an ignore mask of another shape than the picture."""
    a = rgba(arr)
    H, W = a.shape[:2]
    unread = np.zeros((H, W), bool) if ignore is None else np.asarray(ignore, bool)
    if unread.shape != (H, W):
        raise ValueError('ignore must be a mask of the picture, %d x %d pixels; got shape %r'
                         % (W, H, unread.shape))
    return _ground(a, ~unread, tol)[0]


def clean(arr, min_px=CLEAN_MIN_PX, tol=INK_TOLERANCE, keep=None):
    """A picture with its small pieces of ink removed: (the cleaned array, a float32 RGBA copy, {'min_px',
    'by_alpha': whether the picture was read by its alpha, 'kept': the pieces of ink left, 'dropped_px':
    the pixels removed, 'dropped': [{'box': [x0, y0, x1, y1] (x1 and y1 exclusive), 'px'}] each piece
    removed, in the order of its first pixel, row by row}).

    The ink is ground_ink's: the pixels the border's background does not reach, or the opaque ones of a
    picture with transparent pixels. Every 8-connected piece of it under min_px
    pixels is removed: made transparent on a picture read by its alpha (its colour kept), painted the
    border's median colour on any other. A piece is the whole connected drawing, so a mark that touches
    the figure, or a line that joins a label to it, belongs to the figure and stays: those are an ignore
    region's or a cleaner picture's. Ground the figure encloses reads as ink, as in read_ink, so a speck
    inside such a pocket joins the figure and stays. A small part drawn apart from the figure (a loose
    lock, a dot of a pattern on the ground) is removed like any speck: read the 'dropped' boxes, and keep
    such a part with keep.

    min_px: the smallest piece kept, in pixels. tol: read_ink's. keep: None, or a (H, W) bool mask; a
    piece with a pixel in it stays. Raises InkMaskError as read_ink does for a picture without a
    background, and ValueError for a min_px under 1 or a keep mask of another shape than the picture."""
    if isinstance(min_px, bool) or not isinstance(min_px, (int, np.integer)) or min_px < 1:
        raise ValueError('min_px must be a whole number of pixels, 1 or more, got %r' % (min_px,))
    a = rgba(arr).copy()
    H, W = a.shape[:2]
    ink, _, by_alpha, bg = _ground(a, np.ones((H, W), bool), tol)
    labels, sizes = components(ink, 8)
    small = sizes < min_px
    small[0] = False
    if keep is not None:
        keep = np.asarray(keep, bool)
        if keep.shape != (H, W):
            raise ValueError('keep must be a mask of the picture, %d x %d pixels; got shape %r' % (W, H, keep.shape))
        small[np.unique(labels[keep & ink])] = False
    drop = small[labels]
    if by_alpha:
        a[drop, 3] = 0.0
    else:
        a[drop, :3] = bg
        a[drop, 3] = 1.0
    dropped = []
    ys, xs = np.nonzero(drop)
    lab = labels[ys, xs]
    for label in np.flatnonzero(small):
        on = lab == label
        dropped.append({'box': [int(xs[on].min()), int(ys[on].min()), int(xs[on].max()) + 1, int(ys[on].max()) + 1],
                        'px': int(sizes[label])})
    return a, {'min_px': int(min_px), 'by_alpha': by_alpha, 'kept': int(len(sizes) - 1 - small.sum()),
               'dropped_px': int(drop.sum()), 'dropped': dropped}


def outline_picture(first, second, ignored=None):
    """Two masks of one view as an image array: white where neither covers a pixel, BOTH_COLOR where both
    do, FIRST_COLOR where only the first does, SECOND_COLOR where only the second does, and the ignored
    pixels hatched (hatch). first, second: (H, W) bools; ignored: None, or (H, W) bools."""
    A, B = np.asarray(first, bool), np.asarray(second, bool)
    out = np.ones(A.shape + (4,), np.float32)
    out[A & B, :3] = BOTH_COLOR
    out[A & ~B, :3] = FIRST_COLOR
    out[B & ~A, :3] = SECOND_COLOR
    if ignored is not None and np.any(ignored):
        hatch(out, ignored)
    return out


def key(arr, points, radius=2):
    """A picture with its ground made transparent, from points picked on the ground: (the keyed array, a
    float32 RGBA copy whose ground pixels have alpha 0 and keep their colour, [{'point': [x, y], 'colour':
    the patch's median (r, g, b) 0..1, 'tolerance': levels, 'pixels': the ground pixels like its colour}]).
    The ink readers then read the picture by its alpha (read_ink).

    points: [[x, y], ...] pixels on the ground, one on each of its colours (the paper, the grid lines and
    their crossings, each end of a gradient), away from the drawing and its lines. radius: a point's
    patch reaches this many pixels on each side, a square of 2 * radius + 1 pixels cut off at the
    picture's edges; the default square of 5 pixels stays inside a small flat area of the ground. Each
    point's colour is its patch's per-channel median, and its tolerance the largest difference of a patch
    pixel from that colour, in levels of an 8-bit channel (every channel), at least INK_TOLERANCE: the
    ground's own noise and grain there, measured, not set. A pixel is like the ground when it lies within
    some point's tolerance of that point's colour, and the ground is every such pixel 4-connected to a
    point through such pixels (so a point on a grid line lets the paper of every cell join through the
    lines), and a pixel the ground encloses on all eight sides (a lone pixel is noise, ink_mask) away
    from the picture's border. A patch that holds some of the drawing takes the drawing's colours as
    ground and keys whatever it reaches through them, the figure included where its outline lets the
    flood in: look at the result and move such a point (its tolerance and 'pixels' stand out). Raises
    ValueError for no point, a point that is not [x, y] inside the picture, or a radius that is not a
    whole number of pixels, 0 or more."""
    if isinstance(radius, bool) or not isinstance(radius, (int, np.integer)) or radius < 0:
        raise ValueError('radius must be a whole number of pixels, 0 or more, got %r' % (radius,))
    a = rgba(arr).copy()
    H, W = a.shape[:2]
    pts = list(points)
    if not pts:
        raise ValueError('key needs at least one point on the ground')
    levels = a[..., :3].astype(np.float64) * 255.0
    colours, index = np.unique(levels.reshape(-1, 3), axis=0, return_inverse=True)
    index = index.reshape(-1)
    near, xy, seeds = np.zeros(len(colours), bool), [], []
    for p in pts:
        try:
            x, y = (int(math.floor(float(c) + 0.5)) for c in p)
        except (TypeError, ValueError):
            raise ValueError('point %r is not [x, y]' % (p,)) from None
        if not (0 <= x < W and 0 <= y < H):
            raise ValueError('point %r lies outside the picture (%d x %d pixels)' % (list(p), W, H))
        colour, tol = patch_colour(levels, x, y, radius)
        like = np.abs(colours - colour).max(axis=1) <= tol + 0.5
        near |= like
        xy.append((x, y))
        seeds.append({'point': [x, y], 'colour': tuple(round(float(c) / 255.0, 3) for c in colour),
                      'tolerance': round(tol, 1), 'like': like})
    labels, _ = components(near[index].reshape(H, W), 4)
    ground = np.isin(labels, np.unique([labels[y, x] for x, y in xy]))
    ground |= _lone(~ground, _unseen(np.zeros((H, W), bool)))
    counts = np.bincount(index[ground.reshape(-1)], minlength=len(colours))
    for s in seeds:
        s['pixels'] = int(counts[s.pop('like')].sum())
    a[ground, 3] = 0.0
    return a, seeds


def patch_colour(levels, x, y, radius):
    """(colour, tolerance) of the square patch round pixel (x, y), as key measures a point: the patch's
    per-channel median (r, g, b) and the largest difference of a patch pixel from it, at least
    INK_TOLERANCE, both in levels of an 8-bit channel. levels: (H, W, 3) floats 0..255; radius: the
    patch reaches this many pixels on each side, cut off at the picture's edges."""
    patch = levels[max(y - radius, 0):y + radius + 1, max(x - radius, 0):x + radius + 1].reshape(-1, 3)
    colour = np.median(patch, axis=0)
    return colour, max(float(INK_TOLERANCE), float(np.abs(patch - colour).max()))


def ground_seeds(arr, samples, step=GROUND_STEP, radius=2, clearance=GROUND_CLEARANCE,
                 deviation=GROUND_DEVIATION, tolerance=GROUND_TOLERANCE):
    """Points for key over a lattice of the picture, proposed from a few samples of its ground: one point
    per cell of `step` pixels where a patch of the ground fits. The route for a ground no handful of points
    keys (a gradient with compression noise, a fine grid).

    samples: [[x, y], ...] pixels on the ground, one on each of its colours (the paper, the ends of a
    gradient, and as many along it as it changes by more than `tolerance`) and one in each area of ground
    the figures or frames enclose. A pixel is ground-like within `tolerance` levels (every channel of an
    8-bit picture) of a sample's patch colour (patch_colour), and the ground is each 8-connected piece of
    ground-like pixels that holds a sample: a light area of a figure inside its outline holds none, so it
    gets no point. A point stands where every pixel within `clearance` pixels (a square) is ground, at a
    patch whose tolerance (patch_colour, `radius`) is at most `deviation` levels; each cell takes, among
    the candidates every second pixel of it, the one of the largest such tolerance (the first in row
    order among equals), so its patch holds the ground's grain and key's flood from it crosses the
    compression noise. A cell with no candidate gets no point: a strip of ground narrower than twice
    `clearance` (a pocket between two legs) keeps its ink until a sample or a point of its own covers it.

    Returns {'points': [[x, y], ...] in row order of the cells, the input of key, 'samples': [{'point',
    'colour' (r, g, b) 0..1, 'tolerance'}], 'ground': the share of the picture's pixels the samples' ground
    holds, 'cells': the lattice's cell count}. Raises ValueError for no sample, a sample that is not [x, y]
    inside the picture, a step that is not a whole number of pixels, 1 or more, a radius or clearance that
    is not one, 0 or more, or a deviation or tolerance that is not a number above 0."""
    for name, value, least in (('step', step, 1), ('radius', radius, 0), ('clearance', clearance, 0)):
        if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < least:
            raise ValueError('%s must be a whole number of pixels, %d or more, got %r' % (name, least, value))
    for name, value in (('deviation', deviation), ('tolerance', tolerance)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not value > 0:
            raise ValueError('%s must be a number of levels above 0, got %r' % (name, value))
    levels = rgba(arr)[..., :3].astype(np.float64) * 255.0
    H, W = levels.shape[:2]
    pts = list(samples)
    if not pts:
        raise ValueError('ground_seeds needs at least one sample on the ground')
    xy, found = [], []
    like = np.zeros((H, W), bool)
    for p in pts:
        try:
            x, y = (int(math.floor(float(c) + 0.5)) for c in p)
        except (TypeError, ValueError):
            raise ValueError('sample %r is not [x, y]' % (p,)) from None
        if not (0 <= x < W and 0 <= y < H):
            raise ValueError('sample %r lies outside the picture (%d x %d pixels)' % (list(p), W, H))
        colour, tol = patch_colour(levels, x, y, radius)
        like |= np.abs(levels - colour).max(axis=2) <= tolerance
        xy.append((x, y))
        found.append({'point': [x, y], 'colour': tuple(round(float(c) / 255.0, 3) for c in colour),
                      'tolerance': round(tol, 1)})
    labels, _ = components(like, 8)
    held = np.unique([labels[y, x] for x, y in xy])
    ground = np.isin(labels, held[held > 0])
    k = 2 * clearance + 1
    total = np.pad(ground.astype(np.int64), ((clearance + 1, clearance), (clearance + 1, clearance)))
    total = total.cumsum(0).cumsum(1)
    clear = (total[k:, k:] - total[:-k, k:] - total[k:, :-k] + total[:-k, :-k]) == k * k
    points = []
    for y0 in range(0, H, step):
        for x0 in range(0, W, step):
            best = None
            for y in range(y0, min(y0 + step, H), 2):
                for x in range(x0, min(x0 + step, W), 2):
                    if not clear[y, x]:
                        continue
                    tol = patch_colour(levels, x, y, radius)[1]
                    if tol <= deviation and (best is None or tol > best[0]):
                        best = (tol, [x, y])
            if best is not None:
                points.append(best[1])
    return {'points': points, 'samples': found, 'ground': round(float(ground.mean()), 4),
            'cells': len(range(0, H, step)) * len(range(0, W, step))}


def ink_runs(mask, axis, index):
    """The runs of ink along one row or one column of a mask (ink_mask): [(first, last), ...] in order,
    the first and the last ink pixel of each run, both inclusive, as pixel coordinates along the line.

    axis: 'x' for the row y = index (the runs' x coordinates), 'y' for the column x = index (their y).
    An outline crosses the line at a run's first or last pixel; a run that starts or ends on the
    picture's edge may go on past it. Raises ValueError for another axis, a mask that is not 2-D, or an
    index outside the mask."""
    m = np.asarray(mask)
    if m.ndim != 2:
        raise ValueError('ink_runs takes a 2-D mask, got shape %r' % (m.shape,))
    if axis not in ('x', 'y'):
        raise ValueError("axis must be 'x' (a row) or 'y' (a column), got %r" % (axis,))
    n = m.shape[0] if axis == 'x' else m.shape[1]
    if isinstance(index, bool) or not isinstance(index, (int, np.integer)) or not 0 <= index < n:
        raise ValueError('%s %r lies outside the mask (0 to %d)' % ('row' if axis == 'x' else 'column', index, n - 1))
    idx = np.flatnonzero(m[index] if axis == 'x' else m[:, index])
    if not idx.size:
        return []
    cut = np.flatnonzero(np.diff(idx) > 1)
    firsts, lasts = np.concatenate([idx[:1], idx[cut + 1]]), np.concatenate([idx[cut], idx[-1:]])
    return [(int(f), int(e)) for f, e in zip(firsts, lasts)]


def figure_box(image, tol=INK_TOLERANCE):
    """The box (x0, y0, x1, y1), x1 and y1 exclusive, round all the ink of a picture (ink_mask): the crop
    box of its figure, whose height in pixels is y1 - y0.

    image: an image array, or a 2-D bool mask already made; tol: ink_mask's. Everything drawn counts:
    a label, a second figure, a cast shadow or an overlay left in a capture (the 3D cursor, a floor
    line) widens the box. Raises InkMaskError when the picture has no clean background (ink_mask) or no
    ink."""
    m = np.asarray(image)
    if not (m.dtype == bool and m.ndim == 2):
        m = ink_mask(image, tol)
    rows, cols = np.flatnonzero(m.any(axis=1)), np.flatnonzero(m.any(axis=0))
    if not rows.size:
        raise InkMaskError('the picture holds no ink: nothing differs from its background')
    return int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1


def sheet(images, columns, labels=None, pad=8, bg=(1.0, 1.0, 1.0), size=2, color=(0.0, 0.0, 0.0), height=None,
          figure_px=None, crop=False):
    """A contact sheet: images (arrays) in rows of `columns`, left to right, top to bottom.

    Every cell is as wide as the widest image and as high as the highest; an image sits centred
    horizontally at the top of its cell, composited over bg. labels: one string per image (None or ''
    for none), drawn in `color` at font scale `size` in a strip above the image and clipped to the cell.
    pad: pixels between cells and around the sheet. The sheet is
    columns * cell_w + (columns + 1) * pad wide, with columns no more than the number of images.

    height: None leaves every image at its size. A number of pixels scales every image (scale) so its
    figure is that tall, to compare captures and drawings at one figure height: the figure's height is
    figure_px's entry for the image, or else the height of its figure_box. figure_px: None, or one
    entry per image, None or the figure's height in that image's pixels (a drawing's calibrated crown
    to sole rows, a painted picture figure_box refuses). Raises InkMaskError, naming the image, when a
    figure must be found and cannot be; ValueError for a height or a figure height that is not positive,
    or a figure_px of another length than images.

    crop: True cuts the images to their figures first (_figure_crops), `pad` pixels round them, at the
    scale they have: a capture keeps the viewport's landscape frame, so a standing figure fills a third
    of its width, and a row of whole frames shrinks every figure when the sheet is read downscaled. The
    rows are cut to the union of every figure's rows, so the figures keep one floor line across the
    sheet when the images share one framing (the captures of one review do), and the columns of each
    image to its own figure. An image whose figure figure_box cannot find keeps its whole frame."""
    if crop:
        images = _figure_crops(images, pad)
    if height is not None:
        if not height > 0:
            raise ValueError('height must be a positive number of pixels, got %r' % (height,))
        if figure_px is not None and len(figure_px) != len(images):
            raise ValueError('figure_px holds %d entries for %d images' % (len(figure_px), len(images)))
        scaled = []
        for i, im in enumerate(images):
            fh = None if figure_px is None else figure_px[i]
            if fh is None:
                try:
                    x0, y0, x1, y1 = figure_box(im)
                except InkMaskError as e:
                    raise InkMaskError('image %d: %s; give its figure height in figure_px' % (i, e)) from None
                fh = y1 - y0
            if not fh > 0:
                raise ValueError('image %d: the figure height must be positive, got %r' % (i, fh))
            scaled.append(scale(im, height / fh) if height != fh else im)
        images = scaled
    ims = [flatten(i, bg) for i in images]
    if not ims:
        raise ValueError('no images for the sheet')
    n = len(ims)
    columns = max(1, min(int(columns), n))
    rows = -(-n // columns)
    cw = max(i.shape[1] for i in ims)
    ch = max(i.shape[0] for i in ims)
    lh = GLYPH_HEIGHT * size + 2 * LABEL_PAD + 2 if labels else 0
    out = np.empty((rows * (lh + ch) + (rows + 1) * pad, columns * cw + (columns + 1) * pad, 4), np.float32)
    out[...] = _color(bg)[:3].tolist() + [1.0]
    for k, im in enumerate(ims):
        r, c = divmod(k, columns)
        x0, y0 = pad + c * (cw + pad), pad + r * (lh + ch + pad)
        lab = labels[k] if labels and k < len(labels) else None
        if lab:
            text(out[y0:y0 + lh, x0:x0 + cw], 0, 0, lab, color, None, size)
        h, w = im.shape[:2]
        xi = x0 + (cw - w) // 2
        out[y0 + lh:y0 + lh + h, xi:xi + w] = im
    return out


def _figure_crops(images, pad):
    """The images cut for sheet(crop=True): each to the columns of its own figure_box and all to the rows
    of the union of their boxes, `pad` pixels wider on every side and clipped to the image; an image
    figure_box refuses stays whole and adds no rows to the union."""
    boxes = []
    for image in images:
        try:
            boxes.append(figure_box(image))
        except InkMaskError:
            boxes.append(None)
    found = [b for b in boxes if b is not None]
    if not found:
        return list(images)
    top, bottom = min(b[1] for b in found) - pad, max(b[3] for b in found) + pad
    out = []
    for image, b in zip(images, boxes):
        if b is None:
            out.append(image)
            continue
        a = rgba(image)
        H, W = a.shape[:2]
        out.append(a[max(0, top):min(H, bottom), max(0, b[0] - pad):min(W, b[2] + pad)].copy())
    return out


def _segments(arr, segs, col):
    """Opaque 1-pixel lines (x0, y0, x1, y1) in place: max(|dx|, |dy|) + 1 samples per segment, each
    rounded to the nearest pixel centre, clipped to the array."""
    segs = np.asarray(segs, np.float64).reshape(-1, 4)
    if not len(segs):
        return
    H, W = arr.shape[:2]
    n = np.ceil(np.abs(segs[:, 2:] - segs[:, :2]).max(axis=1)).astype(np.int64) + 1
    idx = np.repeat(np.arange(len(segs)), n)
    start = np.cumsum(n) - n
    t = (np.arange(n.sum()) - start[idx]) / np.maximum(n[idx] - 1, 1)
    xi = np.floor(segs[idx, 0] + t * (segs[idx, 2] - segs[idx, 0]) + 0.5).astype(np.int64)
    yi = np.floor(segs[idx, 1] + t * (segs[idx, 3] - segs[idx, 1]) + 0.5).astype(np.int64)
    keep = (xi >= 0) & (xi < W) & (yi >= 0) & (yi < H)
    arr[yi[keep], xi[keep]] = col


def _outline(pts):
    p = np.asarray(pts, np.float64)
    return np.concatenate([p, np.roll(p, -1, axis=0)], axis=1)


def polygon_mask(shape, pts):
    """A (H, W) bool mask, shape (H, W, ...), of the polygon pts [(x, y), ...] (pixel coordinates, any
    simple polygon): the pixels whose centres pass the even-odd crossing test, plus the pixels its
    outline passes through, so slivers thinner than a pixel still count."""
    H, W = shape[:2]
    m = np.zeros((H, W), bool)
    P = np.asarray(pts, np.float64)
    x0, x1 = max(int(math.ceil(P[:, 0].min())), 0), min(int(math.floor(P[:, 0].max())), W - 1)
    y0, y1 = max(int(math.ceil(P[:, 1].min())), 0), min(int(math.floor(P[:, 1].max())), H - 1)
    if x1 >= x0 and y1 >= y0:
        X = np.arange(x0, x1 + 1, dtype=np.float64)[None, :]
        Y = np.arange(y0, y1 + 1, dtype=np.float64)[:, None]
        inside = np.zeros((y1 - y0 + 1, x1 - x0 + 1), bool)
        xj, yj = P[-1]
        for xi, yi in P:
            if yi != yj:
                cross = (yi > Y) != (yj > Y)
                xint = xi + (Y - yi) * (xj - xi) / (yj - yi)
                inside ^= cross & (X < xint)
            xj, yj = xi, yi
        m[y0:y1 + 1, x0:x1 + 1] = inside
    _segments(m, _outline(P), True)
    return m


def fill_polygon(arr, pts, color):
    """Fill the polygon pts [(x, y), ...] (pixel coordinates, any simple polygon) in place with an
    opaque colour: the pixels of polygon_mask."""
    arr[polygon_mask(arr.shape, pts)] = _color(color)


def region_labels(shape, polygons):
    """(H, W) int32 for a picture of shape (H, W, ...): 0 on the pixels no polygon covers and k on those
    the k-th of polygons (each [(x, y), ...]) covers (polygon_mask), the first one where they overlap.
    Its pixels above 0 are read_ink's ignore mask of a view's ignore regions, in their order."""
    out = np.zeros(shape[:2], np.int32)
    for k, pts in enumerate(polygons, 1):
        out[polygon_mask(shape, pts) & (out == 0)] = k
    return out


def hatch(arr, mask, color=HATCH_COLOR, step=HATCH_STEP):
    """Draw the True pixels of a (H, W) mask hatched over arr (H, W, 4) in place, so the picture shows
    through: its outline (the pixels with a neighbour off it) and diagonal lines every `step` pixels,
    in an opaque color. Returns arr."""
    m = np.asarray(mask, bool)
    H, W = m.shape
    yy, xx = np.mgrid[0:H, 0:W]
    arr[(m & grown(~m)) | (m & ((xx + yy) % int(step) == 0))] = _color(color)
    return arr


def overlay(reference, faces_json, palette=None, box=None, zoom=1, background=(60 / 255, 60 / 255, 60 / 255)):
    """The build over its reference in three panels side by side: the reference, the build's faces
    flat in their palette colours, and the build's edges (red) over the reference; the fit's
    marked points are blue crosses on the last two.

    reference: the reference picture's array (lpk.stages.view.load_image reads a file). faces_json: the JSON written by
    review.project (path or the loaded dict): faces as (depth, palette key, pixel points), far faces
    painted first. palette: {key: sRGB rgb 0..1}, default the JSON's own 'pal'; colours are used as
    they are (they already are sRGB; a gamma on top washes them out). Unknown keys paint magenta.
    box: (x0, y0, x1, y1) in reference pixels to cut every panel to; zoom: scale() factor of the
    result. background: the flat panel's colour behind the build's faces, sRGB 0..1. Transparent
    reference pixels are composited over white.
    Returns the array."""
    ref = flatten(reference)
    faces = faces_json
    if isinstance(faces, (str, os.PathLike)):
        with open(faces, encoding='utf-8') as f:
            faces = json.load(f)
    pal = faces.get('pal', {}) if palette is None else palette
    flat = np.empty_like(ref)
    flat[...] = _color(background)
    for _, key, pts in sorted(faces['faces'], key=lambda fc: -fc[0]):
        rgb = np.clip(np.asarray(pal.get(key, (1.0, 0.0, 1.0)), np.float64)[:3], 0.0, 1.0)
        fill_polygon(flat, pts, tuple(rgb))
    wire = ref.copy()
    segs = [_outline(pts) for _, _, pts in faces['faces'] if len(pts) > 1]
    if segs:
        _segments(wire, np.concatenate(segs), _color((1.0, 0.0, 0.0)))
    blue = _color((0.0, 160 / 255, 1.0))
    for x, y in faces.get('marks', ()):
        cross = [(x - 6, y + d, x + 6, y + d) for d in (-1, 0, 1)] + [(x + d, y - 6, x + d, y + 6) for d in (-1, 0, 1)]
        for im in (flat, wire):
            _segments(im, cross, blue)
    panels = [ref, flat, wire]
    if box is not None:
        panels = [crop(p, box, (1.0, 1.0, 1.0, 1.0)) for p in panels]
    out = np.concatenate(panels, axis=1)
    return scale(out, zoom) if zoom != 1 else out


# -- atlas texels ------------------------------------------------------------------------------------------
#
# An atlas array is uint8 of shape (H, W, 4) in Blender's pixel order: row 0 at v = 0 (the bottom), the
# 8-bit levels of a byte image, whose pixels Blender gives as level / 255.
# A mask over an atlas, (H, W) bool, is in the same order; texel coordinates are (column, row), u times the
# width and v times the height.

# The neighbours a margin texel takes its value from, as (row step, column step), in the order a tie
# takes: the four sides, then the corners.
MARGIN_NEIGHBOURS = ((0, -1), (0, 1), (-1, 0), (1, 0), (-1, -1), (-1, 1), (1, -1), (1, 1))


def texel_levels(values):
    """Blender image pixels (floats, an 8-bit level b as b / 255) as uint8 levels, rounded to the nearest:
    a byte image's pixels read back as the levels it stores, and levels / 255 written back store them."""
    return np.clip(np.rint(np.asarray(values, np.float64) * 255.0), 0, 255).astype(np.uint8)


def _shifted(a, dy, dx):
    """a moved so out[y, x] = a[y + dy, x + dx], zero (False) where that lies outside."""
    out = np.zeros_like(a)
    h, w = a.shape[:2]
    out[max(0, -dy):h - max(0, dy), max(0, -dx):w - max(0, dx)] = \
        a[max(0, dy):h + min(0, dy), max(0, dx):w + min(0, dx)]
    return out


def extend_margin(values, filled, open_, steps):
    """A bake margin on arrays: `steps` rounds, each giving every texel of `open_` that is not filled yet
    the value of its first filled neighbour in MARGIN_NEIGHBOURS order, as filled at the end of the round
    before. values: (H, W, C); filled, open_: bool (H, W). Deterministic; no texel outside open_ changes.
    Returns (the values with the ring written, the ring: bool (H, W), the texels written)."""
    vals = np.array(values, copy=True)
    done = np.asarray(filled, bool).copy()
    open_ = np.asarray(open_, bool)
    ring = np.zeros_like(done)
    for _ in range(int(steps)):
        new = np.zeros_like(done)
        take = np.zeros_like(vals)
        for dy, dx in MARGIN_NEIGHBOURS:
            pick = _shifted(done, dy, dx) & open_ & ~done & ~new
            take[pick] = _shifted(vals, dy, dx)[pick]
            new |= pick
        if not new.any():
            break
        vals[new] = take[new]
        done |= new
        ring |= new
    return vals, ring


def composite_layer(base, layer, hit, inside, margin):
    """One colour source composited over an atlas: the colour channels of `layer` replace those of `base`
    on the texels the source's bake rays hit, then on the bake margin round them, the texels outside every
    island (~inside) within `margin` rounds of a hit texel (extend_margin), so nearest-texel sampling at an
    island's border shows the source's colour; every other texel, and the alpha channel everywhere, keeps
    base's levels exactly. base, layer: atlas arrays (uint8 (H, W, 4)); hit, inside: bool (H, W); margin:
    texels. Returns (the composite, {'hit': texels hit, 'margin': margin texels written, 'changed': texels
    whose levels differ from base's})."""
    base = np.asarray(base, np.uint8)
    hit = np.asarray(hit, bool)
    rgb = base[..., :3].copy()
    rgb[hit] = np.asarray(layer, np.uint8)[..., :3][hit]
    rgb, ring = extend_margin(rgb, hit, ~np.asarray(inside, bool), margin)
    out = base.copy()
    out[..., :3] = rgb
    changed = (out != base).any(axis=2)
    return out, {'hit': int(hit.sum()), 'margin': int(ring.sum()), 'changed': int(changed.sum())}


def texels_at(pixels, uv):
    """The texels under UV points, nearest texel: pixels (H, W, C) in Blender's order (row 0 at v = 0);
    uv (N, 2). u and v wrap into [0, 1) as a repeating texture reads them; the texel of (u, v) is column
    floor(u W), row floor(v H). Returns (N, C)."""
    pixels = np.asarray(pixels)
    h, w = pixels.shape[:2]
    uv = np.asarray(uv, np.float64).reshape(-1, 2)
    x = np.floor(np.mod(uv[:, 0], 1.0) * w).astype(np.int64) % w
    y = np.floor(np.mod(uv[:, 1], 1.0) * h).astype(np.int64) % h
    return pixels[y, x]


def uv_raster(tris, shape):
    """The texels a set of triangles touches: (H, W) bool, True on every texel whose square (column x
    covers [x, x + 1], row y covers [y, y + 1]) shares an area with a triangle (the separating axis test
    on the square's sides and the triangle's edge normals; an edge of no length gives no axis). It holds
    every texel a bake writes for the triangles, and the ones they only graze. tris: (T, 3, 2) in texels,
    (u times the width, v times the height); shape: (H, W). Parts outside the grid are cut off."""
    H, W = int(shape[0]), int(shape[1])
    out = np.zeros((H, W), bool)
    for t in np.asarray(tris, np.float64).reshape(-1, 3, 2):
        lo, hi = t.min(axis=0), t.max(axis=0)
        x0, y0 = max(0, int(np.floor(lo[0]))), max(0, int(np.floor(lo[1])))
        x1, y1 = min(W, int(np.ceil(hi[0]))), min(H, int(np.ceil(hi[1])))
        if x1 <= x0 or y1 <= y0:
            continue
        cx, cy = np.meshgrid(np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5)
        keep = np.ones(cx.shape, bool)
        for k in range(3):
            e = t[(k + 1) % 3] - t[k]
            n = np.array([-e[1], e[0]])
            if not n.any():
                continue
            p = t @ n
            c = cx * n[0] + cy * n[1]
            r = (abs(n[0]) + abs(n[1])) / 2
            keep &= (c + r > p.min()) & (c - r < p.max())
        out[y0:y1, x0:x1] |= keep
    return out


def free_spot(occupied, width, height):
    """(column, row) of the free rectangle of `width` by `height` texels in the (H, W) bool mask
    `occupied` (True: taken) that starts lowest, then leftmost, rows counted from v = 0; None when none
    fits. Read off a summed-area table, so the search is exact."""
    occ = np.asarray(occupied, bool)
    H, W = occ.shape
    w, h = int(width), int(height)
    if w < 1 or h < 1 or w > W or h > H:
        return None
    S = np.zeros((H + 1, W + 1), np.int64)
    S[1:, 1:] = occ.astype(np.int64).cumsum(axis=0).cumsum(axis=1)
    taken = S[h:, w:] - S[:-h, w:] - S[h:, :-w] + S[:-h, :-w]
    rows, cols = np.nonzero(taken == 0)
    if not len(rows):
        return None
    return int(cols[0]), int(rows[0])


def place_rects(sizes, occupied):
    """Rectangles placed one after another in free space: each (width, height) of `sizes`, in order, at
    free_spot of `occupied` with the rectangles placed before it taken. Returns ([(column, row) or None per
    rectangle], (H, W) bool: the placed rectangles' texels). `occupied` is not changed; a rectangle that
    finds no place takes none."""
    occ = np.array(occupied, bool)
    placed = np.zeros_like(occ)
    spots = []
    for w, h in sizes:
        spot = free_spot(occ, w, h)
        spots.append(spot)
        if spot is not None:
            x, y = spot
            occ[y:y + int(h), x:x + int(w)] = True
            placed[y:y + int(h), x:x + int(w)] = True
    return spots, placed
