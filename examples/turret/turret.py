"""The kit's worked example of a rigid mechanism: a floor turret, 0.8 m tall, on a stepped pedestal, its
head turning about the vertical, its gun cradle tilting between two side arms, its barrel recoiling. It has
no references: every size is a named value of the brief.

Brief: about 400 triangles in one 256 atlas of flat colours; the rigid skeleton, a root at the pedestal and
one bone per moving piece (the head's yaw, the cradle's pitch, the barrel's recoil), each part pinned to the
bone it moves with; binary glTF and FBX from the same body; the pivot at the centre of the pedestal's base,
on the floor, the gun facing -Y; about 120 px tall on screen at the farthest play distance.

Run it from an MCP call after the kit's bootstrap (lpk/__init__.py):

    from lpk import run
    run.model(r'<kit>/examples/turret/turret.py', stages=('blocks',))
    run.model(r'<kit>/examples/turret/turret.py', stages=('build', 'unwrap', 'pack'))
    run.model(r'<kit>/examples/turret/turret.py', stages=('bake', 'rig', 'preview', 'export'))

Every value below is this model's choice, reasoned from its brief; a new model derives its own."""
from lpk.core import edits
from lpk.core.builder import Builder
from lpk.forms import hard

NAME = 'Turret'
EDITS = 'edits.json'
PALETTE = {
    'body': (0.55, 0.55, 0.50),
    'dark': (0.18, 0.18, 0.20),
    'metal': (0.35, 0.36, 0.38),
    'trim': (0.85, 0.45, 0.10),
    'lens': (0.90, 0.12, 0.10),
}
# A frame whose prism runs forward along -Y, its sections across (X) and up (Z): the gun's pieces.
FORWARD = ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, -1.0, 0.0))

# -- measurements: the brief's sizes, each with its reason --------------------------------------------------

# The pedestal's stations bottom up, (height, half size, corner cut) in metres: a wide foot that reads as
# bolted to the floor, a step in, a column up to the head's bearing.
PEDESTAL = ((0.0, 0.30, 0.09), (0.08, 0.30, 0.09), (0.08, 0.20, 0.06), (0.50, 0.14, 0.04))
# The head: the bearing's height (the yaw pivot), the housing's centre height and half sizes (x, y, z), its
# corner and bevel.
BEARING_Z = 0.50
HOUSING = ((0.0, 0.02, 0.60), (0.17, 0.15, 0.08))
HOUSING_CUT = (0.03, 0.01)
# The side arms the cradle swings between: their centre (x, y, z) on the left and half sizes.
ARM = ((0.16, 0.0, 0.72), (0.025, 0.08, 0.08))
# The cradle's pitch axis height, the gun body's centre (y), half sizes (across, up, along) and corner cut.
PITCH_Z = 0.74
GUN = (-0.04, (0.11, 0.08, 0.15), 0.025)
# The hubs on the pitch axis: radius and depth (m), half their depth buried in the arm's outer face.
HUB = (0.045, 0.02)
# The barrel: its root inside the gun body and its muzzle (y), its radius; the muzzle brake's radius and
# length; the recoil stroke the review pose pulls back (m).
BARREL = (-0.16, -0.48, 0.028)
BRAKE = (0.042, 0.05)
RECOIL = 0.08
# The ammunition box on the head's right side: centre and half sizes.
AMMO = ((-0.21, 0.04, 0.60), (0.04, 0.09, 0.06))


def props():
    """P in metres: the turret's height and the pivots of its moving pieces (the yaw bearing, the pitch
    axis, the barrel's line), the brief's values."""
    return {'height': PITCH_Z + GUN[1][1], 'bearing_z': BEARING_Z, 'pitch_z': PITCH_Z,
            'barrel': ((0.0, BARREL[0], PITCH_Z), (0.0, BARREL[1], PITCH_Z))}


# -- blocks ----------------------------------------------------------------------------------------------

def blocks(P):
    """The pedestal, the head, the gun and the barrel as boxes and tubes."""
    return [('box', 'base', 'body', ((0.0, 0.0, 0.25), (0.25, 0.25, 0.25))),
            ('box', 'head', 'body', HOUSING),
            ('box', 'gun', 'dark', ((0.0, GUN[0], PITCH_Z), (GUN[1][0], GUN[1][2], GUN[1][1]))),
            ('tube', 'barrel', 'metal', (P['barrel'], (BARREL[2], BARREL[2])))]


# -- the build --------------------------------------------------------------------------------------------

BARREL_SIDES = 8
HUB_SIDES = 8
# The lens: a slot on the gun's front face, its width and height (m), just off the face.
LENS = (0.12, 0.025)
DECAL_OFF = 0.002


def _pedestal(b, P, data):
    """The pedestal: a chamfered prism up its stations, the step's face looking up, a trim band on the
    foot's sides."""
    paint = lambda band, side: 'trim' if band == 0 else 'body'
    hard.chamfer_loft(b, 'base', (0.0, 0.0, 0.0), None, [(z, h, h, cut) for z, h, cut in PEDESTAL], paint,
                      'dark', 'dark')
    edits.apply(b, P, 'base', data)


def _head(b, P, data):
    """The head: the housing over the bearing, the left arm (mirrored to the right after), the ammunition
    box on the right."""
    hard.chamfer_box(b, 'head', HOUSING[0], HOUSING[1], None, 'body', corner=HOUSING_CUT[0], edge=HOUSING_CUT[1])
    edits.apply(b, P, 'head', data)
    hard.chamfer_box(b, 'arm.L', ARM[0], ARM[1], None, 'body')
    edits.apply(b, P, 'arm.L', data)
    hard.chamfer_box(b, 'ammo', AMMO[0], AMMO[1], None, 'dark', corner=0.01)
    edits.apply(b, P, 'ammo', data)


def _cradle(b, P, data):
    """The cradle: the gun body along -Y with its lens on the front, the left hub on the pitch axis, its back
    buried in the arm and its cap on the arm's outer face (mirrored after)."""
    y, half, cut = GUN
    hard.chamfer_box(b, 'gun', (0.0, y, PITCH_Z), half, FORWARD, 'dark', corner=cut)
    front = y - half[2] - DECAL_OFF
    hard.slot(b, 'gun', (0.0, PITCH_Z + half[1] * 0.4), (1.0, 0.0), LENS[0], LENS[1], 'lens', (0.0, front, 0.0))
    edits.apply(b, P, 'gun', data)
    outer = ARM[0][0] + ARM[1][0]
    hard.hub(b, 'hub.L', (outer - HUB[1] * 0.5, ARM[0][1], PITCH_Z), (1.0, 0.0, 0.0), HUB[0], HUB[1], 'metal',
             'trim', n=HUB_SIDES)
    edits.apply(b, P, 'hub.L', data)


def _barrel(b, P, data):
    """The barrel from inside the gun body to the muzzle, and the muzzle brake round its end."""
    root, muzzle = P['barrel']
    hard.hinge(b, 'barrel', root, muzzle, BARREL[2], 'metal', 'dark', n=BARREL_SIDES)
    r, length = BRAKE
    hard.hinge(b, 'barrel', (0.0, muzzle[1] + length * 0.6, PITCH_Z), (0.0, muzzle[1] - length * 0.4, PITCH_Z),
               r, 'dark', n=BARREL_SIDES)
    edits.apply(b, P, 'barrel', data)


def build_mesh(P):
    """The body: the pedestal, the head with its arms and box, the cradle with its hubs, the barrel; the
    arm and the hub mirrored to the right. Each part replays its stored hand edits right after it is made.
    Returns (the body Builder, {}): flat colours, no colour source."""
    data = P['edits']
    b = Builder(PALETTE)
    _pedestal(b, P, data)
    _head(b, P, data)
    _cradle(b, P, data)
    _barrel(b, P, data)
    b.mirror_part('arm.L', 'arm.R')
    b.mirror_part('hub.L', 'hub.R')
    return b, {}


# -- the atlas ---------------------------------------------------------------------------------------------

ATLAS = (256, {'Body': 1.0})
PREVIEW = 'neutral'


def sheet_of(colour, part):
    """The atlas group of every face: 'Body'."""
    return 'Body'


# -- the rig -----------------------------------------------------------------------------------------------

SKELETON = 'rigid'
# Every part moves with one bone and bends nowhere.
FIXED = {'base': {'Root': 1.0}, 'head': {'Yaw': 1.0}, 'arm.{s}': {'Yaw': 1.0}, 'ammo': {'Yaw': 1.0},
         'gun': {'Pitch': 1.0}, 'hub.{s}': {'Pitch': 1.0}, 'barrel': {'Barrel': 1.0}}
# The distance weights carry FIXED alone: no part takes blended weights.
WEIGHTS = 'distance'
# The yaw bone stands up, so a turn about its own Y turns the head; the pitch and barrel bones point along
# the gun with their Z up, so a turn about X tilts the gun and an offset along Y slides the barrel.
UP = (0.0, 0.0, 1.0)
POSES = {'yaw': {'Yaw': (0, 45, 0)}, 'aim_up': {'Pitch': (25, 0, 0)}, 'aim_down': {'Pitch': (-15, 0, 0)},
         'recoil': {'Barrel': {'loc': (0, -RECOIL, 0)}}}
TEST_POSE = {'Yaw': (0, -30, 0), 'Pitch': (15, 0, 0), 'Barrel': {'loc': (0, -RECOIL, 0)}}


def bones(P):
    """The root from the floor up the pedestal, {bone: (head, tail)} in metres."""
    return {'Root': ((0.0, 0.0, 0.0), (0.0, 0.0, P['bearing_z']))}


def extra_bones(P):
    """The moving pieces' bones: the yaw from the bearing up, the pitch on its axis pointing forward, the
    barrel along its line."""
    root, muzzle = P['barrel']
    return {'Yaw': {'head': (0.0, 0.0, P['bearing_z']), 'tail': (0.0, 0.0, P['pitch_z']), 'parent': 'Root'},
            'Pitch': {'head': (0.0, 0.0, P['pitch_z']), 'tail': (0.0, GUN[0], P['pitch_z']), 'parent': 'Yaw',
                      'roll': UP},
            'Barrel': {'head': root, 'tail': muzzle, 'parent': 'Pitch', 'roll': UP}}


# -- export ------------------------------------------------------------------------------------------------

# The example exports because its run is the kit's acceptance test of a rigid mechanism.
EXPORTS = ('glb_generic', 'fbx_generic')
