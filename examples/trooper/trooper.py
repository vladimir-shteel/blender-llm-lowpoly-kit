"""The kit's worked example of a light biped: a trooper, 1.8 m tall, in an A-pose, in a padded suit with
a belt and a chest plate, shoulder pads, a round helmet with a visor, block gloves and boots. It has no
references: every size is a named value of the brief, and each review compares with the human's idea.

Brief: about 600 triangles in one 256 atlas of flat colours, a body seen in groups at a distance; the
biped skeleton at its fifteen required bones and the chest (no neck, clavicles, toes, fingers or tail),
the limbs as separate shells; binary glTF and FBX, and an FBX for a humanoid avatar, from the same body;
about 100 px tall on screen at the farthest play distance.

Run it from an MCP call after the kit's bootstrap (lpk/__init__.py):

    from lpk import run
    run.model(r'<kit>/examples/trooper/trooper.py', stages=('blocks',))
    run.model(r'<kit>/examples/trooper/trooper.py', stages=('build', 'unwrap', 'pack'))
    run.model(r'<kit>/examples/trooper/trooper.py', stages=('bake', 'rig', 'preview', 'export'))

Every value below is this model's choice, reasoned from its brief; a new model derives its own."""
import math

from mathutils import Vector

from lpk.core import edits
from lpk.core.builder import Builder
from lpk.core.shapes import path_rings
from lpk.forms import hard

NAME = 'Trooper'
EDITS = 'edits.json'
PALETTE = {
    'suit': (0.36, 0.40, 0.30),
    'armour': (0.22, 0.24, 0.22),
    'belt': (0.15, 0.13, 0.11),
    'helmet': (0.30, 0.33, 0.26),
    'visor': (0.85, 0.55, 0.15),
    'glove': (0.12, 0.12, 0.13),
    'boot': (0.10, 0.09, 0.09),
}
SIDES = (('L', 1.0), ('R', -1.0))

# -- measurements: the brief's sizes, each with its reason --------------------------------------------------

HEIGHT = 1.80
# The trunk's sections bottom up, (name, height, half width, half depth) in metres: a stocky soldier, the
# chest wider than the hips, the collar closing round the helmet's neck ring.
TRUNK = (('crotch', 0.80, 0.13, 0.09), ('hips', 0.92, 0.17, 0.115), ('belt_low', 0.98, 0.165, 0.11),
         ('belt_high', 1.04, 0.158, 0.106), ('chest', 1.28, 0.19, 0.125), ('shoulders', 1.42, 0.19, 0.115),
         ('collar', 1.50, 0.085, 0.075))
# The helmet's rings bottom up, (height, half width, half depth): the lowest buried in the collar, the
# visor's band between the third and the fourth.
HELMET = ((1.49, 0.055, 0.055), (1.57, 0.09, 0.10), (1.645, 0.115, 0.125), (1.72, 0.11, 0.12),
          (1.775, 0.075, 0.08))
# The shoulder joint (x, z), the arm's drop below horizontal in the A-pose (degrees) and the bone lengths:
# upper arm, forearm, and the glove from the wrist to the fingertips (m).
SHOULDER = (0.21, 1.43)
ARM_DROP = 45.0
ARM_LENGTHS = (0.29, 0.26, 0.18)
# The hip, knee and ankle joints of the left leg (m); the knee a little forward so the leg bends forward.
HIP = (0.095, 0.0, 0.92)
KNEE = (0.10, -0.01, 0.50)
ANKLE = (0.10, 0.02, 0.09)


def props():
    """P in metres: the body's height, the arm's joints on each side (shoulder, elbow, wrist, knuckles,
    fingertips) and its direction, the leg's joints, the head's joint and crown. Pure arithmetic of the
    brief's values."""
    P = {'height': HEIGHT, 'hip': HIP, 'knee': KNEE, 'ankle': ANKLE,
         'neck_z': TRUNK[-1][1], 'crown': (0.0, 0.0, HEIGHT)}
    drop = math.radians(ARM_DROP)
    upper, fore, glove = ARM_LENGTHS
    for side, sx in SIDES:
        d = Vector((sx * math.cos(drop), 0.0, -math.sin(drop)))
        shoulder = Vector((sx * SHOULDER[0], 0.0, SHOULDER[1]))
        elbow = shoulder + d * upper
        wrist = elbow + d * fore
        P['arm.' + side] = {'d': tuple(d), 'shoulder': tuple(shoulder), 'elbow': tuple(elbow),
                            'wrist': tuple(wrist), 'knuckle': tuple(wrist + d * (glove * 0.55)),
                            'tip': tuple(wrist + d * glove)}
    return P


def arm_back(P, side):
    """The direction the back of the glove and the outer face of the pad look in the A-pose: the arm's
    direction turned up by a right angle in its vertical plane."""
    d = Vector(P['arm.' + side]['d'])
    return tuple(Vector((-d.z * (1 if d.x > 0 else -1), 0.0, abs(d.x))).normalized())


def leg_points(P, sx=1.0):
    """The hip, knee and ankle of one leg (sx +1 left, -1 right), metres."""
    return [(sx * p[0], p[1], p[2]) for p in (P['hip'], P['knee'], P['ankle'])]


# -- blocks ----------------------------------------------------------------------------------------------

def blocks(P):
    """The trunk and the helmet as boxes and an ellipsoid, the limbs as tubes through their joints, the
    gloves and the boots as boxes."""
    out = [('box', 'trunk', 'suit', ((0.0, 0.0, 1.15), (0.18, 0.12, 0.35))),
           ('ellipsoid', 'head', 'helmet', ((0.0, 0.0, 1.66), (0.115, 0.125, 0.14)))]
    for side, sx in SIDES:
        a = P['arm.' + side]
        out.append(('tube', 'arm.' + side, 'suit', ((a['shoulder'], a['elbow'], a['wrist']), (0.06, 0.05, 0.04))))
        tilt = sx * ARM_DROP
        out.append(('box', 'hand.' + side, 'glove', (a['knuckle'], (0.09, 0.045, 0.025), (0.0, tilt, 0.0))))
        out.append(('tube', 'leg.' + side, 'suit', (leg_points(P, sx), (0.09, 0.06, 0.05))))
        out.append(('box', 'foot.' + side, 'boot', ((sx * ANKLE[0], -0.04, 0.05), (0.062, 0.13, 0.05))))
    return out


# -- the build --------------------------------------------------------------------------------------------

# Side counts: eight round the trunk and the helmet, the silhouette's main masses; six round the limbs,
# which read as tubes at the read size.
TRUNK_SIDES = 8
HELMET_SIDES = 8
LIMB_SIDES = 6
# The trunk's sections are rounded boxes: a padded suit, not a cylinder.
TRUNK_P = 2.6
# The arm's profile along its path from the shoulder joint, (s, radius) in metres: the root buried in the
# trunk, rings either side of the elbow so it bends, the cuff at the wrist closed by a flat cap.
ARM_PROFILE = ((-0.04, 0.065), (0.25, 0.05), (0.29, 0.048), (0.33, 0.046), (0.55, 0.038))
# The leg's profile from the hip joint: the root buried in the trunk, rings either side of the knee, the
# end inside the boot's shaft.
LEG_PROFILE = ((-0.06, 0.09), (0.10, 0.085), (0.38, 0.062), (0.42, 0.06), (0.46, 0.058), (0.80, 0.05))
# The glove's half width across and half thickness, and its corner cut (m).
GLOVE_HALF = (0.045, 0.032)
GLOVE_CUT = 0.01
# The pad: from this far above the shoulder joint down the upper arm (m), its half width, half thickness,
# lift off the arm's axis and corner cut.
PAD_SPAN = (0.03, 0.13)
PAD_HALF = (0.08, 0.036)
PAD_LIFT = 0.055
PAD_CUT = 0.015
# The boot: its foot as a box from the heel to the toe, (half width, half height, half length) and its
# centre (y, z) for the left foot; the toe narrows by TOE_TAPER; the shaft's top height and radius, its
# open bottom just inside the box's top.
BOOT_HALF = (0.062, 0.05, 0.13)
BOOT_CENTRE = (-0.04, 0.05)
TOE_TAPER = (0.9, 0.7)
BOOT_EDGE = 0.015
SHAFT_SINK = 0.01
SHAFT = (0.22, 0.06)
# The chest plate: the front faces of the bands between the belt and the shoulders, those looking
# forward past this share.
PLATE_FACING = 0.5


def _trunk(b, P, data):
    """The trunk as one loft up its sections, its ends closed flat, the belt band in 'belt' and the chest
    plate in 'armour' on the front of the bands above it."""
    names = [s[0] for s in TRUNK]
    rings = [(Vector((0.0, 0.0, z)), hw, hd, {'p': TRUNK_P}) for _, z, hw, hd in TRUNK]
    belt = names.index('belt_low')
    chest = names.index('chest')

    def paint(i, j, d):
        if i == belt:
            return 'belt'
        if belt < i <= chest and d.y < -PLATE_FACING:
            return 'armour'
        return 'suit'
    b.loft('trunk', rings, TRUNK_SIDES, Vector((1.0, 0.0, 0.0)), paint, cap0='flat', cap1='flat',
           col0='suit', col1='suit', axis=Vector((0.0, 0.0, 1.0)))
    edits.apply(b, P, 'trunk', data)


def _helmet(b, P, data):
    """The helmet as one loft up its rings to an apex at the crown, the visor on the front of its third
    band. Its lowest ring is open, buried in the collar."""
    rings = [(Vector((0.0, 0.0, z)), hw, hd) for z, hw, hd in HELMET]
    paint = lambda i, j, d: 'visor' if i == 2 and d.y < -PLATE_FACING else 'helmet'
    b.loft('head', rings, HELMET_SIDES, Vector((1.0, 0.0, 0.0)), paint, cap1=P['crown'], col1='helmet',
           axis=Vector((0.0, 0.0, 1.0)))
    edits.apply(b, P, 'head', data)


def _arm(b, P, data):
    """The left arm: a loft from inside the trunk through the elbow to the wrist, capped there; the pad on
    the upper arm; the glove from the wrist to the fingertips."""
    a = P['arm.L']
    path = [a['shoulder'], a['elbow'], a['wrist']]
    rings = path_rings(path, [(s, r, r) for s, r in ARM_PROFILE])
    b.loft('arm.L', rings, LIMB_SIDES, Vector((0.0, -1.0, 0.0)), 'suit', cap1='flat')
    edits.apply(b, P, 'arm.L', data)
    d, back = Vector(a['d']), arm_back(P, 'L')
    shoulder = Vector(a['shoulder'])
    hard.segment_plate(b, 'pad.L', shoulder - d * PAD_SPAN[0], shoulder + d * PAD_SPAN[1], back, PAD_HALF[0],
                       PAD_HALF[1], 'armour', lift=PAD_LIFT, corner=PAD_CUT)
    edits.apply(b, P, 'pad.L', data)
    wrist = Vector(a['wrist'])
    hard.segment_plate(b, 'hand.L', wrist - d * 0.01, Vector(a['tip']), back, GLOVE_HALF[0], GLOVE_HALF[1],
                       'glove', corner=GLOVE_CUT)
    edits.apply(b, P, 'hand.L', data)


def _leg(b, P, data):
    """The left leg: a loft from inside the trunk through the knee into the boot's shaft; the boot, its
    shaft round the ankle and its foot a box narrowing to the toe."""
    rings = path_rings(leg_points(P), [(s, r, r) for s, r in LEG_PROFILE])
    b.loft('leg.L', rings, LIMB_SIDES, Vector((1.0, 0.0, 0.0)), 'suit')
    edits.apply(b, P, 'leg.L', data)
    x = P['ankle'][0]
    top, r = SHAFT
    bottom = BOOT_CENTRE[1] + BOOT_HALF[1] - SHAFT_SINK
    b.loft('foot.L', [(Vector((x, P['ankle'][1], bottom)), r, r), (Vector((x, P['ankle'][1], top)), r, r)],
           LIMB_SIDES, Vector((1.0, 0.0, 0.0)), 'boot', cap1='flat')
    hard.chamfer_box(b, 'foot.L', (x, BOOT_CENTRE[0], BOOT_CENTRE[1]), BOOT_HALF,
                     ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, -1.0, 0.0)), 'boot', edge=BOOT_EDGE, taper=TOE_TAPER)
    edits.apply(b, P, 'foot.L', data)


def build_mesh(P):
    """The body: the trunk, the helmet, the left arm, pad, glove, leg and boot, each mirrored to the right.
    Each part replays its stored hand edits right after it is made (P['edits'], lpk.core.edits.apply).
    Returns (the body Builder, {}): flat colours, no colour source."""
    data = P['edits']
    b = Builder(PALETTE)
    _trunk(b, P, data)
    _helmet(b, P, data)
    _arm(b, P, data)
    _leg(b, P, data)
    for part in ('arm', 'pad', 'hand', 'leg', 'foot'):
        b.mirror_part(part + '.L', part + '.R')
    return b, {}


# -- the atlas ---------------------------------------------------------------------------------------------

ATLAS = (256, {'Body': 1.0})
PREVIEW = 'neutral'


def sheet_of(colour, part):
    """The atlas group of every face: 'Body'."""
    return 'Body'


# -- the rig -----------------------------------------------------------------------------------------------

SKELETON = 'biped'
# Separate shells: the trunk takes no weight from the limbs, whose roots it hides; the pads ride the upper
# arms, the gloves their hands, rigidly.
ALLOWED = {'trunk': ['Hips', 'Spine', 'Chest']}
FIXED = {'pad.{s}': {'UpperArm.{s}': 1.0}, 'hand.{s}': {'Hand.{s}': 1.0}}
WEIGHTS = 'heat_proxy'
TEST_POSE = {'UpperArm.L': (0, 0, 60), 'UpperArm.R': (50, 0, 0), 'LowerArm.R': (0, 0, -40),
             'UpperLeg.L': (35, 0, 0), 'LowerLeg.L': (-45, 0, 0), 'Head': (0, 20, 0)}
# The spine's joints (m): the lumbar joint above the belt, the thorax joint at the chest's widest.
LUMBAR_Z = 1.06
THORAX_Z = 1.28


def bones(P):
    """The biped's joints without the neck, the clavicles and the toes, {bone: (head, tail)} in metres: the
    spine on the midline from the hip joints' height to the collar, the head from the collar to the crown,
    the arms and legs through their joints, the hands to the fingertips, the feet to the boots' toes."""
    pelvis = (0.0, 0.0, P['hip'][2])
    collar = (0.0, 0.0, P['neck_z'])
    J = {'Hips': (pelvis, (0.0, 0.0, LUMBAR_Z)), 'Spine': ((0.0, 0.0, LUMBAR_Z), (0.0, 0.0, THORAX_Z)),
         'Chest': ((0.0, 0.0, THORAX_Z), collar), 'Head': (collar, P['crown'])}
    toe_y = BOOT_CENTRE[0] - BOOT_HALF[2]
    for side, sx in SIDES:
        a = P['arm.' + side]
        hip, knee, ankle = leg_points(P, sx)
        J.update({'UpperArm.' + side: (a['shoulder'], a['elbow']), 'LowerArm.' + side: (a['elbow'], a['wrist']),
                  'Hand.' + side: (a['wrist'], a['tip']),
                  'UpperLeg.' + side: (hip, knee), 'LowerLeg.' + side: (knee, ankle),
                  'Foot.' + side: (ankle, (ankle[0], toe_y, BOOT_CENTRE[1]))})
    return J


# -- export ------------------------------------------------------------------------------------------------

# The example exports because its run is the kit's acceptance test of a light rig: the generic outputs and
# the humanoid-avatar FBX, whose avatar takes the fifteen required bones and the chest.
EXPORTS = ('glb_generic', 'fbx_generic', 'unity_humanoid')
