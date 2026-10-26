"""The kit's worked example of first-person arms: a pair of human arms in long sleeves, bare hands with five
fingers, built on the biped template's standard rest so every character's arms share one skeleton and
carry their look in mesh volume. Only the arms are meshed; the rest of the skeleton is there, unweighted,
for the target's humanoid avatar. It has no references: every size is a named value of the brief.

Brief: about 750 triangles in one 512 atlas of flat colours; the biped skeleton at its standard rest
(lpk.skeletons.rest) with full hands, three phalanges on each digit; the first-person camera at EYE;
binary glTF and FBX, and an FBX for a humanoid avatar, from the same body.

Run it from an MCP call after the kit's bootstrap (lpk/__init__.py):

    from lpk import run
    run.model(r'<kit>/examples/fp_arms/fp_arms.py', stages=('build', 'unwrap', 'pack'))
    run.model(r'<kit>/examples/fp_arms/fp_arms.py', stages=('bake', 'rig', 'preview', 'export'))
    run.poses(r'<kit>/examples/fp_arms/fp_arms.py', views=('eye', 'q34'))

Every value below is this model's choice, reasoned from its brief; a new model derives its own."""
from mathutils import Vector

from lpk import skeletons
from lpk.core import edits
from lpk.core.builder import Builder
from lpk.core.shapes import path_rings

NAME = 'FPArms'
EDITS = 'edits.json'
PALETTE = {
    'sleeve': (0.30, 0.36, 0.44),
    'cuff': (0.20, 0.24, 0.30),
    'skin': (0.80, 0.62, 0.50),
    'nail': (0.88, 0.74, 0.66),
}
SIDES = (('L', 1.0), ('R', -1.0))
DIGITS = ('Thumb', 'Index', 'Middle', 'Ring', 'Little')

# -- measurements ------------------------------------------------------------------------------------------

REST = 'standard'
HANDS = 'full'


def props():
    """P: the joints of the biped's standard rest with full hands ({bone: (head, tail)} in metres)."""
    return {'joints': skeletons.rest('biped', REST, {'hands': HANDS})}


# -- the build --------------------------------------------------------------------------------------------

ARM_SIDES = 8
DIGIT_SIDES = 6
# The arm's profile from the shoulder joint along the upper arm, the forearm and the hand to the knuckles,
# (s, half width across, half thickness, colour of the band from this ring) in metres: the sleeve starts
# below the shoulder (the camera never sees higher), rings either side of the elbow, the cuff, the wrist
# flattened, the palm wide and thin, closed flat at the knuckle line.
ARM = ((0.10, 0.046, 0.046, 'sleeve'), (0.25, 0.041, 0.041, 'sleeve'), (0.29, 0.040, 0.040, 'sleeve'),
       (0.33, 0.039, 0.039, 'sleeve'), (0.47, 0.035, 0.033, 'cuff'), (0.50, 0.035, 0.033, 'skin'),
       (0.51, 0.027, 0.020, 'skin'), (0.535, 0.026, 0.019, 'skin'), (0.56, 0.036, 0.014, 'skin'),
       (0.615, 0.041, 0.012, 'skin'))
# A digit's half width and half thickness at its root, the share left at its tip, and the root's depth in
# the palm (m); the thumb is thicker.
DIGIT = (0.0085, 0.0075, 0.75, 0.012)
THUMB = (0.010, 0.009, 0.75, 0.012)


def _arm(b, P, data):
    """The left arm: one loft from the upper arm through the elbow and the wrist into the palm, its ring
    frames turned by the hand's breadth, closed flat at the knuckle line."""
    J = P['joints']
    path = [J['UpperArm.L'][0], J['LowerArm.L'][0], J['Hand.L'][0], J['Hand.L'][1]]
    rings = path_rings(path, [(s, w, t) for s, w, t, _ in ARM])
    colours = [c for _, _, _, c in ARM]
    b.loft('arm.L', rings, ARM_SIDES, Vector((0.0, -1.0, 0.0)), lambda i, j, d: colours[i], cap1='flat', col1='skin')
    edits.apply(b, P, 'arm.L', data)


def _digits(b, P, data):
    """The left hand's digits, each a loft from inside the palm through its three joints to an apex past
    the last, two rings round the first joint so it bends, the last band a nail colour on its back."""
    J = P['joints']
    for name in DIGITS:
        w, t, tip, sink = THUMB if name == 'Thumb' else DIGIT
        joints = [J['%s%d.L' % (name, k)] for k in (1, 2, 3)]
        path = [joints[0][0], joints[1][0], joints[2][0], joints[2][1]]
        L = sum((Vector(c) - Vector(a)).length for a, c in zip(path, path[1:]))
        l1 = (Vector(path[1]) - Vector(path[0])).length
        profile = [(-sink, w, t), (l1 - 0.004, w * 0.95, t * 0.95), (l1 + 0.004, w * 0.92, t * 0.92),
                   (L - 0.006, w * tip, t * tip)]
        part = name.lower() + '.L'
        rings = path_rings(path, profile)
        apex = Vector(path[-1])
        b.loft(part, rings, DIGIT_SIDES, Vector((0.0, -1.0, 0.0)), 'skin', cap1=apex, col1='nail')
        edits.apply(b, P, part, data)


def build_mesh(P):
    """The body: the left arm and its five digits, mirrored to the right. Returns (the body Builder, {})."""
    data = P['edits']
    b = Builder(PALETTE)
    _arm(b, P, data)
    _digits(b, P, data)
    for part in ('arm',) + tuple(d.lower() for d in DIGITS):
        b.mirror_part(part + '.L', part + '.R')
    return b, {}


# -- the atlas ---------------------------------------------------------------------------------------------

ATLAS = (512, {'Body': 1.0})
PREVIEW = 'neutral'


def sheet_of(colour, part):
    """The atlas group of every face: 'Body'."""
    return 'Body'


# -- the rig and the camera --------------------------------------------------------------------------------

SKELETON = 'biped'
# The arm takes the arm's bones, not the chest or the clavicle above where it starts; each digit its
# own chain and the hand (the template's binding).
ALLOWED = {'arm.{s}': ['UpperArm.{s}', 'LowerArm.{s}', 'Hand.{s}']}
WEIGHTS = 'heat_proxy'
# The first-person camera: the eye between the standard rest's eyes, a focal length near a shooter's view.
EYE = {'at': (0.0, -0.09, 1.64), 'lens': 18.0}
# The arms raised into view: the upper arms forward and in, the elbows bent, the hands turned palm in; a
# grip closes the right hand's fingers round a handle, the index finger along the trigger guard.
AIM = {'UpperArm.L': (60, 0, 35), 'LowerArm.L': (0, 0, 70), 'Hand.L': (0, 60, 0),
       'UpperArm.R': (60, 0, -35), 'LowerArm.R': (0, 0, -70), 'Hand.R': (0, -60, 0)}
GRIP = {'%s%d.R' % (d, k): (0, 0, 55 if d != 'Thumb' else 25) for d in DIGITS[2:] for k in (1, 2, 3)}
GRIP.update({'Index1.R': (0, 0, 10), 'Thumb1.R': (0, 0, 20), 'Thumb2.R': (0, 0, 25)})
POSES = {'aim': AIM, 'aim_grip': dict(AIM, **GRIP)}
TEST_POSE = dict(AIM, **GRIP)


def bones(P):
    """The standard rest's joints, every bone of the biped with full hands."""
    return dict(P['joints'])


# -- export ------------------------------------------------------------------------------------------------

EXPORTS = ('glb_generic', 'fbx_generic', 'unity_humanoid')
