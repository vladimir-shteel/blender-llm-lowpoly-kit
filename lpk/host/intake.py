"""Reference intake on the host: command lines over lpk.intake and lpk.stages.imaging, with PNGs read
and written by lpk.host.png. The model folder holds views.json; view images go to refs/, grids to
out/grids/.

    python -m lpk.host.intake crop <sheet.png> <model_dir> <scale> name=x0,y0,x1,y1 [name=...] [--alpha]
    python -m lpk.host.intake grid <model_dir> <view> [step] [x0,y0,x1,y1] [--zoom Z] [--no-marks]
    python -m lpk.host.intake key <sheet.png> <model_dir> x,y [x,y ...] [--radius R]
    python -m lpk.host.intake seeds <sheet.png> x,y [x,y ...] [--step S] [--radius R]
    python -m lpk.host.intake sample <model_dir> <view> name=x,y [name=x,y ...] [--radius R]
    python -m lpk.host.intake clean <picture.png> <model_dir> [--min-px N] [--keep x0,y0,x1,y1 ...]
    python -m lpk.host.intake compare <model_dir> <view> <original view>

crop cuts the views and writes their views.json fields (--alpha keeps a keyed sheet's transparency); grid
draws a view's grid, or a box of it, labelled in the view's pixels with its landmarks and ignore regions;
key keys a sheet's ground to transparent from points on it and writes the keyed sheet with its record of
seeds; seeds proposes such points over a lattice from a few samples; sample prints palette colours; clean
removes the small pieces of ink from a picture and writes the cleaned picture with its record; compare
draws a view's ink over the ink of the view it was made from and prints how they differ. Each command
prints its result as JSON."""
import argparse
import json
import os

import numpy as np

from lpk import intake as _kit
from lpk.core import views as views_mod
from lpk.host import png
from lpk.stages import imaging


def _rel(model_dir, path):
    """path relative to model_dir with '/' separators, or absolute when it lies outside it."""
    p = os.path.abspath(path)
    try:
        r = os.path.relpath(p, os.path.abspath(model_dir))
    except ValueError:
        r = p
    if r == os.pardir or r.startswith(os.pardir + os.sep):
        r = p
    return r.replace('\\', '/')


def _views_path(model_dir):
    return os.path.join(model_dir, 'views.json')


def crop(sheet, model_dir, scale, boxes, bg=(1.0, 1.0, 1.0)):
    """Cut the views `boxes` ({view: (x0, y0, x1, y1)} in sheet pixels) out of the sheet image at `scale`
    (lpk.intake.crop_views), write them to model_dir/refs/<view>.png and merge their fields into
    model_dir/views.json. bg: the colour transparent pixels are composited over, None to keep the alpha.
    Returns {view: the image's path}."""
    cut = _kit.crop_views(png.load(sheet), boxes, _rel(model_dir, sheet), scale, bg)
    paths = {name: png.save(a, os.path.join(model_dir, cut['views'][name]['image']))
             for name, a in cut['images'].items()}
    path = _views_path(model_dir)
    _kit.write_views(path, _kit.update_views(_kit.read_views(path), views=cut['views']))
    return paths


def grid(model_dir, view, step=None, box=None, zoom=None, marks=True):
    """Draw the grid of a view of model_dir/views.json, or of a box of it (lpk.intake.grid_view), with the
    view's landmarks (unless marks is False) and ignore regions, to out/grids/<view>.png for the whole
    view and out/grids/<view>_<x0>_<y0>_<x1>_<y1>_z<zoom>_s<step>[_marks].png for a box. step, zoom: None
    for grid_view's defaults (lpk.intake.GRID_STEP and GRID_ZOOM on a whole view, BOX_GRID_STEP and
    BOX_GRID_ZOOM on a box). Returns the grid's path."""
    step = step or (_kit.GRID_STEP if box is None else _kit.BOX_GRID_STEP)
    zoom = zoom or (_kit.GRID_ZOOM if box is None else _kit.BOX_GRID_ZOOM)
    vs = views_mod.Views(_views_path(model_dir))
    if view not in vs.names:
        raise ValueError('no view %r in views.json; views: %s' % (view, ', '.join(vs.names)))
    g = _kit.grid_view(png.load(vs.image(view)), box, step, zoom, vs.landmarks(view) if marks else None,
                       vs.ignore(view))
    if box is None:
        name = view + '.png'
    else:
        name = '%s_%d_%d_%d_%d_z%g_s%g%s.png' % ((view,) + tuple(box) + (zoom, step, '_marks' if marks else ''))
    return png.save(g, os.path.join(model_dir, 'out', 'grids', name))


def key(sheet, model_dir, points, radius=2):
    """Key a sheet's ground to transparent from points on it (lpk.stages.imaging.key, which says how to
    pick them) and write the keyed sheet, model_dir/refs/<sheet name>_keyed.png, with its record beside it,
    the same path with '.json': {'sheet': the sheet's path relative to model_dir, 'radius', 'seeds'}. Cut
    the views from the keyed sheet with crop(..., bg=None); sample reads the record through the views'
    source. Returns {'image', 'record', 'seeds', 'share': the share of the sheet keyed}."""
    keyed, seeds = imaging.key(png.load(sheet), points, radius)
    out = png.save(keyed, os.path.join(model_dir, 'refs', os.path.splitext(os.path.basename(sheet))[0]
                                       + '_keyed.png'))
    record = os.path.splitext(out)[0] + '.json'
    with open(record, 'w', encoding='utf-8', newline='\n') as f:
        json.dump({'sheet': _rel(model_dir, sheet), 'radius': radius, 'seeds': seeds}, f, indent=1)
        f.write('\n')
    return {'image': out, 'record': record, 'seeds': seeds, 'share': round(float((keyed[..., 3] == 0).mean()), 4)}


def seeds(sheet, samples, **options):
    """Points on a sheet's ground for key, proposed over a lattice from a few samples on it
    (lpk.stages.imaging.ground_seeds, which says how and takes the options). Returns its dict."""
    return imaging.ground_seeds(png.load(sheet), samples, **options)


def key_seeds(model_dir, view):
    """The seeds of the ground key view `view` of model_dir/views.json was cut from: the record key wrote
    beside its source sheet, [] when its source is no keyed sheet."""
    src = views_mod.Views(_views_path(model_dir)).view(view).get('source')
    sheet = src.get('sheet') if isinstance(src, dict) else None
    if not isinstance(sheet, str):
        return []
    record = os.path.splitext(os.path.join(model_dir, sheet))[0] + '.json'
    if not os.path.exists(record):
        return []
    with open(record, encoding='utf-8') as f:
        return json.load(f).get('seeds') or []


def sample(model_dir, view, points, radius=2):
    """Palette colours of a view of model_dir/views.json at points {name: [x, y]}
    (lpk.intake.sample_colours), with the view's ignore regions and the seeds of the ground key it was
    cut from. Returns sample_colours' dict."""
    vs = views_mod.Views(_views_path(model_dir))
    if view not in vs.names:
        raise ValueError('no view %r in views.json; views: %s' % (view, ', '.join(vs.names)))
    return _kit.sample_colours(png.load(vs.image(view)), points, radius, vs.ignore(view),
                               key_seeds(model_dir, view))


def _record_beside(picture):
    """The record key or clean wrote beside a picture they made (the picture's path with '.json'), {}
    when there is none."""
    path = os.path.splitext(picture)[0] + '.json'
    if not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def clean(picture, model_dir, min_px=imaging.CLEAN_MIN_PX, keep=()):
    """Remove the small pieces of ink from a picture (lpk.stages.imaging.clean, which says what a piece
    is) and write the cleaned picture, model_dir/refs/<picture name>_clean.png, with its record beside it,
    the same path with '.json': {'picture': the picture's path relative to model_dir, 'min_px', 'keep',
    'dropped', 'seeds': the seeds of the ground key the picture was keyed with, [] for none}. A sheet is
    cleaned before its views are cut from it; sample reads the seeds through the views' source. keep:
    [(x0, y0, x1, y1)] boxes in the picture's pixels, x1 and y1 exclusive, whose pieces stay. Returns
    {'image', 'record', 'kept', 'dropped_px', 'dropped'}."""
    arr = png.load(picture)
    mask = None
    if keep:
        mask = np.zeros(arr.shape[:2], bool)
        for x0, y0, x1, y1 in keep:
            mask[max(0, y0):max(0, y1), max(0, x0):max(0, x1)] = True
    out, rec = imaging.clean(arr, min_px, keep=mask)
    image = png.save(out, os.path.join(model_dir, 'refs', os.path.splitext(os.path.basename(picture))[0]
                                       + '_clean.png'))
    record = os.path.splitext(image)[0] + '.json'
    with open(record, 'w', encoding='utf-8', newline='\n') as f:
        json.dump({'picture': _rel(model_dir, picture), 'min_px': rec['min_px'], 'keep': [list(b) for b in keep],
                   'dropped': rec['dropped'], 'seeds': _record_beside(picture).get('seeds') or []}, f, indent=1)
        f.write('\n')
    return {'image': image, 'record': record, 'kept': rec['kept'], 'dropped_px': rec['dropped_px'],
            'dropped': rec['dropped']}


def compare(model_dir, view, original):
    """Draw the ink of view `view` of model_dir/views.json (a cleaned or generated copy) over the ink of
    view `original` (the picture it was made from, cut with the same box and scale) with lpk.intake.
    compare_copy, reading neither on `view`'s ignore regions, to out/compare/<view>.png. Returns
    {'picture', 'size', 'metrics'}: compare_copy's dict with the picture's path."""
    vs = views_mod.Views(_views_path(model_dir))
    for name in (view, original):
        if name not in vs.names:
            raise ValueError('no view %r in views.json; views: %s' % (name, ', '.join(vs.names)))
    picture, out = _kit.compare_copy(png.load(vs.image(original)), png.load(vs.image(view)),
                                     regions=vs.ignore(view))
    return dict(out, picture=png.save(picture, os.path.join(model_dir, 'out', 'compare', view + '.png')))


def _ints(text):
    return [int(v) for v in text.split(',')]


def _named(items):
    return {k: _ints(v) for k, _, v in (s.partition('=') for s in items)}


def main(argv=None):
    p = argparse.ArgumentParser(prog='python -m lpk.host.intake', description=__doc__.split('\n\n')[0])
    sub = p.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('crop')
    c.add_argument('sheet')
    c.add_argument('model_dir')
    c.add_argument('scale', type=float)
    c.add_argument('boxes', nargs='+')
    c.add_argument('--alpha', action='store_true')
    g = sub.add_parser('grid')
    g.add_argument('model_dir')
    g.add_argument('view')
    g.add_argument('step', nargs='?', type=float)
    g.add_argument('box', nargs='?')
    g.add_argument('--zoom', type=float)
    g.add_argument('--no-marks', action='store_true')
    k = sub.add_parser('key')
    k.add_argument('sheet')
    k.add_argument('model_dir')
    k.add_argument('points', nargs='+')
    k.add_argument('--radius', type=int, default=2)
    s = sub.add_parser('seeds')
    s.add_argument('sheet')
    s.add_argument('samples', nargs='+')
    s.add_argument('--step', type=int, default=imaging.GROUND_STEP)
    s.add_argument('--radius', type=int, default=2)
    m = sub.add_parser('sample')
    m.add_argument('model_dir')
    m.add_argument('view')
    m.add_argument('points', nargs='+')
    m.add_argument('--radius', type=int, default=2)
    n = sub.add_parser('clean')
    n.add_argument('picture')
    n.add_argument('model_dir')
    n.add_argument('--min-px', type=int, default=imaging.CLEAN_MIN_PX)
    n.add_argument('--keep', nargs='+', default=[])
    o = sub.add_parser('compare')
    o.add_argument('model_dir')
    o.add_argument('view')
    o.add_argument('original')
    a = p.parse_args(argv)
    if a.cmd == 'crop':
        scale = int(a.scale) if a.scale.is_integer() else a.scale
        out = crop(a.sheet, a.model_dir, scale, _named(a.boxes), None if a.alpha else (1.0, 1.0, 1.0))
    elif a.cmd == 'grid':
        step = None if a.step is None else int(a.step) if a.step.is_integer() else a.step
        zoom = None if a.zoom is None else int(a.zoom) if a.zoom.is_integer() else a.zoom
        out = grid(a.model_dir, a.view, step, a.box and _ints(a.box), zoom, not a.no_marks)
    elif a.cmd == 'key':
        out = key(a.sheet, a.model_dir, [_ints(v) for v in a.points], a.radius)
    elif a.cmd == 'seeds':
        out = seeds(a.sheet, [_ints(v) for v in a.samples], step=a.step, radius=a.radius)
    elif a.cmd == 'sample':
        out = sample(a.model_dir, a.view, _named(a.points), a.radius)
    elif a.cmd == 'clean':
        out = clean(a.picture, a.model_dir, a.min_px, [_ints(v) for v in a.keep])
    else:
        out = compare(a.model_dir, a.view, a.original)
    print(json.dumps(out, indent=1, default=lambda v: v.tolist() if hasattr(v, 'tolist') else str(v)))
    return out


if __name__ == '__main__':
    main()
