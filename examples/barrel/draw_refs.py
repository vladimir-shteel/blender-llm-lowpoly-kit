"""Draws the barrel's reference view (refs/front.png) as flat-coloured shapes on white, inside Blender with
lpk.stages.imaging (lpk.stages.view writes the PNG): the staves' bulging outline, four iron hoops standing
off it and the bung on the front. 0.9 m is 800 px, the top on row 100 and the base on row 900; the midline
is column 300. A barrel is round, so one view gives every size.

Run inside Blender (lpk on sys.path): exec(open(path).read(), {'MODEL': <the barrel's folder>})."""
import math
import os

import numpy as np

from lpk.stages import imaging, view

K = 800 / 0.9             # pixels per metre
BASE = 900                # the base row
MID = 300                 # the midline column
H = 0.90                  # the barrel's height (m)
HEAD_R, BILGE_R = 0.25, 0.31   # the staves' radius at the ends and at mid-height (m)
HOOP_PROUD = 0.006        # how far the hoops stand off the staves (m)
# Each hoop's lower and upper edge (m above the base).
HOOPS = ((0.03, 0.08), (0.24, 0.29), (0.61, 0.66), (0.82, 0.87))
BUNG_Z, BUNG_R = 0.45, 0.025

WOOD = (0.55, 0.36, 0.20)
IRON = (0.25, 0.25, 0.27)
BUNG = (0.35, 0.22, 0.12)


def radius(z):
    """The staves' radius at height z: a parabola through the ends and the bilge."""
    u = (z - H / 2) / (H / 2)
    return HEAD_R + (BILGE_R - HEAD_R) * (1 - u * u)


def band(z0, z1, extra=0.0, n=24):
    """The outline of the barrel's elevation from z0 to z1, its radius `extra` over the staves'."""
    zs = [z0 + (z1 - z0) * i / n for i in range(n + 1)]
    right = [(radius(z) + extra, z) for z in zs]
    return right + [(-x, z) for x, z in reversed(right)]


def draw_front(path):
    img = np.ones((1000, 600, 4), np.float32)
    px = lambda p: (MID + p[0] * K, BASE - p[1] * K)
    fill = lambda pts, col: imaging.fill_polygon(img, [px(p) for p in pts], col)
    fill(band(0.0, H), WOOD)
    for z0, z1 in HOOPS:
        fill(band(z0, z1, HOOP_PROUD), IRON)
    fill([(BUNG_R * math.cos(2 * math.pi * i / 32), BUNG_Z + BUNG_R * math.sin(2 * math.pi * i / 32))
          for i in range(32)], BUNG)
    return view.save_image(img, path)


out = os.path.join(MODEL, 'refs')
os.makedirs(out, exist_ok=True)
result = {'front': draw_front(os.path.join(out, 'front.png'))}
