"""Draws the mannequin's reference views (refs/front.png, refs/side.png, refs/back.png) as flat-coloured
shapes on white, inside Blender with lpk.stages.imaging (lpk.stages.view writes the PNGs). The views share one scale and one ground row:
1.75 m is 800 px, the crown on row 100, the soles on row 900. The front and the back view's midline is
column 350; the back view shows the figure from behind (its left, +x, on the image's left), the hair
covering the head down to the nape and no face; the side view faces left (nose toward the image's left)
with model y = 0 on column 250.

Run inside Blender (lpk on sys.path): exec(open(path).read(), {'MODEL': <the mannequin's folder>})."""
import math
import os

import numpy as np

from lpk.stages import imaging, view

K = 800 / 1.75            # pixels per metre
FEET = 900                # sole row
H = 1.75

SKIN = (0.87, 0.71, 0.60)
SHIRT = (0.27, 0.48, 0.62)
TROUSERS = (0.30, 0.31, 0.36)
SHOE = (0.20, 0.17, 0.15)
SOLE = (0.42, 0.40, 0.38)
HAIR = (0.33, 0.24, 0.17)
EYE = (0.10, 0.10, 0.12)
MOUTH = (0.62, 0.36, 0.33)

ANG = math.radians(38)    # A-pose: arms 38 degrees off vertical
SH = (0.170, 1.430)       # shoulder joint (x, z)
UPPER, FORE, HAND = 0.30, 0.26, 0.19
HEAD_C = (0.0, 1.632)      # the head's centre (x, z)


def canvas(w, h):
    a = np.ones((h, w, 4), np.float32)
    return a


def ellipse(c, rx, rz, n=48):
    return [(c[0] + rx * math.cos(2 * math.pi * i / n), c[1] + rz * math.sin(2 * math.pi * i / n)) for i in range(n)]


def capsule(a, b, ra, rb, n=24):
    """Outline of a tapered capsule from a to b (2D, metres), radius ra at a and rb at b."""
    ax, az = a; bx, bz = b
    dx, dz = bx - ax, bz - az
    L = math.hypot(dx, dz)
    ux, uz = dx / L, dz / L
    nx, nz = -uz, ux
    pts = []
    for i in range(n + 1):                       # cap at b
        t = -math.pi / 2 + math.pi * i / n
        pts.append((bx + rb * (ux * math.cos(t) + nx * math.sin(t)), bz + rb * (uz * math.cos(t) + nz * math.sin(t))))
    for i in range(n + 1):                       # cap at a
        t = math.pi / 2 + math.pi * i / n
        pts.append((ax + ra * (ux * math.cos(t) + nx * math.sin(t)), az + ra * (uz * math.cos(t) + nz * math.sin(t))))
    return pts


def mirror(pts):
    return [(-x, z) for x, z in pts]


def arm_points(sx):
    d = (sx * math.sin(ANG), -math.cos(ANG))
    S = (sx * SH[0], SH[1])
    E = (S[0] + d[0] * UPPER, S[1] + d[1] * UPPER)
    W = (E[0] + d[0] * FORE, E[1] + d[1] * FORE)
    T = (W[0] + d[0] * HAND, W[1] + d[1] * HAND)
    hem = (S[0] + d[0] * 0.14, S[1] + d[1] * 0.14)
    return S, E, W, T, hem, d


def _body(fill):
    """The figure the front and the back view share, as fill(points in model (x, z) metres, colour) draws
    it: the shoes, the trousers, the neck, the t-shirt, the arms, the head's skin and the ears."""
    for sx in (1, -1):
        # shoe: seen from the front or the back, a rounded block
        shoe = [(0.055, 0.0), (0.062, 0.025), (0.058, 0.06), (0.045, 0.095), (-0.045, 0.095), (-0.058, 0.06),
                (-0.062, 0.025), (-0.055, 0.0)]
        fill([(sx * 0.10 + x, z) for x, z in shoe], SHOE)
        fill([(sx * 0.10 + x, z) for x, z in [(0.062, 0.0), (0.064, 0.02), (-0.064, 0.02), (-0.062, 0.0)]], SOLE)
        # straight trouser leg, hip to hem
        leg = [(0.0, 0.84), (0.168, 0.95), (0.170, 0.80), (0.160, 0.50), (0.163, 0.07), (0.037, 0.07),
               (0.030, 0.50), (0.012, 0.80)]
        fill(leg if sx > 0 else mirror(leg), TROUSERS)
    pelvis = [(-0.163, 0.97), (0.163, 0.97), (0.168, 0.86), (0.0, 0.82), (-0.168, 0.86)]
    fill(pelvis, TROUSERS)
    # neck under the head
    fill([(-0.052, 1.44), (0.052, 1.44), (0.048, 1.56), (-0.048, 1.56)], SKIN)
    # fitted t-shirt: torso outline
    half = [(0.058, 1.475), (0.150, 1.452), (0.192, 1.425), (0.190, 1.370), (0.160, 1.305), (0.160, 1.230),
            (0.140, 1.120), (0.136, 1.050), (0.152, 0.960), (0.160, 0.905)]
    torso = half + [(-x, z) for x, z in reversed(half)]
    torso.insert(0, (0.0, 1.462))
    fill(torso, SHIRT)
    for sx in (1, -1):
        S, E, Wr, T, hem, d = arm_points(sx)
        fill(capsule(E, Wr, 0.040, 0.030), SKIN)                  # forearm
        fill(capsule(hem, E, 0.044, 0.040), SKIN)                 # bare upper arm below the sleeve
        fill(capsule(Wr, T, 0.026, 0.020), SKIN)                  # hand, edge-on in the A-pose
        sleeve = capsule(S, hem, 0.060, 0.056)
        fill(sleeve, SHIRT)
    # head: skin, then the ears
    fill(ellipse(HEAD_C, 0.077, 0.112), SKIN)
    for sx in (1, -1):
        fill(ellipse((sx * 0.077, 1.625), 0.012, 0.026), SKIN)


def draw_front(path):
    W_, H_ = 700, 1000
    mid = 350
    img = canvas(W_, H_)
    px = lambda p: (mid + p[0] * K, FEET - p[1] * K)            # the character's left (+x) on the image's right
    fill = lambda pts, col: imaging.fill_polygon(img, [px(p) for p in pts], col)
    _body(fill)
    # the hair cap over the forehead, then the painted face
    cap = [(0.0, 1.750)]
    for i in range(1, 25):
        t = math.pi / 2 - (math.pi / 2 + math.radians(20)) * i / 24
        cap.append((0.083 * math.cos(t), HEAD_C[1] + 0.118 * math.sin(t)))
    cap += [(0.070, 1.640), (0.050, 1.690), (0.0, 1.700), (-0.050, 1.690), (-0.070, 1.640)]
    cap += [(-x, z) for x, z in reversed(cap[1:25])]
    fill(cap, HAIR)
    for sx in (1, -1):
        fill(ellipse((sx * 0.031, 1.636), 0.010, 0.006), EYE)
    fill(ellipse((0.0, 1.567), 0.022, 0.005), MOUTH)
    return view.save_image(img, path)


def draw_back(path):
    W_, H_ = 700, 1000
    mid = 350
    img = canvas(W_, H_)
    px = lambda p: (mid - p[0] * K, FEET - p[1] * K)            # seen from behind: +x on the image's left
    fill = lambda pts, col: imaging.fill_polygon(img, [px(p) for p in pts], col)
    _body(fill)
    # the hair covering the head from the crown down to the nape, 20 degrees under the head's centre
    hair = []
    for i in range(49):
        t = -math.radians(20) + (math.pi + math.radians(40)) * i / 48
        hair.append((0.083 * math.cos(t), HEAD_C[1] + 0.118 * math.sin(t)))
    fill(hair, HAIR)
    return view.save_image(img, path)


def draw_side(path):
    W_, H_ = 500, 1000
    zero = 250
    img = canvas(W_, H_)
    px = lambda p: (zero + p[0] * K, FEET - p[1] * K)      # facing left: model y (forward is -y) runs with px
    fill = lambda pts, col: imaging.fill_polygon(img, [px(p) for p in pts], col)
    # shoe, toe toward -y
    fill([(0.070, 0.0), (0.075, 0.05), (0.060, 0.095), (0.0, 0.10), (-0.08, 0.075), (-0.17, 0.055),
          (-0.205, 0.035), (-0.205, 0.0)], SHOE)
    fill([(0.075, 0.0), (0.075, 0.02), (-0.208, 0.02), (-0.208, 0.0)], SOLE)
    # trousers: seat to hem, straight
    fill([(-0.085, 0.97), (0.080, 0.97), (0.110, 0.90), (0.105, 0.80), (0.070, 0.62), (0.058, 0.50),
          (0.060, 0.07), (-0.062, 0.07), (-0.064, 0.50), (-0.080, 0.75), (-0.092, 0.90)], TROUSERS)
    # neck
    fill([(-0.040, 1.44), (0.060, 1.44), (0.052, 1.56), (-0.035, 1.56)], SKIN)
    # t-shirt torso profile
    fill([(-0.040, 1.475), (0.065, 1.480), (0.100, 1.420), (0.105, 1.300), (0.080, 1.150), (0.075, 1.050),
          (0.095, 0.950), (0.100, 0.905), (-0.092, 0.905), (-0.090, 0.960), (-0.085, 1.050), (-0.095, 1.150),
          (-0.112, 1.280), (-0.100, 1.400)], SHIRT)
    # head profile: skull, face with nose and chin, hair cap
    head = [(0.110, 1.640), (0.100, 1.700), (0.060, 1.738), (0.0, 1.745), (-0.060, 1.730), (-0.088, 1.690),
            (-0.094, 1.650), (-0.096, 1.625), (-0.110, 1.600), (-0.098, 1.590), (-0.096, 1.570),
            (-0.090, 1.545), (-0.072, 1.522), (-0.040, 1.518), (-0.010, 1.540), (0.040, 1.545), (0.080, 1.560),
            (0.105, 1.590)]
    fill(head, SKIN)
    fill(ellipse((0.005, 1.625), 0.016, 0.026), SKIN)
    hair = [(0.118, 1.640), (0.108, 1.705), (0.064, 1.746), (0.0, 1.752), (-0.064, 1.737), (-0.092, 1.700),
            (-0.090, 1.690), (-0.050, 1.700), (0.0, 1.690), (0.030, 1.655), (0.060, 1.640), (0.095, 1.590),
            (0.112, 1.595)]
    fill(hair, HAIR)
    fill(ellipse((-0.090, 1.636), 0.005, 0.006), EYE)
    fill([(-0.100, 1.570), (-0.090, 1.572), (-0.090, 1.564), (-0.098, 1.563)], MOUTH)
    # the left arm (+x, toward the viewer) seen from the side: in the y = 0 plane, over the torso
    S, E, Wr, T, hem, d = arm_points(1)
    z = lambda p: p[1]
    fill(capsule((0.0, z(E)), (0.0, z(Wr)), 0.042, 0.032), SKIN)
    fill(capsule((0.0, z(hem)), (0.0, z(E)), 0.046, 0.042), SKIN)
    hand = [(-0.035, z(Wr)), (0.035, z(Wr)), (0.045, z(Wr) - 0.10), (0.030, z(T)), (-0.025, z(T)),
            (-0.045, z(Wr) - 0.09), (-0.058, z(Wr) - 0.05), (-0.040, z(Wr) - 0.02)]
    fill(hand, SKIN)
    fill(capsule((0.0, z(S)), (0.0, z(hem)), 0.062, 0.058), SHIRT)
    return view.save_image(img, path)


out = os.path.join(MODEL, 'refs')
os.makedirs(out, exist_ok=True)
result = {'front': draw_front(os.path.join(out, 'front.png')), 'side': draw_side(os.path.join(out, 'side.png')),
          'back': draw_back(os.path.join(out, 'back.png'))}
