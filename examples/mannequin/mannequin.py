"""The kit's worked example: a gender-neutral adult mannequin, 1.75 m tall, in an A-pose, in a fitted
short-sleeve t-shirt, straight trousers and simple shoes, with bare forearms, mitten hands, a plain human
head, a short hair cap and a painted face. It is measured from the front and side views drawn for it
(refs/, drawn by draw_refs.py) through views.json; the back view is not read by the measurements and is
there to compare the build with.

Brief: about 1500-2500 triangles in one 512 atlas; the biped skeleton with mitten fingers and no tail;
binary glTF for the engine and FBX from the same body; about 200 px tall on screen at the farthest play
distance.

Run it from an MCP call after the kit's bootstrap (lpk/__init__.py):

    from lpk import run
    run.model(r'<kit>/examples/mannequin/mannequin.py', stages=('reference', 'blocks'))
    run.model(r'<kit>/examples/mannequin/mannequin.py', stages=('build', 'unwrap', 'pack', 'pack', 'pack'))
    run.model(r'<kit>/examples/mannequin/mannequin.py', stages=('bake', 'rig', 'preview', 'export'))

Every value below is this model's choice, measured or reasoned from its references and brief; a new
model derives its own."""
import math
import os

from mathutils import Vector

from lpk.core import edits
from lpk.core.builder import Builder
from lpk.core.sections import ProfileKey, Section, loft_rings, profile_rings, section_radii
from lpk.core.shapes import bvh_of, cast_point, fan_decal, lobe, ridge_flip
from lpk.core.views import Views
from lpk.forms import hair as hair_form, hands, head as head_form, joins, torso

NAME = 'Mannequin'
VIEWS = 'views.json'
EDITS = 'edits.json'
# The medians of 5 x 5 pixel patches of flat areas of refs/front.png (lpk.intake.sample_colours).
PALETTE = {
    'skin': (0.87, 0.71, 0.60),
    'shirt': (0.27, 0.48, 0.62),
    'trousers': (0.30, 0.31, 0.36),
    'shoe': (0.20, 0.17, 0.15),
    'sole': (0.42, 0.40, 0.38),
    'hair': (0.33, 0.24, 0.17),
    'eye': (0.10, 0.10, 0.12),
    'mouth': (0.62, 0.36, 0.33),
}

# -- measurements: the values the drawings do not give, each with its reason ---------------------------

# The head and the mitten hands are built 10% larger than drawn, about the head's centre and along the
# hand: at the drawn sizes both read small in the captures.
HEAD_STYLE = 1.1
HAND_STYLE = 1.1
# The drawn sleeve ends round: its hem sits this far above the sleeve's lowest drawn point (m).
SLEEVE_ROUND = 0.028
# The ear's half sizes (m): how far it stands out of the skull, its depth and its height, as drawn; its
# centre lies EAR_BACK behind the head's centre (m), as the side view draws it.
EAR_HALF = (0.009, 0.008, 0.023)
EAR_BACK = 0.012
# The shoe's opening above the floor (m), under the trouser hem, which hides it in the drawings.
SHOE_TOP = 0.10
# The superellipse exponent of the trunk's lowest section (the crotch, a rounded box that holds the two
# thighs side by side) and of the shoe's sections (a rounded box).
CROTCH_EXPONENT = 3.2
SHOE_EXPONENT = 3.0
SIDES = (('L', 1.0), ('R', -1.0))
# The trunk's sections where the drawings give no landmark, each this body's choice read off its captures.
# TRUNK_RISE: each section's height (m) above the landmark it is placed from (the crotch, the waist and
# armpit midway, the armpits, the shoulders, the collar base).
TRUNK_RISE = {'crotch': 0.055, 'ribs': 0.02, 'armhole': 0.083, 'shoulders': 0.040, 'collar': 0.012, 'neck': 0.046,
              'neck_top': 0.10}
# TRUNK_Y: the sections' centre depths (m) the side view does not draw: the seat's centre (the crotch
# section), the belly's start, blended halfway to the waist's, and each upper section's shift off the chest's
# or the neck's centre (+y is back).
TRUNK_Y = {'seat': 0.008, 'belly': 0.006, 'ribs': -0.004, 'armhole': 0.003, 'shoulders': 0.008, 'neck_top': 0.004}
# SEAT_HALF_DEPTH: the trousers' half depths (m) at the crotch section and the belly's start,
# blended halfway to the waist's: the shirt hides the seat in the side view.
SEAT_HALF_DEPTH = {'crotch': 0.098, 'belly': 0.099}
# RIBS_SWELL: the rib cage's half sizes over the mean of the waist's and the chest's (m), a fuller chest.
RIBS_SWELL = 0.006
# The collar's half sizes over the neck's (across, front to back): the shirt's collar stands off the neck;
# the neck's top ring over the neck's half sizes, a taper into the head.
COLLAR_FLARE = (1.33, 1.15)
NECK_TOP = 0.92
# The arm's stations where the drawing gives no landmark, this shirt's and this body's choices (m):
# SLEEVE_HALF, the loose sleeve's half sizes at its socket, under the armpit and at its last ring;
# SLEEVE_UNDERARM, the ring under the armpit this far down the arm; HEM_THICK, a garment hem's thickness,
# the sleeve's and the trousers' last ring above their hem; ELBOW_SPAN and KNEE_SPAN, the rings above and
# below the joint this far from it; WRIST_SPAN, the ring above the wrist this far up the arm and the arm's
# open end this far past the wrist, inside the mitten.
SLEEVE_HALF = {'shoulder': (0.056, 0.054), 'sleeve': (0.055, 0.054), 'cuff': (0.054, 0.053)}
SLEEVE_UNDERARM = 0.07
HEM_THICK = 0.004
ELBOW_SPAN = 0.045
KNEE_SPAN = 0.045
WRIST_SPAN = (0.03, 0.02)
# The leg's stations, this body's choices (m): THIGH_STATION, the thigh ring this far down from the hip
# joint; ANKLE_HALF, the half size of the trousers' hem underside and of the leg's open end at the ankle;
# ANKLE_DROP, the open end this far below the hem, inside the shoe.
THIGH_STATION = 0.12
ANKLE_HALF = (0.040, 0.034)
ANKLE_DROP = 0.03
# The shoe's profile keys, this shoe's choice: SHOE_HEEL_S, the heel key this far ahead of the drawn heel
# (m); SHOE_SHARE, the counter's, the instep's and the toe key's places as shares of the shoe's length (the
# ball's is measured); SHOE_HEIGHT, the keys' heights (m; the counter's is SHOE_TOP); SHOE_WIDTH, their half
# widths over the foot's measured half width.
SHOE_HEEL_S = 0.004
SHOE_SHARE = {'counter': 0.16, 'instep': 0.42, 'toe': 0.90}
SHOE_HEIGHT = {'heel': 0.084, 'instep': 0.080, 'ball': 0.060, 'toe': 0.050}
SHOE_WIDTH = {'heel': 0.62, 'counter': 0.80, 'instep': 0.92, 'ball': 1.0, 'toe': 0.84}


def props():
    """P from the front and the side view of views.json: every length and position the build reads, in
    metres (the head's values scaled by HEAD_STYLE about its centre, the hand's by HAND_STYLE), the arms'
    A-pose angle off vertical in radians ('arm_rad'), the depths (y, forward is -y) from the side view."""
    views = Views(os.path.join(os.path.dirname(__file__), VIEWS))
    front, side = views.calib('front'), views.calib('side')
    marks, profile = views.landmarks('front'), views.landmarks('side')
    width, side_width = views.widths('front'), views.widths('side')
    mid = views.view('front')['mid_px']

    def z(key):
        return front.z(marks[key][1])

    def x(key):
        return front.m(marks[key][0] - mid)

    def w(key):
        return front.m(width[key])

    def span(a, b):
        return front.m(abs(marks[a][0] - marks[b][0])) / 2

    def dist(a, b):
        return front.m(math.dist(marks[a], marks[b]))

    def y(key):
        return side.side(*profile[key])[0]

    def pair(f, a):
        return (f(a + '.L') + f(a + '.R')) / 2

    P = {}
    # The head: the skull under the hair, then the style factor about its centre.
    hair_t = (w('hair') - w('skull')) / 2
    skull_top, skull_back, brow = z('crown') - hair_t, y('skull_back') - 2 * hair_t, y('brow')
    cz = (skull_top + z('chin')) / 2
    styled = lambda h: cz + (h - cz) * HEAD_STYLE
    P['head_c'] = (0.0, (brow + skull_back) / 2, cz)
    P['head_half'] = (w('skull') / 2 * HEAD_STYLE, (skull_back - brow) / 2 * HEAD_STYLE,
                      (skull_top - z('chin')) / 2 * HEAD_STYLE)
    P['hair_t'] = hair_t
    P['hairline_front'] = styled(z('hairline'))
    P['hairline_back'] = side.side(*profile['hair_nape'])[1]
    P['eye_x'], P['eye_z'], P['eye_w'] = abs(x('eye.L') - x('eye.R')) / 2 * HEAD_STYLE, styled(z('eye.L')), w('eye') / 2
    P['mouth_z'], P['mouth_w'] = styled(z('mouth')), w('mouth') / 2
    P['chin_z'] = styled(z('chin'))
    P['ear_x'], P['ear_z'] = x('ear.L'), z('ear.L')
    # The neck and the trunk.
    P['neck_r'], P['neck_y'] = w('neck') / 2, (y('neck_front') + y('neck_back')) / 2
    P['neck_ry'] = (y('neck_back') - y('neck_front')) / 2
    P['collar_z'] = z('collar_base')
    P['sh_x'], P['sh_z'] = span('shoulder.R', 'shoulder.L'), pair(z, 'shoulder')
    P['armpit_z'] = pair(z, 'armpit')
    P['chest_x'], P['chest_y'], P['back_y'] = span('chest.R', 'chest.L'), y('chest_front'), y('back')
    P['waist_x'], P['waist_z'] = span('waist.R', 'waist.L'), z('waist.L')
    P['waist_y'] = (y('waist_front'), y('waist_back'))
    P['hips_x'], P['shirt_hem_z'], P['crotch_z'] = span('hips.R', 'hips.L'), z('shirt_hem'), z('crotch')
    # The arms: the A-pose angle measured on the drawing places them.
    P['upper_arm'] = (dist('shoulder.L', 'elbow.L') + dist('shoulder.R', 'elbow.R')) / 2
    P['forearm'] = (dist('elbow.L', 'wrist.L') + dist('elbow.R', 'wrist.R')) / 2
    P['arm_rad'] = sum(math.atan2(abs(marks['wrist.' + s][0] - marks['shoulder.' + s][0]),
                                  marks['wrist.' + s][1] - marks['shoulder.' + s][1]) for s in 'LR') / 2
    P['sleeve'] = (dist('shoulder.L', 'sleeve.L') + dist('shoulder.R', 'sleeve.R')) / 2 - SLEEVE_ROUND
    P['upper_arm_r'], P['forearm_r'], P['wrist_r'] = w('upper_arm') / 2, w('forearm') / 2, w('wrist') / 2
    P['hand_len'] = (dist('wrist.L', 'fingers.L') + dist('wrist.R', 'fingers.R')) / 2 * HAND_STYLE
    P['hand_half_w'] = side.m(side_width['hand']) / 2 * HAND_STYLE
    P['hand_thick'] = w('hand') / 2 * HAND_STYLE
    # The legs and the feet.
    P['hip_x'], P['hip_z'] = span('hip.R', 'hip.L'), z('hip.L')
    P['knee_x'], P['knee_z'] = span('knee.R', 'knee.L'), z('knee.L')
    P['knee_y'] = (y('knee_front') + y('knee_back')) / 2
    P['ankle_x'], P['ankle_z'] = span('ankle.R', 'ankle.L'), z('ankle.L')
    P['thigh_r'] = (w('thigh') / 2, (y('thigh_back') - y('thigh_front')) / 2)
    P['knee_r'] = (w('knee') / 2, (y('knee_back') - y('knee_front')) / 2)
    P['shin_r'], P['trouser_hem_z'] = w('shin') / 2, z('trouser_hem')
    P['heel_y'], P['ball_y'], P['toe_y'] = y('heel'), y('ball'), y('toe')
    P['foot_w'] = w('foot') / 2
    return P


# -- the figure's sections, shared by the blocks, the build, the seams and the rig ----------------------

def unit(v):
    """v scaled to length 1, as a tuple."""
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v)


def arm_axes(shoulder, wrist):
    """(d, out) of an arm from its shoulder to its wrist point: d, the unit direction down the arm; out,
    the unit direction away from the body, perpendicular to d in the arm's vertical plane (the back of
    the mitten faces it). The arm's side is the sign of the shoulder's x (+x is the left)."""
    d = unit(tuple(w - s for s, w in zip(shoulder, wrist)))
    side = 1.0 if shoulder[0] > 0 else -1.0
    return d, (-d[2] * side, 0.0, d[0] * side)


def _along(path, s):
    """The point at arc length s (m) along the polyline `path`, extrapolated along its end segments
    before its start and past its end."""
    for k, (a, b) in enumerate(zip(path, path[1:])):
        length = math.dist(a, b)
        if s <= length or k == len(path) - 2:
            return tuple(p + (q - p) * s / length for p, q in zip(a, b))
        s -= length


def _cut(h):
    """The half size of an ellipsoid's cross-section at the height fraction h of its half height."""
    return math.sqrt(1.0 - h * h)


def ear_centre(P, sx=1.0):
    """The ear's centre on the side sx (1 left, -1 right), m."""
    return (sx * (P['ear_x'] - EAR_HALF[0]), P['head_c'][1] + EAR_BACK, P['ear_z'])


def hair_sections(P):
    """The hair cap's volume as loft sections over the skull: its brim along the hairline from the forehead
    down to the nape, the dome and the crown."""
    cx, cy, cz = P['head_c']
    W, D, H = P['head_half']
    t = P['hair_t']
    Wh, Dh, Hh = W + t, D + t, H + t
    front, back = P['hairline_front'], P['hairline_back']
    rise = front - back
    return (Section('brim', (0.0, cy, (front + back) / 2), (Wh, math.hypot(Dh, rise / 2)), normal=(0.0, rise, 2 * Dh)),
            Section('dome', (0.0, cy, cz + 0.65 * Hh), (_cut(0.65) * Wh, _cut(0.65) * Dh)),
            Section('crown', (0.0, cy, cz + 0.92 * Hh), (_cut(0.92) * Wh, _cut(0.92) * Dh)))


def trunk_sections(P):
    """The trunk as one surface from the crotch to the top of the neck, which ends open inside the head;
    the arms weld out of it between the chest and the armhole sections, the legs out of its crotch end."""
    hips, waist, chest = P['hips_x'], P['waist_x'], P['chest_x']
    wy, wr = sum(P['waist_y']) / 2, (P['waist_y'][1] - P['waist_y'][0]) / 2
    cy, cr = (P['chest_y'] + P['back_y']) / 2, (P['back_y'] - P['chest_y']) / 2
    ny, nr, nry = P['neck_y'], P['neck_r'], P['neck_ry']
    hem, waist_z, armpit_z, collar_z = P['shirt_hem_z'], P['waist_z'], P['armpit_z'], P['collar_z']
    rise, ty, seat = TRUNK_RISE, TRUNK_Y, SEAT_HALF_DEPTH
    return (
        # Above the drawn crotch: on this model a seam at the measured crotch reads too low; another body
        # places its seam from its own captures.
        Section('crotch', (0.0, ty['seat'], P['crotch_z'] + rise['crotch']), (hips * 0.99, seat['crotch']),
                exponent=CROTCH_EXPONENT),
        Section('belly', (0.0, (ty['belly'] + wy) / 2, (hem + waist_z) / 2),
                ((hips + waist) / 2, (seat['belly'] + wr) / 2)),
        Section('waist', (0.0, wy, waist_z), (waist, wr)),
        Section('ribs', (0.0, (wy + cy) / 2 + ty['ribs'], (waist_z + armpit_z) / 2 + rise['ribs']),
                ((waist + chest) / 2 + RIBS_SWELL, (wr + cr) / 2 + RIBS_SWELL)),
        Section('chest', (0.0, cy, armpit_z), (chest, cr)),                         # the armpits
        Section('armhole', (0.0, cy + ty['armhole'], armpit_z + rise['armhole']), (chest * 1.03, cr * 0.9)),
        Section('shoulders', (0.0, cy + ty['shoulders'], P['sh_z'] + rise['shoulders']), (chest * 0.86, cr * 0.7)),
        Section('collar', (0.0, ny, collar_z + rise['collar']), (nr * COLLAR_FLARE[0], nry * COLLAR_FLARE[1])),
        Section('neck', (0.0, ny, collar_z + rise['neck']), (nr, nry)),
        Section('neck_top', (0.0, ny + ty['neck_top'], collar_z + rise['neck_top']), (nr * NECK_TOP, nry * NECK_TOP)),
    )


def arm_sections(P, sx=1.0):
    """The arm of the side sx (1 left, -1 right) along its straight A-pose path from the shoulder joint:
    [(name, distance down the arm, centre, half extents across it and along the back of the hand)], m."""
    ua, fa, sleeve = P['upper_arm'], P['forearm'], P['sleeve']
    r0, r1, r2 = P['upper_arm_r'], P['forearm_r'], P['wrist_r']
    a = P['arm_rad']
    shoulder = (sx * P['sh_x'], 0.0, P['sh_z'])
    down = (sx * math.sin(a), 0.0, -math.cos(a))
    stations = (('shoulder', 0.0, SLEEVE_HALF['shoulder']),          # the sleeve's socket, which the weld tilts in
                ('sleeve', SLEEVE_UNDERARM, SLEEVE_HALF['sleeve']),
                ('cuff', sleeve - HEM_THICK, SLEEVE_HALF['cuff']),
                ('hem', sleeve, (r0 * 1.04, r0)),              # the hem steps onto the bare arm
                ('biceps', ua - ELBOW_SPAN, (r0, r0 * 0.95)),
                ('elbow', ua, (r1 * 1.08, r1)),
                ('below_elbow', ua + ELBOW_SPAN, (r1 * 1.05, r1 * 0.98)),
                ('forearm', ua + fa * 0.55, (r1 * 0.95, r1 * 0.82)),
                ('above_wrist', ua + fa - WRIST_SPAN[0], (r2 * 1.05, r2 * 0.80)),
                ('wrist', ua + fa, (r2, r2 * 0.68)),           # flat, to fit inside the mitten's opening
                ('end', ua + fa + WRIST_SPAN[1], (r2 * 0.75, r2 * 0.5)))
    return [(name, d, tuple(p + q * d for p, q in zip(shoulder, down)), half) for name, d, half in stations]


def arm_point(P, name, sx=1.0):
    """The centre of the arm section `name` on the side sx, m."""
    return next(c for n, _, c, _ in arm_sections(P, sx) if n == name)


def leg_sections(P, sx=1.0):
    """The leg of the side sx through its hip, knee and ankle joints down to its open end inside the shoe:
    [(name, centre, half extents across and front to back)], m."""
    hip = (sx * P['hip_x'], 0.0, P['hip_z'])
    knee = (sx * P['knee_x'], P['knee_y'], P['knee_z'])
    ankle = (sx * P['ankle_x'], 0.0, P['ankle_z'])
    knee_s = math.dist(hip, knee)
    # The trouser hem lies on the shin's line, below the ankle joint.
    hem_s = knee_s + math.dist(knee, ankle) * (P['knee_z'] - P['trouser_hem_z']) / (P['knee_z'] - P['ankle_z'])
    thigh, kn, shin = P['thigh_r'], P['knee_r'], P['shin_r']
    mean = lambda u, v: tuple((p + q) / 2 for p, q in zip(u, v))
    stations = (('hip', 0.0, thigh),                       # the weld lays this ring on the leg hole
                ('thigh', THIGH_STATION, thigh),
                ('above_knee', knee_s - KNEE_SPAN, mean(thigh, kn)),
                ('knee', knee_s, kn),
                ('below_knee', knee_s + KNEE_SPAN, mean(kn, (shin, shin))),
                ('shin', hem_s - HEM_THICK, (shin, shin)),     # the trouser hem
                ('hem', hem_s, (ANKLE_HALF[0],) * 2),          # the hem's underside, onto the ankle
                ('cuff', hem_s + ANKLE_DROP, (ANKLE_HALF[1],) * 2))  # the ankle, open inside the shoe
    return [(name, _along((hip, knee, ankle), d), half) for name, d, half in stations]


def hand_box(P, sx=1.0):
    """The mitten's box from the wrist along the arm: (wrist, d, out, (half thickness along the back of the
    hand, half width across it, half length)), m."""
    wrist = arm_point(P, 'wrist', sx)
    d, out = arm_axes(arm_point(P, 'shoulder', sx), wrist)
    return wrist, d, out, (P['hand_thick'], P['hand_half_w'], P['hand_len'] / 2)


def shoe_keys(P):
    """The left shoe as a profile from the heel to the toe: (origin, axis, up, keys), m."""
    heel, w = P['heel_y'], P['foot_w']
    length = heel - P['toe_y']
    places = {'heel': SHOE_HEEL_S, 'ball': heel - P['ball_y']}
    places.update({k: length * share for k, share in SHOE_SHARE.items()})
    heights = dict(SHOE_HEIGHT, counter=SHOE_TOP)
    keys = tuple(ProfileKey(k, places[k], heights[k], 0.0, w * SHOE_WIDTH[k], exponent=SHOE_EXPONENT)
                 for k in ('heel', 'counter', 'instep', 'ball', 'toe'))
    return (P['ankle_x'], heel, 0.0), (0.0, -1.0, 0.0), (0.0, 0.0, 1.0), keys


def shoe_point(P, key, sx=1.0):
    """The centre of the shoe key `key` on the side sx, m."""
    (ox, oy, oz), (ax, ay, az), (ux, uy, uz), keys = shoe_keys(P)
    k = next(k for k in keys if k.name == key)
    h = (k.top + k.bottom) / 2
    return (sx * (ox + ax * k.s + ux * h), oy + ay * k.s + uy * h, oz + az * k.s + uz * h)


# -- blocks ----------------------------------------------------------------------------------------------

def blocks(P):
    """Every part as the primitive its shape reads as: the head and the ears ellipsoids, the hair, the trunk,
    the arms and the legs lofts through their sections, the mittens boxes and the shoes profiles."""
    out = [('ellipsoid', 'head', 'skin', (P['head_c'], P['head_half'])),
           ('loft', 'hair', 'hair', (hair_sections(P), (1.0, 0.0, 0.0))),
           ('loft', 'trunk', 'shirt', (trunk_sections(P), (1.0, 0.0, 0.0)))]
    for side, sx in SIDES:
        wrist, d, out_dir, half = hand_box(P, sx)
        origin, axis, up, keys = shoe_keys(P)
        out += [('ellipsoid', 'ear.' + side, 'skin', (ear_centre(P, sx), EAR_HALF)),
                ('loft', 'arm.' + side, 'skin', ([Section(n, c, h) for n, _, c, h in arm_sections(P, sx)],
                                                 (0.0, 1.0, 0.0))),
                ('box', 'hand.' + side, 'skin', (tuple(w + q * half[2] for w, q in zip(wrist, d)), half,
                                                 (0.0, -math.degrees(math.atan2(d[0], -d[2])), 0.0))),
                ('loft', 'leg.' + side, 'trousers', ([Section(n, c, h) for n, c, h in leg_sections(P, sx)],
                                                     (sx, 0.0, 0.0))),
                ('profile', 'foot.' + side, 'shoe', ((sx * origin[0],) + origin[1:], axis, up, keys))]
    return out


# -- the build --------------------------------------------------------------------------------------------

# The drawn nose stands 2 cm off the face plane; a vertex pulled 6 mm forward reads as a nose.
NOSE = 0.006
# The ear: a lobe of EAR_SIDES sides whose root is sunk EAR_SINK (m) into the skull, so its open base
# never shows, EAR_THICK thick (half size, m), its cupped side facing EAR_FRONT.
EAR_SIDES = 6
EAR_SINK = 0.008
EAR_THICK = 0.006
EAR_FRONT = (1.0, -0.3, 0.0)
# The hair cap: its columns and rows (enough columns to follow this hairline); the hairline's elevation
# above the ears (the drawing lets the hair cover the ear tops); its thickness over the drawn one (m), an
# allowance for the skull's facets, which the cap's faces span as chords; its edge's thickness at the
# forehead (m) and, as a share of the full thickness, at the nape, kept thick there so that the skull's
# facets stay covered at the back.
HAIR_COLUMNS, HAIR_ROWS = 16, 4
HAIR_SIDE_RAD = math.radians(16)
HAIR_EXTRA = 0.0035
HAIR_EDGE = 0.003
HAIR_NAPE = 2.2
# The leg holes' crotch seam above the drawn crotch (m): on this model a seam at the measured crotch reads
# too low; another body places its seam from its own captures.
CROTCH_SEAM = 0.017
# Each leg's first ring follows its hole's outline this far down the leg (m), so the leg leaves the trunk
# in line with it.
LEG_FOLLOW = 0.02
# The palm's share of the mitten's length; the fingers take the rest. The mittens' frame across the hand,
# toward the back: the thumb lies on its other side, in front.
PALM_SHARE = 0.55
ACROSS = (0.0, 1.0, 0.0)
# The shoe's apexes beyond its end keys, (distance along the shoe, height) in metres: the heel's behind
# the heel key, the toe's ahead of the toe key and close to it, so that the toe stays blunt: the further an
# apex lies past its key, the more pointed the end.
HEEL_APEX = (0.007, 0.040)
TOE_APEX = (0.020, 0.018)
SHOE_SIDES = 8
# The face's decals: the eye's half height over its half width, the mouth's half height (m), how far each
# decal stands off the head (m), and the plane in front of the face its outline is cast from (y, m).
EYE_ASPECT = 0.6
MOUTH_HALF_H = 0.005
DECAL_LIFT = 0.0015
DECAL_FRONT_Y = -0.35


def _hairline(P):
    """line(phi) of lpk.forms.hair.hair_cap: the hairline's elevation round the head's centre (radians), over
    the forehead from the front view, above the ears, and at the nape from the side view."""
    cz, D = P['head_c'][2], P['head_half'][1]
    front = math.atan2(P['hairline_front'] - cz, D)
    back = math.atan2(P['hairline_back'] - cz, D)

    def line(phi):
        a = abs(math.atan2(math.sin(phi), math.cos(phi)))         # 0 at the front, pi at the back
        if a < math.pi / 2:
            t = a / (math.pi / 2)
            return front + (HAIR_SIDE_RAD - front) * t * t
        t = (a - math.pi / 2) / (math.pi / 2)
        return HAIR_SIDE_RAD + (back - HAIR_SIDE_RAD) * t
    return line


def _hair_thickness(P):
    """thick(phi, f) of lpk.forms.hair.hair_cap (m): HAIR_EXTRA more than the drawn hair over the crown,
    thinning toward the edge, to HAIR_EDGE at the forehead and HAIR_NAPE times the full thickness at the
    nape."""
    t = P['hair_t'] + HAIR_EXTRA

    def thick(phi, f):
        a = abs(math.atan2(math.sin(phi), math.cos(phi))) / math.pi    # 0 at the front, 1 at the back
        edge = HAIR_EDGE + (t * HAIR_NAPE - HAIR_EDGE) * a
        return t + (edge - t) * f
    return thick


def _profile(stations):
    """(path, profile) of a limb for the weld kernels: the sections' centres in order, and each section as
    (its distance from the first along the centres, its half extent along a, along b), m."""
    path = [Vector(c) for _, c, _ in stations]
    profile, run = [], 0.0
    for i, (_, _, half) in enumerate(stations):
        run += (path[i] - path[i - 1]).length if i else 0.0
        profile.append((run,) + tuple(half))
    return path, profile


def _ear(b, P, skull, data):
    """The left ear (lpk.core.shapes.lobe): its root cast onto the skull from the ear's outer side, its tip
    at its outer back, as wide as its half height. Raises ValueError when the root's ray misses the
    skull."""
    (cx, cy, cz), (hx, hy, hz) = ear_centre(P), EAR_HALF
    root = cast_point(b, skull, (cx + 0.3, cy - hy, cz), (-1.0, 0.0, 0.0), sink=EAR_SINK, distance=1.0, part='ear.L')
    if root is None:
        raise ValueError('the root ray of ear.L missed the skull: move the ear (EAR_HALF, EAR_BACK)')
    lobe(b, 'ear.L', root, (cx + hx, cy + hy, cz), hz, EAR_THICK, EAR_FRONT, 'skin', n=EAR_SIDES)
    edits.apply(b, P, 'ear.L', data)
    b.mirror_part('ear.L', 'ear.R')


def _trunk(b, P, data):
    """The trunk through its sections (lpk.forms.torso.trunk at the sections' exact extents, the rounded-box
    sections at their exponents), its armholes cut between the chest and the armhole sections and its bottom
    ring split into the two leg holes. The shirt colours the trunk up to the collar section; the trousers
    are painted over its lower part by the Trousers source (_trousers). Returns ({side: armhole loop},
    {side: leg hole loop})."""
    sections = trunk_sections(P)
    names = [s.name for s in sections]
    collar = names.index('collar')
    colour = lambda i, j, normal: 'shirt' if i < collar else 'skin'
    rings = [(s.at,) + section_radii(s, torso.SIDES)[:2] for s in sections]
    boxes = tuple((i, s.exponent) for i, s in enumerate(sections) if s.exponent != 2.0)
    # The crotch and the belly keep their full ring; from the waist up the fitted outline.
    R = torso.trunk(b, 'trunk', rings, colour, round_rings=2, boxes=boxes)
    arm_holes = joins.armholes(b, R[names.index('chest')], R[names.index('armhole')], torso.ARMHOLE_COLS)
    leg_holes = joins.leg_holes(b, R[0], 'trunk', P['crotch_z'] + CROTCH_SEAM)
    edits.apply(b, P, 'trunk', data)
    return arm_holes, leg_holes


def _arm(b, P, hole, side, sx, data):
    """The arm of `side` welded out of the trunk's armhole along its sections (lpk.forms.joins.weld_limb),
    the sleeve in the shirt colour down to its hem. Returns the join's vertices for ridge_flip."""
    stations = arm_sections(P, sx)
    path, profile = _profile([(n, c, h) for n, _, c, h in stations])
    d, out = arm_axes(arm_point(P, 'shoulder', sx), arm_point(P, 'wrist', sx))
    hem = [n for n, _, _, _ in stations].index('hem')
    part = 'arm.' + side
    k = joins.weld_limb(b, part, hole, path, profile[0], profile[1], profile[2:], None, Vector((0.0, 1.0, 0.0)),
                        lambda i, j, normal: 'shirt' if i < hem else 'skin', 'shirt', Vector(d), Vector(out))
    edits.apply(b, P, part, data)
    return k['verts']


def _leg(b, P, hole, side, sx, data):
    """The leg of `side` welded out of the trunk's leg hole along its sections (lpk.forms.joins.weld_leg).
    Returns the join's vertices for ridge_flip."""
    path, profile = _profile(leg_sections(P, sx))
    part = 'leg.' + side
    _, verts = joins.weld_leg(b, part, hole, path, profile, None, Vector((sx, 0.0, 0.0)), 'trousers', 'trousers',
                              follow=LEG_FOLLOW)
    edits.apply(b, P, part, data)
    return verts


def mitten_points(P, sx=1.0):
    """The mitten's points (lpk.forms.hands.fist_points) on the side sx, which the build and the rig
    share: the build makes the mitten round them, the rig binds the hand and the mitten fingers to them."""
    wrist, d, out, (thick, half_w, half_len) = hand_box(P, sx)
    length = 2 * half_len
    return hands.fist_points(Vector(wrist), Vector(d), Vector(out), Vector(ACROSS), length * PALM_SHARE,
                             length * (1 - PALM_SHARE), half_w, thick / half_w)


def _mitten(b, P, side, sx, data):
    """The mitten of `side` (lpk.forms.hands.fist_mitten) in its box from the wrist along the arm: the box's
    half sizes are the hand's half thickness, half width and half length; the palm takes PALM_SHARE of the
    length."""
    wrist, d, out, (thick, half_w, half_len) = hand_box(P, sx)
    length = 2 * half_len
    hands.fist_mitten(b, 'hand.' + side, Vector(wrist), Vector(d), Vector(out), Vector(ACROSS), 'skin',
                      length * PALM_SHARE, length * (1 - PALM_SHARE), half_w, thick=thick / half_w)
    edits.apply(b, P, 'hand.' + side, data)


def _shoe(b, P, data):
    """The left shoe through its profile keys (lpk.core.sections.profile_rings, at SHOE_SIDES sides) from a
    rounded heel apex to a blunt toe apex (HEEL_APEX, TOE_APEX), the faces that turn to the floor in the
    sole colour, mirrored into the right one."""
    origin, axis, up, keys = shoe_keys(P)
    rings = profile_rings(origin, axis, up, keys, SHOE_SIDES)
    o, a, u = Vector(origin), Vector(axis), Vector(up)
    heel = o + a * (keys[0].s - HEEL_APEX[0]) + u * HEEL_APEX[1]
    toe = o + a * (keys[-1].s + TOE_APEX[0]) + u * TOE_APEX[1]
    paint = lambda i, j, direction: 'sole' if direction.z < -0.6 else 'shoe'
    b.loft('foot.L', rings, SHOE_SIDES, rings[0][3]['ref'], paint, cap0=tuple(heel), cap1=tuple(toe))
    edits.apply(b, P, 'foot.L', data)
    b.mirror_part('foot.L', 'foot.R')


def _ellipse(cx, cz, rx, rz, n=10):
    """An outline of n points round (cx, cz) with half sizes rx, rz (m), in the plane DECAL_FRONT_Y in front
    of the face."""
    return [(cx + rx * math.cos(2 * math.pi * i / n), DECAL_FRONT_Y, cz + rz * math.sin(2 * math.pi * i / n))
            for i in range(n)]


def _face(P, skull):
    """The eyes and the mouth on a colour source of their own (lpk.core.shapes.fan_decal), cast onto the
    skull from the front and marked for the bake's texel readings."""
    f = Builder(PALETTE)
    for sx in (1.0, -1.0):
        fan_decal(f, 'face', skull, _ellipse(sx * P['eye_x'], P['eye_z'], P['eye_w'], P['eye_w'] * EYE_ASPECT),
                  (0.0, 1.0, 0.0), 'eye', lift=DECAL_LIFT, mark='eye')
    fan_decal(f, 'face', skull, _ellipse(0.0, P['mouth_z'], P['mouth_w'], MOUTH_HALF_H), (0.0, 1.0, 0.0), 'mouth',
              lift=DECAL_LIFT, mark='line')
    return f


# The trousers' colour source: how far it stands off the trunk (m), inside the bake's cage
# (lpk.stages.texture.BAKE_CAGE), and how far below the crotch seam it starts (m), so it covers the trunk's
# faces between the leg holes.
TROUSERS_LIFT = 0.004
TROUSERS_DROP = 0.03


def _trousers(P):
    """The trousers' colour on the trunk as a colour source: a band lofted just off the trunk's sections
    from below the crotch seam up to the shirt's hem (lpk.forms.torso.section_at), which the bake paints
    into the trunk. A colour boundary that does not change the shape belongs to the texture: a hem ring in
    the mesh would crowd the hip, where the leg holes rise."""
    sections = trunk_sections(P)
    low, cut = sections[0], torso.section_at(sections, P['shirt_hem_z'])
    lifted = lambda s, name, z: Section(name, (s.at[0], s.at[1], z),
                                        (s.half[0] + TROUSERS_LIFT, s.half[1] + TROUSERS_LIFT), exponent=s.exponent)
    seam = P['crotch_z'] + CROTCH_SEAM - TROUSERS_DROP
    band = (lifted(low, 'seam', seam), lifted(low, 'crotch', low.at[2]), lifted(cut, 'hem', cut.at[2]))
    t = Builder(PALETTE)
    rings = loft_rings(band, (1.0, 0.0, 0.0), torso.SIDES)
    t.loft('trunk', rings, torso.SIDES, Vector(rings[0][3]['ref']), 'trousers')
    return t


def build_mesh(P):
    """The body and its colour sources. In order: the head and the ears; the hair cap cast onto the
    skull; the trunk with its armholes and leg holes; the arms and the legs welded out of those holes, then
    the folds of the join seams flipped; the mittens; the shoes; then the sources the bake paints in: the
    trousers over the trunk's lower part, the eyes and the mouth into the head. Each part replays its stored
    hand edits right after it is made (P['edits'], lpk.core.edits.apply); the mirrored ear and shoe are
    copies of the edited left ones.
    Returns (the body Builder, {'Face': its Builder, 'Trousers': its Builder})."""
    data = P['edits']
    b = Builder(PALETTE, vert_layers=(joins.LAYER,))
    W, D, H = P['head_half']
    head_form.human_head(b, 'head', Vector(P['head_c']), W, H, D, 'skin', nose=NOSE)
    edits.apply(b, P, 'head', data)
    skull = bvh_of(b, ['head'])
    _ear(b, P, skull, data)
    hair_form.hair_cap(b, 'hair', skull, Vector(P['head_c']), _hairline(P), _hair_thickness(P), 'hair',
                       n=HAIR_COLUMNS, rows=HAIR_ROWS, symmetric=True)
    edits.apply(b, P, 'hair', data)
    arm_holes, leg_holes = _trunk(b, P, data)
    seams = {}
    for side, sx in SIDES:
        seams['arm.' + side] = _arm(b, P, arm_holes[side], side, sx, data)
        seams['leg.' + side] = _leg(b, P, leg_holes[side], side, sx, data)
    # After the last weld and before anything is projected onto the body.
    for part in seams:
        ridge_flip(b, [v for v in seams[part] if v.is_valid], ['trunk'])
    for side, sx in SIDES:
        _mitten(b, P, side, sx, data)
    _shoe(b, P, data)
    return b, {'Face': _face(P, skull), 'Trousers': _trousers(P)}


# -- the atlas ---------------------------------------------------------------------------------------------

# Skin and hair in one group, the garments and the shoes in another at the same density.
ATLAS = (512, {'Body': 1.0, 'Outfit': 1.0})
FACE_PART = 'head'
# The face island's texel density (texels per metre): the mouth, the narrowest painted shape at 1 cm,
# spans 4 texels, four times the one texel a baked line needs to stay unbroken.
FACE_TEXELS = 400
# The colour sources in bake order: the trousers painted into the trunk below the shirt's hem, the eyes and
# the mouth into the head.
SOURCES = {'Trousers': {'mask': ('trunk',)}, 'Face': {'mask': ('head',)}}
# The trunk's panels: front, back, the sides, top and bottom.
BOX = ((0, -1, 0), (0, 1, 0), (1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, -1))
PREVIEW = 'neutral'


def sheet_of(colour, part):
    """The atlas group of a face of palette colour `colour` on part `part`: 'Body' for the skin and the
    hair, 'Outfit' for the garments and the shoes."""
    return 'Body' if colour in ('skin', 'hair') else 'Outfit'


def face_pred(P):
    """The face island's faces of the head: those that look forward, from the chin to the brow, clear of
    the head's sides. Returns the predicate (centre, normal) -> bool over the head's faces (metres)."""
    (cx, cy, cz), (W, D, H) = P['head_c'], P['head_half']
    return lambda centre, normal: (normal[1] < -0.3 and abs(centre[0]) < W * 0.75
                                   and cz - H * 0.95 < centre[2] < cz + H * 0.45)


def seams(P):
    """A seamed unwrap: each tube's seam on its hidden side (an arm's underside against the back of the
    hand, a leg's inner side, a mitten's palm side, a shoe's sole) and the trunk cut into panels."""
    cuts = {}
    for side, sx in SIDES:
        _, out = arm_axes(arm_point(P, 'shoulder', sx), arm_point(P, 'wrist', sx))
        cuts.update({'arm.' + side: [tuple(-c for c in out)], 'leg.' + side: [(-sx, 0.0, 0.0)],
                     'hand.' + side: [(0.0, 1.0, 0.0)], 'foot.' + side: [(0.0, 0.0, -1.0)]})
    return {'cuts': cuts, 'panels': {'trunk': BOX}}


# -- the rig -----------------------------------------------------------------------------------------------

SKELETON = 'biped'
# The hair and the ears follow the head; every other part takes the template's part binding.
ALLOWED = {'hair': ['Head'], 'ear.{s}': ['Head']}
# The welded shoulders and hips are smoothed; the shoulder loop keeps a tenth of the upper arm.
JOINS = [('trunk', 'arm.{s}', {'UpperArm.{s}': 0.10}), ('trunk', 'leg.{s}', {})]
# Blender's own bone heat on a watertight proxy, so the example runs without an add-on.
WEIGHTS = 'heat_proxy'
# One arm, one leg and the head bent.
TEST_POSE = {'UpperArm.L': (0, 0, 60), 'UpperArm.R': (50, 0, 0), 'UpperLeg.L': (35, 0, 0),
             'LowerLeg.L': (-45, 0, 0), 'Head': (0, 20, 0)}
# The spine's joints off the landmarks, this body's choices (m): SPINE_DROP, the lumbar joint below the
# waist and the thorax joint below the armpits; SKULL_BASE, the head's joint behind the neck's centre and
# above the chin; CLAVICLE, a clavicle's inner end out from the midline and above the shoulder joints.
SPINE_DROP = (0.03, 0.12)
SKULL_BASE = (0.003, 0.03)
CLAVICLE = (0.03, 0.01)


def bones(P):
    """The biped's joints with mitten fingers and no tail, {bone: (head, tail)} in metres: the spine on the
    midline (the hip joints' height, under the waist, under the armpits, the collar), the skull's base above
    the chin, the clavicles' inner ends beside the neck, the limbs through their sections, the hands and
    fingers through the mitten's points, the feet through the shoe's ball and toe."""
    pelvis, lumbar = (0.0, 0.0, P['hip_z']), (0.0, 0.0, P['waist_z'] - SPINE_DROP[0])
    thorax = (0.0, 0.0, P['armpit_z'] - SPINE_DROP[1])
    collar = next(s.at for s in trunk_sections(P) if s.name == 'collar')
    skull_base = (0.0, P['neck_y'] + SKULL_BASE[0], P['chin_z'] + SKULL_BASE[1])
    crown = (P['head_c'][0], P['head_c'][1], P['head_c'][2] + P['head_half'][2])
    J = {'Hips': (pelvis, lumbar), 'Spine': (lumbar, thorax), 'Chest': (thorax, collar),
         'Neck': (collar, skull_base), 'Head': (skull_base, crown)}
    for side, sx in SIDES:
        arm = lambda name: arm_point(P, name, sx)
        leg = {n: c for n, c, _ in leg_sections(P, sx)}
        ankle = (sx * P['ankle_x'], 0.0, P['ankle_z'])
        k = mitten_points(P, sx)
        J.update({'Shoulder.' + side: ((sx * CLAVICLE[0], P['neck_y'], P['sh_z'] + CLAVICLE[1]), arm('shoulder')),
                  'UpperArm.' + side: (arm('shoulder'), arm('elbow')),
                  'LowerArm.' + side: (arm('elbow'), arm('wrist')),
                  'Hand.' + side: (arm('wrist'), tuple(k['knuckle'])),
                  'Index.' + side: (tuple(k['knuckle_index']), tuple(k['tip_index'][0])),
                  'Middle.' + side: (tuple(k['knuckle_block']), tuple(k['tip_block'][0])),
                  'Thumb.' + side: (tuple(k['thumb'][0]), tuple(k['thumb'][2])),
                  'UpperLeg.' + side: (leg['hip'], leg['knee']),
                  'LowerLeg.' + side: (leg['knee'], ankle),
                  'Foot.' + side: (ankle, shoe_point(P, 'ball', sx)),
                  'Toes.' + side: (shoe_point(P, 'ball', sx), shoe_point(P, 'toe', sx))})
    return J


# -- export ------------------------------------------------------------------------------------------------

# The brief's engine imports binary glTF; a second output writes FBX from the same body. The example exports
# because its run is the kit's acceptance test; a model of your own adds EXPORTS when the human asks.
EXPORTS = ('glb_generic', 'fbx_generic')
