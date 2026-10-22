"""Reference intake on plain data: cut a reference sheet into view images with their views.json
entries, draw labelled pixel grids of a view (its landmarks marked, its ignore regions hatched), derive
calibrations from the crops and from measured landmarks, sample palette colours, and merge measurements
into views.json.

Every function takes image arrays (lpk.stages.imaging's float32 RGBA, top row first) and plain data and
returns arrays and dicts; decoding and writing PNGs is the caller's (lpk.host.intake on the host,
lpk.stages.view in Blender). views.json is a dict here: read_views and write_views read and write the
file, update_views merges into the dict.

    from lpk import intake
    cut = intake.crop_views(sheet, {'front': (40, 60, 720, 1550), 'side': (800, 60, 1450, 1550)}, 'sheet.png')
    data = intake.update_views(intake.read_views(path), views=cut['views'])   # cut['images'] go to refs/
    intake.update_views(data, landmarks={'front': {'crown': [338, 130], 'sole': [338, 1465]}})
    intake.update_views(data, views={'front': {'calibration': intake.rows_calibration(data, 'front', 1.9)},
                                     'side': {'calibration': intake.rows_of_calibration(data, 'side', 'front')}})
    intake.write_views(path, data)
    grid = intake.grid_view(front, box=(250, 100, 430, 300), step=10, zoom=3, landmarks=data['landmarks']['front'])
    intake.sample_colours(front, {'shirt': [338, 600]})['colours']   # {'shirt': (r, g, b)} for PALETTE

Every pixel coordinate in views.json is in the view image's own pixels (refs/<view>.png), the space every
grid here is labelled in, whatever its zoom. A crop records where it came from ('source': sheet, box,
scale): view pixel (px, py) is sheet pixel (box x0 + px / scale, box y0 + py / scale). Landmarks are
measured by a human on the grids or by deterministic sampling: a grid presents pixels, it does not make
an LLM's reading of them exact."""
import json
import math
import os
import re

import numpy as np

from lpk.stages import imaging, numerical

SECTIONS = ('views', 'landmarks', 'widths_px', 'traces')
MARK_COLOR = (1.0, 0.0, 1.0, 1.0)
VIEW_NAME = re.compile(r'^[A-Za-z0-9_.-]+$')
# grid_view's spacing (view pixels) and zoom for a whole view, where labels every GRID_STEP pixels stay
# readable at the view's own size, and for a box, enlarged so a pixel is a block a point can be read on.
GRID_STEP, GRID_ZOOM = 50, 1
BOX_GRID_STEP, BOX_GRID_ZOOM = 10, 3


def read_views(path):
    """The views.json dict at path; {'views': {}} when the file does not exist."""
    if not os.path.exists(path):
        return {'views': {}}
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def write_views(path, data):
    """Write the views.json dict to path, UTF-8 with LF line ends and indent 1, keys in their order,
    through a temporary file, so a failed dump never leaves half a file. Returns path."""
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(data, f, indent=1)
        f.write('\n')
    os.replace(tmp, path)
    return path


def _plain(v):
    """v with tuples, numpy values and vectors turned into JSON lists and numbers."""
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in v.items()}
    if isinstance(v, (str, bytes)) or v is None:
        return v
    if hasattr(v, 'tolist'):
        return _plain(v.tolist())
    if isinstance(v, (list, tuple)) or hasattr(v, '__iter__'):
        return [_plain(x) for x in v]
    return v


def _tidy(x):
    """An integral float as int, so derived pixel values stay integers in views.json."""
    return int(x) if isinstance(x, float) and x.is_integer() else x


def _num(x):
    return isinstance(x, (int, float, np.integer, np.floating)) and not isinstance(x, bool) and math.isfinite(x)


def _box(box):
    try:
        x0, y0, x1, y1 = box
    except (TypeError, ValueError):
        raise ValueError('a box is (x0, y0, x1, y1), got %r' % (box,)) from None
    if not all(isinstance(v, (int, float, np.integer, np.floating)) and float(v).is_integer() for v in box):
        raise ValueError('box %r must hold whole pixels' % (box,))
    x0, y0, x1, y1 = (int(v) for v in box)
    if x1 <= x0 or y1 <= y0:
        raise ValueError('empty box %r (x1 and y1 are exclusive and must exceed x0 and y0)' % (box,))
    return x0, y0, x1, y1


def crop_views(sheet, boxes, sheet_path, scale=1, bg=(1.0, 1.0, 1.0)):
    """Cut a reference sheet into one image per view, with each view's views.json fields.

    sheet: the sheet's image array. boxes: {view: (x0, y0, x1, y1)} in sheet pixels, x1 and y1
    exclusive; a box may reach past the sheet's edge, the outside filled with bg. View names are file
    names: letters, digits, _ . - (VIEW_NAME). sheet_path: the sheet's path as the views record it,
    relative to the views.json folder; rows_of_calibration and crop_of_calibration compare it to tell
    crops of one sheet. scale: the size factor of every crop (> 0), applied after cutting by
    lpk.stages.imaging.scale: nearest neighbour at 1 and above, so every sheet pixel stays a sharp block
    and a landmark read on the crop maps back exactly; a box filter below 1. bg: the colour (sRGB 0..1)
    transparent pixels are composited over, None to keep the alpha (a sheet whose ground was keyed to
    transparent, so the ink readers read the views by their alpha).

    Returns {'images': {view: array}, 'views': {view: {'image': 'refs/<view>.png', 'size': [width,
    height], 'source': {'sheet': sheet_path, 'box': [x0, y0, x1, y1], 'scale': scale}}}}: write each image
    to its 'image' path beside views.json and merge the fields with update_views(data, views=...), which
    keeps a view's other fields. A view cut anew at another box or scale moves every pixel measured on
    it: measure its landmarks, widths, traces and calibration again. Raises ValueError for a bad view
    name, a box that is not four whole pixels enclosing some, or a scale that is not positive."""
    if not scale > 0:
        raise ValueError('scale must be positive, got %r' % (scale,))
    cuts = {}
    for name, box in boxes.items():
        if not isinstance(name, str) or not VIEW_NAME.match(name):
            raise ValueError('view name %r: use letters, digits, _ . - only' % (name,))
        cuts[name] = _box(box)
    fill = (0.0, 0.0, 0.0, 0.0) if bg is None else tuple(float(c) for c in bg)[:3] + (1.0,)
    images, views = {}, {}
    for name, box in cuts.items():
        a = imaging.crop(sheet, box, fill)
        if bg is not None:
            a = imaging.flatten(a, bg)
        if scale != 1:
            a = imaging.scale(a, scale)
        images[name] = a
        views[name] = {'image': 'refs/%s.png' % name, 'size': [int(a.shape[1]), int(a.shape[0])],
                       'source': {'sheet': sheet_path, 'box': list(box), 'scale': _plain(scale)}}
    return {'images': images, 'views': views}


def _sources(data, view, of):
    vs = data.get('views', {})
    out = []
    for name in (view, of):
        src = vs.get(name, {}).get('source') if isinstance(vs.get(name), dict) else None
        if not isinstance(src, dict) or not all(k in src for k in ('sheet', 'box', 'scale')):
            raise ValueError('view %r has no crop source in views.json: cut it with crop_views' % (name,))
        out.append(src)
    if out[0]['sheet'] != out[1]['sheet']:
        raise ValueError('views %r and %r come from different sheets (%s, %s)' % (view, of, out[0]['sheet'],
                                                                                 out[1]['sheet']))
    return out


def crop_of_calibration(data, view, of):
    """The crop_of calibration of `view` as a crop of `of`, both cut from one sheet by crop_views: the
    corner of view's box in of's pixels and the ratio of their scales. data: the views.json dict.
    Returns the calibration dict for update_views(data, views={view: {'calibration': ...}}). Raises
    ValueError when a view has no crop source or the two come from different sheets."""
    sv, so = _sources(data, view, of)
    k = so['scale']
    origin = [_tidy((sv['box'][0] - so['box'][0]) * k), _tidy((sv['box'][1] - so['box'][1]) * k)]
    return {'mode': 'crop_of', 'of': of, 'origin_px': origin, 'zoom': _tidy(sv['scale'] / k)}


def rows_of_calibration(data, view, of):
    """The rows_of calibration of `view` from `of`, both cut from one sheet at one scale by crop_views:
    the row offset between their boxes. Valid only when the sheet draws both views at one size on one
    ground line (a turnaround sheet); views drawn at different sizes need their own calibrations.
    data: the views.json dict. Returns the calibration dict for update_views. Raises ValueError when a
    view has no crop source, the sheets differ or the crops were scaled differently."""
    sv, so = _sources(data, view, of)
    if sv['scale'] != so['scale']:
        raise ValueError('views %r and %r were cropped at scales %r and %r: rows_of needs one scale'
                         % (view, of, sv['scale'], so['scale']))
    return {'mode': 'rows_of', 'of': of, 'row_offset_px': _tidy((sv['box'][1] - so['box'][1]) * sv['scale'])}


def rows_calibration(data, view, height_m):
    """The 'rows' calibration of `view` from its measured landmarks 'crown' and 'sole': their rows taken
    as height_m metres apart. The height runs to that crown: put it where the brief's height is measured
    to (the top of the hair, a crest), not on a part above it the height leaves out (an ear, a horn).

    data: the views.json dict. height_m: the model's height in metres, from the brief or the human.
    Returns {'mode': 'rows', 'height_m', 'crown_px', 'feet_px'} for update_views(data, views={view:
    {'calibration': ...}}). Raises ValueError for a height that is not a positive number, a view without
    both landmarks, or a sole that is not below the crown."""
    if not _num(height_m) or height_m <= 0:
        raise ValueError('height_m %r: give the height in metres, a positive number' % (height_m,))
    lm = data.get('landmarks', {}).get(view, {})
    missing = [k for k in ('crown', 'sole') if k not in lm]
    if missing:
        raise ValueError('view %r has no landmark %s: measure it on the grid first' % (view, ' or '.join(missing)))
    crown, sole = lm['crown'][1], lm['sole'][1]
    if not sole > crown:
        raise ValueError('view %r: the sole row %r must lie below the crown row %r' % (view, sole, crown))
    return {'mode': 'rows', 'height_m': _tidy(float(height_m)), 'crown_px': crown, 'feet_px': sole}


def update_views(data, **sections):
    """Merge sections into a views.json dict, in place, and return it.

    sections, each optional, every pixel value in its view's own pixels:
      landmarks={view: {name: [x, y]}}, widths_px={view: {name: px}}: set or replace single entries.
      views={view: {field: value}}: set fields of a view (image, size, source, calibration, mid_px,
        zero_px, facing, note, ignore, ...); a field's value is replaced whole, never merged, so no field
        of an earlier calibration mode and no region dropped from an ignore field survives. ignore:
        {trace name: the reason}, the view's ignore regions (lpk.core.views.Views.ignore).
      traces={name: {'view': view, 'px': [[x, y], ...]}}: set or replace whole traces; an ignore
        region's trace is a closed polygon round the pixels to leave unread.
    A value None removes that entry (a whole view's dict, a field, a landmark, a trace). Existing keys
    keep their place, new ones are appended; tuples, numpy values and vectors are stored as lists and
    numbers. Raises ValueError for an unknown section, a section or a view's entry that is not a dict, or
    a section of data that is not an object, before changing anything."""
    unknown = [k for k in sections if k not in SECTIONS]
    if unknown:
        raise ValueError('unknown sections %s; sections: %s' % (', '.join(unknown), ', '.join(SECTIONS)))
    for sec, upd in sections.items():
        if not isinstance(upd, dict):
            raise ValueError('section %s must be a dict, got %s' % (sec, type(upd).__name__))
        if sec != 'traces':
            for k, fields in upd.items():
                if fields is not None and not isinstance(fields, dict):
                    raise ValueError('%s.%s must be a dict or None, got %s' % (sec, k, type(fields).__name__))
        if not isinstance(data.get(sec, {}), dict):
            raise ValueError('views.json section %s is not an object; fix it by hand' % sec)
    for sec in SECTIONS:
        if sec not in sections:
            continue
        dst = data.setdefault(sec, {})
        for k, val in sections[sec].items():
            k = str(k)
            if val is None:
                dst.pop(k, None)
            elif sec == 'traces':
                dst[k] = _plain(val)
            else:
                inner = dst.get(k)
                if not isinstance(inner, dict):
                    inner = dst[k] = {}
                for f, x in val.items():
                    if x is None:
                        inner.pop(str(f), None)
                    else:
                        inner[str(f)] = _plain(x)
    return data


def marks(arr, landmarks, origin, zoom, color=MARK_COLOR, arm=3):
    """Draw landmarks as crosses with their names on arr, a grid of a view, in place: a landmark (x, y)
    in view pixels sits at the centre of its zoomed pixel, (x - origin) * zoom + (zoom - 1) / 2.
    landmarks: {name: [x, y]}; entries that are not a pair, and crosses off the array, are skipped.
    origin: the view pixel the array's top-left pixel shows; zoom: array pixels per view pixel; arm:
    the cross's half length in pixels."""
    H, W = arr.shape[:2]
    col = np.array(color, np.float32)
    for key, p in landmarks.items():
        if not (isinstance(p, (list, tuple)) and len(p) == 2):
            continue
        cx = int(math.floor((p[0] - origin[0]) * zoom + (zoom - 1) / 2 + 0.5))
        cy = int(math.floor((p[1] - origin[1]) * zoom + (zoom - 1) / 2 + 0.5))
        if not (0 <= cx < W and 0 <= cy < H):
            continue
        arr[cy, max(cx - arm, 0):cx + arm + 1] = col
        arr[max(cy - arm, 0):cy + arm + 1, cx] = col
        imaging.text(arr, cx + arm + 1, cy + 1, key, color, (1.0, 1.0, 1.0, 1.0), 1)


def _hatched(arr, labels, origin, zoom):
    """The region labels under each pixel of arr, a grid of the view whose top-left pixel shows view
    pixel `origin` at `zoom` grid pixels per view pixel, after drawing the regions hatched over arr in
    place (lpk.stages.imaging.hatch). Pixels outside the view take 0."""
    h, w = arr.shape[:2]
    H, W = labels.shape
    ys = origin[1] + np.floor((np.arange(h) + 0.5) / zoom).astype(np.int64)
    xs = origin[0] + np.floor((np.arange(w) + 0.5) / zoom).astype(np.int64)
    oy, ox = (ys >= 0) & (ys < H), (xs >= 0) & (xs < W)
    lab = np.zeros((h, w), np.int32)
    lab[np.ix_(oy, ox)] = labels[np.ix_(ys[oy], xs[ox])]
    if lab.any():
        imaging.hatch(arr, lab > 0)
    return lab


def _region_names(arr, lab, names):
    """Each region's name at the top-left corner of its hatching in arr (a grid), in place."""
    for k, name in enumerate(names, 1):
        ys, xs = np.nonzero(lab == k)
        if len(xs):
            imaging.text(arr, int(xs.min()) + 1, int(ys.min()) + 1, name, imaging.HATCH_COLOR,
                         (1.0, 1.0, 1.0, 1.0), 1)


def _labels(shape, regions):
    """(labels (H, W): 0 where a pixel is read, k inside the k-th region, the region names in order) of
    ignore regions {name: {'px': polygon}} over a picture of `shape`."""
    regions = regions or {}
    return imaging.region_labels(shape, [r['px'] for r in regions.values()]), list(regions)


def grid_view(arr, box=None, step=None, zoom=None, landmarks=None, regions=None):
    """A labelled pixel grid of a view, or of one region of it (a head, a hand), for a human to read
    pixels on.

    arr: the view's image array; transparent pixels show white. box: (x0, y0, x1, y1) in the view's
    pixels, x1 and y1 exclusive, None for the whole view; parts of it outside the image are white.
    step: the grid spacing in view pixels. zoom: grid pixels per view pixel; an integer keeps every
    view pixel a sharp block, below 1 gives an overview of a large view. None takes GRID_STEP and
    GRID_ZOOM for a whole view, BOX_GRID_STEP and BOX_GRID_ZOOM for a box. Labels are the view's own pixel
    coordinates at any box and zoom (lpk.stages.imaging.grid with the box's corner as origin), so a point
    measured on the grid goes into views.json as it is. landmarks: {name: [x, y]} drawn as magenta
    crosses with their names (marks), None for none. regions: the view's ignore regions as
    lpk.core.views.Views.ignore gives them, drawn hatched under the grid, each with its name.

    Returns the grid array. Raises ValueError for a box that is not four whole pixels enclosing some."""
    step = step or (GRID_STEP if box is None else BOX_GRID_STEP)
    zoom = zoom or (GRID_ZOOM if box is None else BOX_GRID_ZOOM)
    whole = imaging.flatten(arr)
    H, W = whole.shape[:2]
    x0, y0, x1, y1 = (0, 0, W, H) if box is None else _box(box)
    labels, names = _labels(whole.shape, regions)
    a = whole if box is None else imaging.crop(whole, (x0, y0, x1, y1), (1.0, 1.0, 1.0, 1.0))
    if zoom != 1:
        a = imaging.scale(a, zoom)
    lab = _hatched(a, labels, (x0, y0), zoom)
    g = imaging.grid(a, step, (x0, y0), zoom=zoom)
    _region_names(g, lab, names)
    if landmarks:
        marks(g, landmarks, (x0, y0), zoom)
    return g


def sample_colours(arr, points, radius=2, regions=None, seeds=()):
    """Palette colours sampled from a view: the per-channel median of a small square patch round each
    point, so line art, noise and compression specks inside a flat area of colour do not tint the result,
    with what in each patch may make the colour another one's.

    arr: the view's image array; transparent pixels count as white, as on the grids. points: {colour
    name: [x, y]} in the view's own pixels; pick each in a flat area of that colour, away from lines, and
    a colour drawn in several flat tones (cel steps, a lit and a shadow side) at its lit tone. radius:
    the patch reaches this many pixels on each side of the point, a square of 2 * radius + 1 pixels a
    side, cut off at the image's edges; the default square of 5 pixels stays inside a small flat area
    while the median still drops a stray line pixel. regions: the view's ignore regions
    (lpk.core.views.Views.ignore), whose pixels are never ground. seeds: the seeds of the ground key the
    view was cut from (lpk.stages.imaging.key's, [{'point', 'colour', 'tolerance', ...}]), () for none.

    Ground: the view's ink is read by lpk.stages.imaging.read_ink, its ignore regions unread; a patch
    pixel that is neither ink nor ignored is ground, so a point on the ground or across the outer
    outline samples the ground's colour (on a keyed view, white). Light paint on a ground of its own
    colour reads as ground where its outline is open. Keyed: a colour within some seed's tolerance of
    that seed's colour (levels of an 8-bit channel, every channel, as imaging.key compares them) keys as
    ground wherever the figure's outline opens onto the ground. A seed whose patch holds a line thinner
    than the patch takes the line's contrast with the paper as its tolerance.

    Returns {'colours': {name: (r, g, b)}, sRGB 0..1 rounded to 3 decimals, the format PALETTE takes;
    'ground': {name: the share of its patch's pixels that are ground, 0..1 rounded to 3 decimals}, None
    when read_ink refuses the picture (a painted ground, noise); 'ink_refused': read_ink's reason, None
    when it read the picture; 'keyed': {name: [{'point': the seed's point, 'tolerance': its tolerance,
    'levels': the colour's distance from the seed's colour}]}, empty lists where no seed takes it}.
    Raises ValueError for a negative or fractional radius or a point that is not [x, y] inside the image."""
    if isinstance(radius, bool) or not isinstance(radius, (int, np.integer)) or radius < 0:
        raise ValueError('radius must be a whole number of pixels, 0 or more, got %r' % (radius,))
    raw = imaging.rgba(arr)
    a = imaging.flatten(raw)
    H, W = a.shape[:2]
    labels, _ = _labels(raw.shape, regions)
    refused = None
    try:
        ink = imaging.read_ink(raw, ignore=labels > 0)
    except imaging.InkMaskError as e:
        ground, refused = None, str(e)
    else:
        ground = ~ink['mask'] & ~ink['ignored']
    seeds = [s for s in seeds or () if isinstance(s, dict) and _num(s.get('tolerance'))
             and isinstance(s.get('colour'), (list, tuple)) and len(s['colour']) == 3]
    colours, shares, keyed = {}, {}, {}
    for name, p in points.items():
        try:
            x, y = (int(math.floor(float(c) + 0.5)) for c in p)
        except (TypeError, ValueError):
            raise ValueError('point %r: %r is not [x, y]' % (name, p)) from None
        if not (0 <= x < W and 0 <= y < H):
            raise ValueError('point %r at %r lies outside the image (%d x %d pixels)' % (name, list(p), W, H))
        box = (slice(max(y - radius, 0), y + radius + 1), slice(max(x - radius, 0), x + radius + 1))
        colour = tuple(round(float(c), 3) for c in np.median(a[box][..., :3].reshape(-1, 3), axis=0))
        colours[name] = colour
        if ground is not None:
            shares[name] = round(float(ground[box].mean()), 3)
        keyed[name] = []
        for s in seeds:
            far = max(abs(c - k) for c, k in zip(colour, s['colour'])) * 255.0
            if far <= s['tolerance'] + 0.5:
                keyed[name].append({'point': list(s.get('point', ())), 'tolerance': s['tolerance'],
                                    'levels': round(far, 1)})
    return {'colours': colours, 'ground': None if ground is None else shares, 'ink_refused': refused,
            'keyed': keyed}


def compare_copy(original, copy, tol=imaging.INK_TOLERANCE, regions=None):
    """How a cleaned or generated copy of a view lies against the original it was made from: (the
    picture, imaging.outline_picture of the copy's ink over the original's, {'size', 'metrics'}).

    original, copy: image arrays of one size, cut from their pictures with the same box and scale so a
    pixel of one is the same point of the drawing in the other. Each one's ink is imaging.ground_ink's,
    which drops no speck and refuses no lone pixel, so a cluttered original is read whole. regions: the
    view's ignore regions (lpk.core.views.Views.ignore), read on neither side.

    metrics is lpk.stages.numerical.metrics with the copy as the build and the original as the target:
    'extra_px' and the 'extra' regions are ink the copy has and the original lacks (drawn by the tool),
    'missing_px' and the 'missing' regions ink the copy removed; the contour distances are None while
    regions leave pixels unread. A clean copy removes clutter and adds nothing: read the boxes of both
    kinds of region against the pictures, since this compares pixels and does not know which ink is
    clutter. Raises ValueError for pictures of different sizes, InkMaskError for a picture without a
    background."""
    o, c = imaging.rgba(original), imaging.rgba(copy)
    if o.shape != c.shape:
        raise ValueError('the copy is %d x %d pixels and the original %d x %d: cut both with the same box '
                         'and scale' % (c.shape[1], c.shape[0], o.shape[1], o.shape[0]))
    H, W = o.shape[:2]
    unread = (_labels(o.shape, regions)[0] > 0) if regions else np.zeros((H, W), bool)
    drawn = imaging.ground_ink(o, tol, unread)
    made = imaging.ground_ink(c, tol, unread)
    picture = imaging.outline_picture(made, drawn, unread if unread.any() else None)
    return picture, {'size': [W, H], 'metrics': numerical.metrics(made, drawn, unread)}

