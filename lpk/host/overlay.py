"""The build over its reference on the host: a command line over lpk.stages.imaging.overlay, with PNGs
read and written by lpk.host.png. Three panels: the reference, the build's faces flat in their palette
colours, and the build's edges over the reference; the faces come from lpk.stages.review.project in the
reference's pixels.

    python -m lpk.host.overlay <faces.json> <reference.png> <out.png> [x0,y0,x1,y1] [zoom]

Use it whenever a part's accuracy against the drawing is in doubt: landmark numbers can all match while
a shape is off."""
import sys

from lpk.host import png
from lpk.stages import imaging


def overlay(faces, reference, out, box=None, zoom=1.5):
    """Write the overlay of the faces JSON file over the reference image to `out` and return its (width,
    height) in pixels. box: (x0, y0, x1, y1) in reference pixels to cut the panels to, None for the whole
    picture; zoom: the scale of the result (lpk.stages.imaging.scale)."""
    a = imaging.overlay(png.load(reference), faces, box=box, zoom=zoom)
    png.save(a, out)
    return a.shape[1], a.shape[0]


if __name__ == '__main__':
    box = tuple(int(v) for v in sys.argv[4].split(',')) if len(sys.argv) > 4 else None
    print(overlay(sys.argv[1], sys.argv[2], sys.argv[3], box, float(sys.argv[5]) if len(sys.argv) > 5 else 1.5))
