"""PNG input and output of the host commands, through Pillow: the one thing the host commands take from
it. Every image operation is lpk.stages.imaging's or lpk.intake's, on the arrays these return.

Pillow is imported when a picture is read or written, so the commands import without it and fail only
when they touch a file."""
import os

import numpy as np

from lpk.stages import imaging


def _pillow():
    try:
        from PIL import Image
    except ImportError:
        raise ImportError('the host commands read and write PNGs with Pillow: pip install pillow') from None
    return Image


def load(path):
    """An image file (any format Pillow reads) as lpk.stages.imaging's float32 RGBA array (H, W, 4),
    top row first: 8-bit values / 255, exactly, as lpk.stages.view.load_image gives them in Blender; grey,
    palette and RGB pictures get an opaque alpha."""
    with _pillow().open(path) as im:
        a = np.asarray(im.convert('RGBA'), dtype=np.uint8)
    return a.astype(np.float32) / 255.0


def save(arr, path):
    """Write an image array as an 8-bit RGBA PNG and return the absolute path. arr: (H, W, 4) top row
    first (grey, RGB and uint8 arrays are accepted); values are clipped to 0..1 and rounded to the
    nearest of the 256 levels, so what load returned is written back unchanged. The folder is made when
    missing."""
    a = np.floor(np.clip(imaging.rgba(arr), 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _pillow().fromarray(a, 'RGBA').save(path)
    return path
