"""Draws the worked example's head (skills/lowpoly/references/forms/snout-keys.md): a generic muzzled
animal head, a side view and a front view of the head alone, flat colours with dark ink on white, and
writes the views.json a model would hold for them: both views calibrated on the rows of the figure the
head belongs to (1.2 m tall, the crown on row 60, the soles on row 1260, below the pictures, so one
pixel is one millimetre), the side view facing left with model y = 0 on column 300, landmarks, and the
traces of the head's outline in each view and of the muzzle's outline in the front view, as an agent
would trace them.

Every shape is a polygon in the pictures' pixels, written here once: the pictures are drawn from it and
the traces are the head's and the muzzle's polygons themselves, so the example's numbers come from
nothing but this drawing.

python skills/lowpoly/references/forms/snout-keys/draw.py
(system Python with Pillow; writes front.png, side.png and views.json beside this file)"""
import hashlib
import json
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
INK = (38, 31, 26)
FUR = (158, 115, 77)
MUZZLE = (219, 199, 168)
NOSE = (30, 25, 25)
EAR = (120, 84, 56)
EYE = (25, 20, 20)
INK_W = 2

# The side view, nose toward the image's left: the head's outline from the crown, clockwise.
SIDE_HEAD = [(250, 60), (280, 70), (302, 92), (314, 125), (312, 160), (295, 185), (240, 192), (170, 185),
             (120, 176), (102, 168), (96, 156), (92, 145), (89, 132), (90, 120), (100, 114), (140, 106),
             (172, 98), (190, 84), (215, 68)]
SIDE_MUZZLE = [(172, 98), (140, 106), (100, 114), (90, 120), (89, 132), (92, 145), (96, 156), (102, 168),
               (120, 176), (170, 185), (176, 160), (178, 128)]
SIDE_NOSE = [(100, 114), (90, 120), (89, 132), (100, 134), (110, 124)]
SIDE_EAR = [(232, 72), (262, 18), (288, 78)]
SIDE_NECK = [(240, 192), (295, 185), (310, 240), (230, 240)]
SIDE_EYE = (186, 108, 9, 6)                     # centre column, row, half width, half height
SIDE_MOUTH = [(96, 156), (125, 160), (150, 158)]

# The front view, midline on column 160: right halves from the top, mirrored about the midline.
FRONT_HEAD_R = [(160, 60), (190, 64), (215, 76), (232, 96), (240, 120), (238, 140), (228, 158), (210, 174),
                (185, 186), (160, 191)]
FRONT_MUZZLE_R = [(160, 104), (180, 108), (193, 122), (196, 140), (192, 158), (180, 172), (160, 178)]
FRONT_NOSE_R = [(160, 106), (176, 110), (180, 120), (170, 128), (160, 130)]
FRONT_EAR_R = [(208, 70), (252, 14), (236, 100)]
FRONT_NECK = [(122, 186), (198, 186), (210, 240), (110, 240)]
FRONT_EYE = (203, 108, 7, 7)
MID = 160


def mirrored(right):
    """A closed outline from its right half (top to bottom on the midline): the right half, then its mirror
    image back up, without repeating the points on the midline."""
    left = [(2 * MID - x, y) for x, y in reversed(right) if x != MID]
    return list(right) + left


def ellipse_box(cx, cy, rx, ry):
    return (cx - rx, cy - ry, cx + rx, cy + ry)


def draw(size, layers, out):
    """layers: (polygon or ('ellipse', box) or ('line', points), fill colour or None) back to front."""
    im = Image.new('RGB', size, (255, 255, 255))
    d = ImageDraw.Draw(im)
    for shape, fill in layers:
        if shape[0] == 'ellipse':
            d.ellipse(shape[1], fill=fill, outline=INK, width=INK_W)
        elif shape[0] == 'line':
            d.line(shape[1], fill=INK, width=INK_W)
        else:
            d.polygon(shape, fill=fill, outline=INK, width=INK_W)
    im.save(out, optimize=False)
    with open(out, 'rb') as f:
        return list(size), hashlib.sha256(f.read()).hexdigest()


def main():
    front_head = mirrored(FRONT_HEAD_R)
    front_muzzle = mirrored(FRONT_MUZZLE_R)
    front_nose = mirrored(FRONT_NOSE_R)
    ex, ey, erx, ery = FRONT_EYE
    side_size, side_sha = draw((360, 240), [
        (SIDE_NECK, FUR), (SIDE_EAR, EAR), (SIDE_HEAD, FUR), (SIDE_MUZZLE, MUZZLE), (SIDE_NOSE, NOSE),
        (('ellipse', ellipse_box(*SIDE_EYE)), EYE), (('line', SIDE_MOUTH), None)], os.path.join(HERE, 'side.png'))
    front_size, front_sha = draw((320, 240), [
        (FRONT_NECK, FUR), (FRONT_EAR_R, EAR), ([(2 * MID - x, y) for x, y in FRONT_EAR_R], EAR), (front_head, FUR),
        (front_muzzle, MUZZLE), (front_nose, NOSE), (('ellipse', ellipse_box(ex, ey, erx, ery)), EYE),
        (('ellipse', ellipse_box(2 * MID - ex, ey, erx, ery)), EYE)], os.path.join(HERE, 'front.png'))
    views = {
        'views': {
            'front': {'image': 'front.png', 'facing': 'front', 'role': 'main', 'size': front_size,
                      'sha256': front_sha, 'mid_px': MID,
                      'calibration': {'mode': 'rows', 'height_m': 1.2, 'crown_px': 60, 'feet_px': 1260},
                      'note': 'the head of a figure 1.2 m tall, drawn by draw.py beside this file'},
            'side': {'image': 'side.png', 'facing': 'left', 'role': 'measure', 'size': side_size,
                     'sha256': side_sha, 'zero_px': 300,
                     'calibration': {'mode': 'rows_of', 'of': 'front', 'row_offset_px': 0},
                     'note': 'the same head in profile, on the front view rows'},
        },
        'landmarks': {
            'front': {'crown': [MID, 60], 'eye.L': [ex, ey], 'eye.R': [2 * MID - ex, ey]},
            'side': {'crown': [250, 60], 'skull_back': [314, 125], 'brow': [190, 84], 'eye': [SIDE_EYE[0], SIDE_EYE[1]],
                     'bridge': [140, 106], 'nose': [89, 132], 'lip': [96, 156], 'chin': [102, 168],
                     'throat': [240, 192]},
        },
        'traces': {
            'head_side': {'view': 'side', 'px': [list(p) for p in SIDE_HEAD]},
            'head_front': {'view': 'front', 'px': [list(p) for p in front_head]},
            'muzzle_front': {'view': 'front', 'px': [list(p) for p in front_muzzle]},
        },
    }
    with open(os.path.join(HERE, 'views.json'), 'w', encoding='utf-8', newline='\n') as f:
        json.dump(views, f, indent=1)
        f.write('\n')


if __name__ == '__main__':
    main()
