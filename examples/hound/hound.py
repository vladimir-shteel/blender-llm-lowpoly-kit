"""The kit's worked example of a quadruped: a lean hound, 0.75 m at the withers, standing square, with a deep
chest and a tucked-up loin, a long muzzle, pricked ears, digitigrade legs on soft paws and a tail held low.
It has no references: every size is a named value of the brief.

Brief: about 650 triangles in one 256 atlas of flat colours; the quadruped skeleton with a three-bone tail,
no jaw, toe bones on all four paws; every part a separate shell; binary glTF and FBX from the same body;
about 100 px tall on screen at the farthest play distance.

Run it from an MCP call after the kit's bootstrap (lpk/__init__.py):

    from lpk import run
    run.model(r'<kit>/examples/hound/hound.py', stages=('blocks',))
    run.model(r'<kit>/examples/hound/hound.py', stages=('build', 'unwrap', 'pack'))
    run.model(r'<kit>/examples/hound/hound.py', stages=('bake', 'rig', 'preview', 'export'))

Every value below is this model's choice, reasoned from its brief; a new model derives its own."""
from mathutils import Vector

from lpk.core import edits
from lpk.core.builder import Builder
from lpk.core.shapes import lobe, path_rings
from lpk.forms import feet, head as head_form, tails

NAME = 'Hound'
EDITS = 'edits.json'
PALETTE = {
    'fur': (0.52, 0.46, 0.38),
    'belly': (0.74, 0.69, 0.60),
    'dark': (0.15, 0.13, 0.12),
    'paw': (0.35, 0.31, 0.27),
}
SIDES = (('L', 1.0), ('R', -1.0))

# -- measurements: the brief's sizes, each with its reason --------------------------------------------------

# The trunk's sections from the rump forward, (y, centre height, half width, half height) in metres: the
# rump narrow over the tail, the hips, the loin tucked up (its centre high, its depth small), the chest deep
# and wide behind the front legs, the withers, the front of the chest closed under the neck.
TRUNK = ((0.36, 0.60, 0.07, 0.07), (0.28, 0.60, 0.10, 0.11), (0.08, 0.64, 0.08, 0.09),
         (-0.15, 0.59, 0.12, 0.17), (-0.28, 0.64, 0.11, 0.14), (-0.36, 0.66, 0.07, 0.09))
# The neck from inside the chest to the back of the skull: (start, end) centres and radii (m).
NECK = (((0.0, -0.30, 0.68), 0.07), ((0.0, -0.38, 0.79), 0.06), ((0.0, -0.44, 0.88), 0.05))
# The head: the cranium's centre, its length unit, half width and half height (snout_head's units).
HEAD = ((0.0, -0.48, 0.90), 0.13, 0.065, 0.07)
# The left legs' joints (m): the front from the scapula's top through the shoulder, elbow, wrist and the
# ball of the paw to the toe tip; the hind from the hip through the stifle, the hock and the ball to the tip.
FRONT = {'scapula': (0.07, -0.24, 0.74), 'shoulder': (0.09, -0.30, 0.55), 'elbow': (0.09, -0.26, 0.38),
         'wrist': (0.09, -0.27, 0.12), 'ball': (0.09, -0.30, 0.035), 'tip': (0.09, -0.37, 0.02)}
HIND = {'hip': (0.08, 0.27, 0.58), 'stifle': (0.09, 0.18, 0.38), 'hock': (0.09, 0.32, 0.16),
        'ball': (0.09, 0.28, 0.035), 'tip': (0.09, 0.21, 0.02)}
# The tail: its root inside the rump, its direction (back and down, held low) and length (m).
TAIL = ((0.0, 0.34, 0.63), (0.0, 1.0, -0.8), 0.36)


def props():
    """P in metres: the joints of each leg on both sides, the tail's line and the spine's points, the
    brief's values."""
    P = {}
    for side, sx in SIDES:
        for name, joints in (('front', FRONT), ('hind', HIND)):
            P['%s.%s' % (name, side)] = {k: (sx * x, y, z) for k, (x, y, z) in joints.items()}
    root, direction, length = TAIL
    d = Vector(direction).normalized()
    P['tail'] = (root, tuple(Vector(root) + d * length))
    P['neck'] = tuple(c for c, _ in NECK)
    P['nose'] = (0.0, HEAD[0][1] - 1.12 * HEAD[1], HEAD[0][2])
    return P


# -- blocks ----------------------------------------------------------------------------------------------

def blocks(P):
    """The trunk and the head as ellipsoids, the neck, the legs and the tail as tubes through their
    joints."""
    out = [('ellipsoid', 'trunk', 'fur', ((0.0, -0.0, 0.62), (0.11, 0.36, 0.15))),
           ('tube', 'neck', 'fur', (P['neck'], (0.07, 0.06, 0.05))),
           ('ellipsoid', 'head', 'fur', ((0.0, -0.53, 0.90), (0.065, 0.14, 0.07))),
           ('tube', 'tail', 'fur', (P['tail'], (0.03, 0.012)))]
    for side, _ in SIDES:
        f, h = P['front.' + side], P['hind.' + side]
        out.append(('tube', 'front_leg.' + side, 'fur',
                    ((f['shoulder'], f['elbow'], f['wrist'], f['ball']), (0.045, 0.034, 0.024, 0.02))))
        out.append(('tube', 'hind_leg.' + side, 'fur',
                    ((h['hip'], h['stifle'], h['hock'], h['ball']), (0.06, 0.04, 0.026, 0.02))))
    return out


# -- the build --------------------------------------------------------------------------------------------

TRUNK_SIDES = 8
NECK_SIDES = 6
HEAD_SIDES = 6
LEG_SIDES = 5
PAW_SIDES = 5
TAIL_SIDES = 5
# The belly: faces of the trunk looking down past this share take the lighter colour.
BELLY_FACING = 0.6
# The legs' profiles along their paths from the shoulder or the hip, (s, radius) in metres: the root
# buried in the trunk, rings either side of the elbow or the stifle and the wrist or the hock so they
# bend, the end buried in the paw.
FRONT_PROFILE = ((-0.05, 0.05), (0.15, 0.038), (0.20, 0.032), (0.42, 0.024), (0.45, 0.023), (0.53, 0.02))
HIND_PROFILE = ((-0.06, 0.07), (0.17, 0.045), (0.25, 0.036), (0.47, 0.026), (0.50, 0.024), (0.64, 0.02))
# The paw: from its heel at the ball to its toe past the tip, half width and height (m).
PAW = (0.032, 0.05)
# The ears: base on the skull and tip (head units of snout_head: s along, height, x across), half width,
# half thickness (m).
EAR = ((0.15, 0.85, 0.55), (0.35, 1.9, 0.75), 0.022, 0.006)
# The tail's profile from its root, (s, radius) in metres.
TAIL_PROFILE = ((0.0, 0.03), (0.15, 0.022), (0.28, 0.014))
# The nose pad: the snout_head band coloured dark (MUZZLE_KEYS' last band).
NOSE_BAND = 8


def _trunk(b, P, data):
    """The trunk as one loft forward through its sections, every ring upright, the rump closed on an apex
    over the tail's root and the chest's front flat under the neck; the belly in the lighter colour."""
    rings = [(Vector((0.0, y, z)), hw, hh, {'p': 2.4}) for y, z, hw, hh in TRUNK]
    paint = lambda i, j, d: 'belly' if d.z < -BELLY_FACING else 'fur'
    rump = Vector((0.0, TRUNK[0][0] + 0.03, TRUNK[0][1]))
    b.loft('trunk', rings, TRUNK_SIDES, Vector((1.0, 0.0, 0.0)), paint, cap0=rump, cap1='flat', col0='fur',
           col1='fur', axis=Vector((0.0, -1.0, 0.0)))
    edits.apply(b, P, 'trunk', data)


def _neck_and_head(b, P, data):
    """The neck from inside the chest into the skull; the head with its nose pad, the left ear (the right
    one a mirrored copy, made in build_mesh)."""
    b.loft('neck', [(Vector(c), r, r) for c, r in NECK], NECK_SIDES, Vector((1.0, 0.0, 0.0)), 'fur')
    edits.apply(b, P, 'neck', data)
    centre, length, width, height = HEAD
    paint = lambda i, j, d: 'dark' if i == NOSE_BAND else 'fur'
    head = head_form.snout_head(b, 'head', centre, length, width, height, paint, n=HEAD_SIDES)
    edits.apply(b, P, 'head', data)
    base, tip, half_w, half_t = EAR
    pt = head['pt']
    lobe(b, 'ear.L', pt(*base[:2], x=base[2]), pt(*tip[:2], x=tip[2]), half_w, half_t, Vector((0.3, -1.0, 0.0)),
         'fur', inner_col='dark', n=4)
    edits.apply(b, P, 'ear.L', data)


def _legs(b, P, data):
    """The left front and hind legs, each a loft through its joints from inside the trunk into its paw,
    and the paws (mirrored to the right in build_mesh)."""
    for name, profile, joints in (('front', FRONT_PROFILE, ('shoulder', 'elbow', 'wrist', 'ball')),
                                  ('hind', HIND_PROFILE, ('hip', 'stifle', 'hock', 'ball'))):
        J = P[name + '.L']
        rings = path_rings([J[k] for k in joints], [(s, r, r) for s, r in profile])
        b.loft(name + '_leg.L', rings, LEG_SIDES, Vector((0.0, -1.0, 0.0)), 'fur')
        edits.apply(b, P, name + '_leg.L', data)
        ball, tip = Vector(J['ball']), Vector(J['tip'])
        heel = Vector((ball.x, ball.y + 0.015, 0.0))
        toe = Vector((tip.x, tip.y - 0.01, 0.0))
        feet.mitt_paw(b, name + '_paw.L', heel, toe, PAW[0], PAW[1], 'paw', 'dark', claws=0, n=PAW_SIDES)
        b.ground_part(name + '_paw.L')
        edits.apply(b, P, name + '_paw.L', data)


def _tail(b, P, data):
    """The tail as one straight loft from inside the rump, its root closed on a buried apex."""
    root, end = (Vector(p) for p in P['tail'])
    d = (end - root).normalized()
    tails.straight_tail(b, 'tail', root, d, (end - root).length, [(s, r, r) for s, r in TAIL_PROFILE], TAIL_SIDES,
                        Vector((1.0, 0.0, 0.0)), 'fur', cap0=root - d * 0.03)
    edits.apply(b, P, 'tail', data)


def build_mesh(P):
    """The body: the trunk, the neck and the head with its ears, the legs and paws, the tail; the left ear,
    legs and paws mirrored to the right. Returns (the body Builder, {})."""
    data = P['edits']
    b = Builder(PALETTE)
    _trunk(b, P, data)
    _neck_and_head(b, P, data)
    _legs(b, P, data)
    _tail(b, P, data)
    for part in ('ear', 'front_leg', 'front_paw', 'hind_leg', 'hind_paw'):
        b.mirror_part(part + '.L', part + '.R')
    return b, {}


# -- the atlas ---------------------------------------------------------------------------------------------

ATLAS = (256, {'Body': 1.0})
PREVIEW = 'neutral'


def sheet_of(colour, part):
    """The atlas group of every face: 'Body'."""
    return 'Body'


# -- the rig -----------------------------------------------------------------------------------------------

SKELETON = 'quadruped'
# The ears ride the head.
ALLOWED = {'ear.{s}': ['Head']}
WEIGHTS = 'heat_proxy'
TEST_POSE = {'Thigh.L': (30, 0, 0), 'Shin.L': (-45, 0, 0), 'HindFoot.L': (35, 0, 0), 'UpperArm.R': (30, 0, 0),
             'FrontFoot.R': (-40, 0, 0), 'Neck': (0, 0, 20), 'Tail.1': (25, 0, 0), 'Tail.2': (20, 0, 0)}
# The spine's joints along the trunk (y, z): the hips over the hip joints, the loin, the withers.
SPINE = ((0.27, 0.62), (0.08, 0.64), (-0.15, 0.65), (-0.30, 0.69))


def bones(P):
    """The quadruped's joints with a three-bone tail and toes, {bone: (head, tail)} in metres: the spine
    along the trunk's top third, the neck and head to the nose, each leg through its joints, the toes
    from the ball to the tip, the tail evenly along its line."""
    s = [(0.0, y, z) for y, z in SPINE]
    J = {'Hips': (s[0], s[1]), 'Spine': (s[1], s[2]), 'Chest': (s[2], s[3]),
         'Neck': (s[3], P['neck'][-1]), 'Head': (P['neck'][-1], P['nose'])}
    for side, _ in SIDES:
        f, h = P['front.' + side], P['hind.' + side]
        J.update({'Scapula.' + side: (f['scapula'], f['shoulder']), 'UpperArm.' + side: (f['shoulder'], f['elbow']),
                  'Forearm.' + side: (f['elbow'], f['wrist']), 'FrontFoot.' + side: (f['wrist'], f['ball']),
                  'FrontToes.' + side: (f['ball'], f['tip']),
                  'Thigh.' + side: (h['hip'], h['stifle']), 'Shin.' + side: (h['stifle'], h['hock']),
                  'HindFoot.' + side: (h['hock'], h['ball']), 'HindToes.' + side: (h['ball'], h['tip'])})
    root, end = (Vector(p) for p in P['tail'])
    for k in range(3):
        J['Tail.%d' % (k + 1)] = (tuple(root.lerp(end, k / 3)), tuple(root.lerp(end, (k + 1) / 3)))
    return J


# -- export ------------------------------------------------------------------------------------------------

# The example exports because its run is the kit's acceptance test of a quadruped.
EXPORTS = ('glb_generic', 'fbx_generic')
