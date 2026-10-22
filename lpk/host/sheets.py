"""Contact sheets of review captures on the host: a command line over lpk.stages.imaging.sheet, with PNGs
read and written by lpk.host.png.

    python -m lpk.host.sheets <out.png> <cols> <width> <crop> <label,label,...> <image.png[@crop]> [...]

Each image is centre-cropped to `crop` of its width (image.png@0.4 overrides it for that image), scaled
to `width` pixels wide (a negative width scales it to that many pixels high instead) with
lpk.stages.imaging.scale, and laid out in `cols` columns; the labels name the images of the first row,
an empty one none."""
import sys

from lpk.host import png
from lpk.stages import imaging


def sheet(out, cols, width, crop, labels, files):
    """Write the contact sheet of the image files to `out` and return its (width, height) in pixels.
    cols: columns; width: the width in pixels every image is scaled to, or minus the height; crop: the
    share of an image's width kept round its centre, 0..1, overridden per file by 'path@share';
    labels: the labels of the first row's images, '' for none."""
    ims = []
    for f in files:
        f, _, k = f.partition('@')
        a = png.load(f)
        h, w = a.shape[:2]
        cw = int(w * (float(k) if k else crop))
        x0 = (w - cw) // 2
        a = imaging.crop(a, (x0, 0, x0 + cw, h))
        ims.append(imaging.scale(a, width / cw if width > 0 else -width / h))
    names = [lab or None for lab in labels[:len(ims)]]
    s = imaging.sheet(ims, cols, names + [None] * (len(ims) - len(names)) if any(names) else None)
    png.save(s, out)
    return s.shape[1], s.shape[0]


if __name__ == '__main__':
    print(sheet(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), float(sys.argv[4]), sys.argv[5].split(','),
                sys.argv[6:]))
