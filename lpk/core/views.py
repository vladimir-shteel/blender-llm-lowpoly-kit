"""Reference views of a model (views.json): images, calibrations, landmarks, widths and traced outlines.

A view's landmarks stay in that view's own pixels; a calibration turns pixels into model metres. A view's
'size' [width, height] is the size of its image when its landmarks were read: a re-cropped or rescaled
image moves every landmark, so measure the landmarks again after cutting a view anew.

Calibration modes (the 'calibration' object of a view, field 'mode'):

    rows          height_m, crown_px, feet_px: the crown and sole rows of the model, of known height.
    rows_of       of, row_offset_px: another view's metres per pixel and sole row; row py of this view
                  is row py + row_offset_px of the other.
    crop_of       of, origin_px [x0, y0], zoom: a zoomed crop of another view; pixel (px, py) here is
                  (x0 + px / zoom, y0 + py / zoom) there.
    scale_figure  figure_top_px, ground_px, figure_height_m: a reference figure of known height standing
                  on the model's ground line.
    known_span    a, b, metres, ground_px (axis): a known distance between two landmarks of the view
                  (names or [x, y]); axis 'x' or 'y' measures the horizontal or vertical span, no axis
                  the straight line. The soles stand on ground_px.
    none          no metric scale: the dimensions come from text, and calib() refuses.

View fields the calibrations read: mid_px (the midline column, default the image centre; a 'rows'
calibration takes the midline only as model()'s argument), zero_px and facing (a side view's column of
model y = 0, and the way the model faces in the picture: 'front', 'back', 'left' or 'right'
(SIDE_FACINGS), or 'turned' for any other turn, whose columns mix width and depth).

A view's 'ignore' field names its ignore regions, {trace name: the reason}: traces drawn on the view,
closed polygons whose pixels the ink readers leave unread (Views.ignore).

The module is plain Python (the standard library only), so it runs on the host and in Blender alike and
a model module's props() may import it. A calibration's points are plain (x, y, z) tuples in metres."""
import json
import math
import os

# Required calibration fields per mode, in the order they are documented.
MODES = {
    'rows': ('height_m', 'crown_px', 'feet_px'),
    'rows_of': ('of', 'row_offset_px'),
    'crop_of': ('of', 'origin_px', 'zoom'),
    'scale_figure': ('figure_top_px', 'ground_px', 'figure_height_m'),
    'known_span': ('a', 'b', 'metres', 'ground_px'),
    'none': (),
}
SIDE_FACINGS = ('left', 'right')


class CalibrationError(ValueError):
    """A view's pixels cannot be turned into metres: an unknown mode, missing or impossible fields, views
    calibrated from each other in a cycle, or a view without a metric scale (mode 'none')."""



class _Frame:
    """What every calibration shares: the midline default of model() and side-view depth.

    A subclass provides w and h (the view's size in pixels), mpp (metres per view pixel), z(py) and
    m(px_len). mid_px: the view's midline column, None for the image centre. zero_px, facing: a side
    view's column of model y = 0 and the way the model faces in the picture ('left' or 'right'); a
    model facing image right has its front (-Y) towards larger px."""
    mid_px = None
    zero_px = None
    facing = None

    def _frame(self, size, mid_px, zero_px, facing):
        self.w, self.h = size
        self.mid_px = mid_px
        self.zero_px = zero_px
        self.facing = facing

    def model(self, px, py, y=0.0, mid_px=None):
        """A picture point in model space, (x, y, z) in metres (the model stands at the origin, soles on
        z = 0). y: the depth to give the point. mid_px: the midline column, default the view's mid_px or
        the image centre."""
        mid = mid_px if mid_px is not None else (self.w / 2 if self.mid_px is None else self.mid_px)
        return (self.m(px - mid), y, self.z(py))

    def side_y(self, px):
        """Model y (metres, - is forward) of column px of a side view, from the view's zero_px and
        facing."""
        if self.zero_px is None or self.facing not in SIDE_FACINGS:
            raise CalibrationError("side-view depth needs the view's zero_px and facing 'left' or 'right' "
                                   "(got zero_px %r, facing %r)" % (self.zero_px, self.facing))
        return self.m(self.zero_px - px) if self.facing == 'right' else self.m(px - self.zero_px)

    def side(self, px, py):
        """A side-view point as model (y, z) in metres."""
        return self.side_y(px), self.z(py)


class Calib(_Frame):
    """Pixel <-> model metres for a view calibrated by the rows of the crown and the soles: one scale
    (metres per pixel) for both axes, the soles on z = 0. The image's centre column is the midline
    unless a caller passes its own (mid_px). size is (width, height) in pixels."""

    def __init__(self, height_m, crown_px, feet_px, size):
        self.w, self.h = size
        self.mpp = height_m / (feet_px - crown_px)
        self.feet_px = feet_px

    def model(self, px, py, y=0.0, mid_px=None):
        """A picture point in model space, (x, y, z) in metres (the model stands at the origin, not at
        the reference). mid_px: the character's midline column when the drawing is not centred in the
        picture."""
        mid = self.w / 2 if mid_px is None else mid_px
        return ((px - mid) * self.mpp, y, (self.feet_px - py) * self.mpp)

    def z(self, py):
        return (self.feet_px - py) * self.mpp

    def m(self, px_len):
        return px_len * self.mpp


class _Linear(_Frame):
    """A calibration with its own scale and sole row (feet_px): z = (feet_px - py) * mpp."""

    def z(self, py):
        return (self.feet_px - py) * self.mpp

    def m(self, px_len):
        return px_len * self.mpp


class ScaleFigureCalib(_Linear):
    """Mode scale_figure: a reference figure figure_height_m tall (metres) whose top is on row
    figure_top_px and whose soles, like the model's, are on row ground_px. size: (width, height) of the
    view in pixels; the other fields as in _Frame."""

    def __init__(self, figure_height_m, figure_top_px, ground_px, size, mid_px=None, zero_px=None, facing=None):
        if ground_px <= figure_top_px:
            raise CalibrationError('scale_figure: ground_px %r must be below figure_top_px %r'
                                   % (ground_px, figure_top_px))
        self._frame(size, mid_px, zero_px, facing)
        self.mpp = figure_height_m / (ground_px - figure_top_px)
        self.feet_px = ground_px


class KnownSpanCalib(_Linear):
    """Mode known_span: span_px pixels of the view are `metres` long; the soles are on row ground_px.
    size: (width, height) of the view in pixels; the other fields as in _Frame."""

    def __init__(self, metres, span_px, ground_px, size, mid_px=None, zero_px=None, facing=None):
        if not span_px > 0 or not metres > 0:
            raise CalibrationError('known_span: the span (%r px) and its length (%r m) must be positive'
                                   % (span_px, metres))
        self._frame(size, mid_px, zero_px, facing)
        self.mpp = metres / span_px
        self.feet_px = ground_px


class RowsOfCalib(_Frame):
    """Mode rows_of: the scale and ground of another view's calibration `of`, with this view's rows
    shifted: z(py) = of.z(py + row_offset_px). Lengths and depths go through of.m, so a side view
    calibrated this way gives exactly the numbers of the other view's calibration applied by hand.
    size: (width, height) of this view in pixels; mid_px, zero_px, facing are this view's own."""

    def __init__(self, of, row_offset_px, size, mid_px=None, zero_px=None, facing=None):
        self.of = of
        self.row_offset_px = row_offset_px
        self._frame(size, mid_px, zero_px, facing)

    @property
    def mpp(self):
        return self.of.mpp

    @property
    def feet_px(self):
        """The sole row in this view's pixels."""
        return self.of.feet_px - self.row_offset_px

    def z(self, py):
        return self.of.z(py + self.row_offset_px)

    def m(self, px_len):
        return self.of.m(px_len)


class CropOfCalib(_Frame):
    """Mode crop_of: this view is a crop of the view calibrated by `of`, scaled by zoom, its top-left
    pixel at origin_px (x0, y0) of that view. Every method maps the pixel to the other view's,
    (x0 + px / zoom, y0 + py / zoom), and delegates, so the crop measures exactly like its source;
    zero_px and facing are the source's. mid_px: the midline column in the crop's pixels, None for the
    source's own default."""

    def __init__(self, of, origin_px, zoom, size, mid_px=None):
        if not zoom > 0:
            raise CalibrationError('crop_of: zoom must be positive, got %r' % (zoom,))
        self.of = of
        self.x0, self.y0 = origin_px
        self.zoom = zoom
        self.w, self.h = size
        self.mid_px = mid_px

    def to_of(self, px, py):
        """The pixel of the source view under crop pixel (px, py)."""
        return self.x0 + px / self.zoom, self.y0 + py / self.zoom

    @property
    def mpp(self):
        return self.of.mpp / self.zoom

    @property
    def feet_px(self):
        """The sole row in the crop's pixels (usually outside the crop)."""
        return (self.of.feet_px - self.y0) * self.zoom

    @property
    def zero_px(self):
        z = self.of.zero_px
        return None if z is None else (z - self.x0) * self.zoom

    @property
    def facing(self):
        return self.of.facing

    def z(self, py):
        return self.of.z(self.y0 + py / self.zoom)

    def m(self, px_len):
        return self.of.m(px_len / self.zoom)

    def model(self, px, py, y=0.0, mid_px=None):
        mid = self.mid_px if mid_px is None else mid_px
        fx, fy = self.to_of(px, py)
        return self.of.model(fx, fy, y, None if mid is None else self.x0 + mid / self.zoom)

    def side_y(self, px):
        return self.of.side_y(self.x0 + px / self.zoom)

    def side(self, px, py):
        return self.of.side(*self.to_of(px, py))


def measure(calib, landmarks, widths_px, width_k=1.0):
    """Model-space measurements of a view from its calibration: the helper a model module's props() takes its
    numbers from. calib: the view's calibration (Views.calib); landmarks: {name: (px, py)} of the view
    (Views.landmarks); widths_px: {name: pixels} (Views.widths); width_k: the factor span() scales the
    horizontal distances by, 1.0 for an orthographic front. A concept turned three-quarters mixes the
    torso's width with part of its depth in its picture widths, and a factor chosen for that picture
    (under 1 where the turn widens them) scales them toward frontal widths: an approximation, not an
    inverse of the projection, so check the widths against an orthographic view where there is one.

    Returns {'z': {landmark: its height in metres}, 'dist': dist(a, b), the picture distance in metres
    between two landmarks, 'w': {name: the width in metres}, 'span': span(a, b, k=width_k), the horizontal
    distance in metres between two landmarks times k}. Pure: reads nothing but its arguments."""
    z = {k: calib.z(p[1]) for k, p in landmarks.items()}

    def dist(a, b):
        (ax, ay), (bx, by) = landmarks[a][:2], landmarks[b][:2]
        return calib.m(math.hypot(ax - bx, ay - by))
    w = {k: calib.m(v) for k, v in widths_px.items()}

    def span(a, b, k=width_k):
        return calib.m(abs(landmarks[a][0] - landmarks[b][0])) * k
    return {'z': z, 'dist': dist, 'w': w, 'span': span}



def image_size(path):
    """(width, height) of a PNG read from its header, without decoding the image. Raises ValueError for
    a file that is not a PNG."""
    with open(path, 'rb') as f:
        head = f.read(24)
    if head[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('%s is not a PNG' % path)
    return int.from_bytes(head[16:20], 'big'), int.from_bytes(head[20:24], 'big')


class Views:
    """views.json of a model, read once: its views in declaration order and accessors for their data.

    path: the views.json file; image paths in it are relative to its folder. `data` is the file as read."""

    def __init__(self, path):
        self.path = path
        self.root = os.path.dirname(os.path.abspath(path))
        with open(path, encoding='utf-8') as f:
            self.data = json.load(f)
        self._calibs = {}
        self._resolving = []

    @property
    def names(self):
        return list(self.data.get('views', {}))

    def view(self, name):
        return self.data['views'][name]

    def image(self, name):
        """The absolute path of view `name`'s image."""
        return os.path.join(self.root, self.data['views'][name]['image'])

    def size(self, name):
        return tuple(self.data['views'][name]['size'])

    def landmarks(self, name):
        return self.data.get('landmarks', {}).get(name, {})

    def widths(self, name):
        return self.data.get('widths_px', {}).get(name, {})

    def trace(self, name):
        """The trace `name`, {'view': view, 'px': [[x, y], ...]}."""
        return self.data['traces'][name]

    def ignore(self, name):
        """The ignore regions of view `name`: {trace name: {'why': the reason the view's 'ignore' field
        gives, 'px': the trace's polygon [[x, y], ...] in the view's pixels}}, in the field's order, empty
        when the view declares none. lpk.stages.imaging.region_labels rasterises them for read_ink's
        ignore= and lpk.stages.imaging.hatch draws them. Raises ValueError, naming each problem, for a field
        that is not {trace name: a non-empty reason}, or that names a trace views.json lacks, one drawn on
        another view or one of fewer than three points (a polygon needs three corners to enclose pixels)."""
        own = self.data['views'][name].get('ignore')
        if own is None:
            return {}
        if not isinstance(own, dict):
            raise ValueError('view %r: ignore must be {trace name: the reason}, got %r' % (name, own))
        traces = self.data.get('traces') if isinstance(self.data.get('traces'), dict) else {}
        problems = []
        for t, why in own.items():
            tr = traces.get(t)
            if not isinstance(tr, dict):
                problems.append('ignore names trace %r, which the traces section lacks' % (t,))
            elif tr.get('view') != name:
                problems.append('ignore names trace %r, which is drawn on view %r' % (t, tr.get('view')))
            elif not (isinstance(tr.get('px'), list) and len(tr['px']) >= 3):
                problems.append('ignore names trace %r, which has fewer than three points and encloses nothing'
                                % (t,))
            if not (isinstance(why, str) and why.strip()):
                problems.append('ignore: trace %r needs its reason, a non-empty string, got %r' % (t, why))
        if problems:
            raise ValueError('view %r: %s' % (name, '; '.join(problems)))
        return {t: {'why': why, 'px': traces[t]['px']} for t, why in own.items()}

    def calibration(self, name):
        return self.data['views'][name]['calibration']

    def calib(self, name):
        """View `name`'s calibration object, built once and cached.

        Mode 'rows' gives a Calib: its own crown and sole rows and height, the midline an argument of
        model() (the image centre by default; the view's mid_px is not applied). The other modes give
        ScaleFigureCalib, KnownSpanCalib, RowsOfCalib or CropOfCalib, whose model() defaults to the
        view's mid_px (a crop_of view without one: its source's midline). Every one offers
        model(px, py, y=0, mid_px=None) -> (x, y, z), z(py), m(px_len) and mpp; side views with zero_px
        and facing also side(px, py) -> (y, z). rows_of and crop_of build the view they derive from
        first. Raises CalibrationError for an unknown mode, missing fields, a cycle of views
        calibrated from each other, and mode 'none' (no metric scale)."""
        if name not in self._calibs:
            if name in self._resolving:
                chain = self._resolving[self._resolving.index(name):] + [name]
                raise CalibrationError('views calibrated from each other: %s' % ' -> '.join(chain))
            self._resolving.append(name)
            try:
                self._calibs[name] = self._new_calib(name)
            finally:
                self._resolving.pop()
        return self._calibs[name]

    def _new_calib(self, name):
        views = self.data.get('views', {})
        if name not in views:
            need = ' (needed by %r)' % self._resolving[-2] if len(self._resolving) > 1 else ''
            raise CalibrationError('no view %r in views.json%s; views: %s' % (name, need, ', '.join(views)))
        v = views[name]
        c = v.get('calibration')
        if not isinstance(c, dict):
            raise CalibrationError("view %r has no calibration (mode 'none' marks a picture without a scale)"
                                   % name)
        mode = c.get('mode')
        if mode not in MODES:
            raise CalibrationError('view %r: unknown calibration mode %r; modes: %s' % (name, mode, ', '.join(MODES)))
        missing = [k for k in MODES[mode] if k not in c]
        if missing:
            raise CalibrationError('view %r: calibration %s lacks %s' % (name, mode, ', '.join(missing)))
        if mode == 'none':
            raise CalibrationError(
                "view %r has no metric scale (calibration mode 'none'): give the model's dimensions in metres "
                'in props() from the text that came with the pictures (a height, a length), or calibrate the '
                "view with 'rows', 'scale_figure' or 'known_span'; its landmarks still give proportions in "
                'pixels' % name)
        if 'size' not in v:
            raise CalibrationError('view %r has no size [width, height]; lpk.intake.crop_views gives it' % name)
        if mode == 'rows':
            cal = Calib(c['height_m'], c['crown_px'], c['feet_px'], tuple(v['size']))
            cal.zero_px, cal.facing = v.get('zero_px'), v.get('facing')
            return cal
        size = tuple(v['size'])
        frame = {'mid_px': v.get('mid_px'), 'zero_px': v.get('zero_px'), 'facing': v.get('facing')}
        if mode == 'rows_of':
            return RowsOfCalib(self.calib(c['of']), c['row_offset_px'], size, **frame)
        if mode == 'crop_of':
            return CropOfCalib(self.calib(c['of']), c['origin_px'], c['zoom'], size, v.get('mid_px'))
        if mode == 'scale_figure':
            return ScaleFigureCalib(c['figure_height_m'], c['figure_top_px'], c['ground_px'], size, **frame)
        return KnownSpanCalib(c['metres'], self.span_px(name), c['ground_px'], size, **frame)

    def span_px(self, name):
        """The pixel length of a known_span view's span: |dx| for axis 'x', |dy| for 'y', the straight
        line without an axis. Its ends a and b are landmark names of the view or [x, y] pixels. Raises
        CalibrationError for a landmark name the view lacks or an unknown axis."""
        c = self.data['views'][name]['calibration']
        pts = []
        for end in (c['a'], c['b']):
            if isinstance(end, str):
                lm = self.landmarks(name)
                if end not in lm:
                    raise CalibrationError('view %r, known_span: no landmark %r in landmarks.%s' % (name, end, name))
                end = lm[end]
            pts.append(end)
        (ax, ay), (bx, by) = pts
        axis = c.get('axis')
        if axis == 'x':
            return abs(bx - ax)
        if axis == 'y':
            return abs(by - ay)
        if axis is None:
            return math.hypot(bx - ax, by - ay)
        raise CalibrationError("view %r, known_span: axis must be 'x', 'y' or absent, got %r" % (name, axis))
