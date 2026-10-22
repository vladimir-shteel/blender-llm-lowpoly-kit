"""The kit's worked example of a prop: a wooden barrel, 0.9 m tall, with four iron hoops and a bung on its
front. It is measured from the one front view drawn for it (refs/, drawn by draw_refs.py) through
views.json: a barrel is round, so the front view gives every size.

Brief: about 500 triangles in one 256 atlas of flat colours; no rig; binary glTF for the engine and FBX
from the same body; the pivot at the centre of the base, on the floor; about 150 px tall on screen at the
farthest play distance.

Run it from an MCP call after the kit's bootstrap (lpk/__init__.py):

    from lpk import run
    run.model(r'<kit>/examples/barrel/barrel.py', stages=('reference', 'blocks'))
    run.model(r'<kit>/examples/barrel/barrel.py', stages=('build', 'unwrap', 'pack'))
    run.model(r'<kit>/examples/barrel/barrel.py', stages=('bake', 'preview', 'export'))

Every value below is this model's choice, measured or reasoned from its reference and brief; a new
model derives its own."""
import os

from mathutils import Vector

from lpk.core import edits
from lpk.core.builder import Builder
from lpk.core.sections import Section
from lpk.core.shapes import bvh_of, cast_point
from lpk.core.views import Views

NAME = 'Barrel'
VIEWS = 'views.json'
EDITS = 'edits.json'
# The flat colours of refs/front.png (lpk.intake.sample_colours); 'head', the end grain of the two ends,
# which the front view does not show, is the staves' wood lightened.
PALETTE = {
    'wood': (0.55, 0.36, 0.20),
    'head': (0.62, 0.45, 0.28),
    'iron': (0.25, 0.25, 0.27),
    'bung': (0.35, 0.22, 0.12),
}

# -- measurements ------------------------------------------------------------------------------------------

# The hoops, numbered from the base up, as views.json names their edges.
HOOPS = (1, 2, 3, 4)


def props():
    """P from the front view of views.json, in metres: the barrel's height (its top, the landmark 'crown'
    the calibration reads with 'sole'), the staves' radius at the base,
    the bilge (its widest row) and the top, the height of the bilge, each hoop's lower and upper edge, how
    far the hoops stand off the staves (read where the third hoop's rim crosses the outline), and the bung's
    height and radius."""
    views = Views(os.path.join(os.path.dirname(__file__), VIEWS))
    front = views.calib('front')
    marks, width = views.landmarks('front'), views.widths('front')
    mid = views.view('front')['mid_px']

    def z(key):
        return front.z(marks[key][1])

    def w(key):
        return front.m(width[key])

    P = {'height': z('crown'), 'base_r': w('base') / 2, 'bilge_z': z('bilge'), 'bilge_r': w('bilge') / 2,
         'top_r': w('top') / 2,
         'hoops': [(z('hoop.%d.bottom' % k), z('hoop.%d.top' % k)) for k in HOOPS],
         'bung_z': z('bung'), 'bung_r': w('bung') / 2}
    rim = marks['hoop.3.rim']
    P['hoop_proud'] = front.m(rim[0] - mid) - stave_radius(P, front.z(rim[1]))
    return P


def stave_radius(P, z):
    """The staves' radius at height z (m): the parabola through the base, the bilge and the top, the
    drawing's bulge."""
    pts = ((0.0, P['base_r']), (P['bilge_z'], P['bilge_r']), (P['height'], P['top_r']))
    r = 0.0
    for i, (zi, ri) in enumerate(pts):
        term = ri
        for j, (zj, _) in enumerate(pts):
            if j != i:
                term *= (z - zj) / (zi - zj)
        r += term
    return r


def stave_rings(P):
    """The staves' rings from the base up, [(height, radius, hoop)] in metres: the base, each hoop as four
    rings (the staves' radius and the hoop's at its lower edge, the hoop's and the staves' at its upper
    edge, hoop its number) with the bilge ring between the hoops below and above it, and the top. hoop is
    None on the staves' own rings."""
    proud = P['hoop_proud']
    rings = [(0.0, P['base_r'], None)]
    stations = [(z0, z1, k) for k, (z0, z1) in zip(HOOPS, P['hoops'])] + [(P['bilge_z'], None, None)]
    for z0, z1, k in sorted(stations):
        if k is None:
            rings.append((z0, stave_radius(P, z0), None))
            continue
        r0, r1 = stave_radius(P, z0), stave_radius(P, z1)
        rings += [(z0, r0, None), (z0, r0 + proud, k), (z1, r1 + proud, k), (z1, r1, None)]
    rings.append((P['height'], P['top_r'], None))
    return rings


# -- blocks ----------------------------------------------------------------------------------------------

def blocks(P):
    """The staves as a loft through the base, the bilge and the top, the bung as a short tube on the
    front."""
    sections = [Section(n, (0.0, 0.0, z), (stave_radius(P, z),) * 2)
                for n, z in (('base', 0.0), ('bilge', P['bilge_z']), ('top', P['height']))]
    front = -stave_radius(P, P['bung_z'])
    return [('loft', 'barrel', 'wood', (sections, (1.0, 0.0, 0.0))),
            ('tube', 'bung', 'bung', (((0.0, front + BUNG_SINK, P['bung_z']), (0.0, front - BUNG_PROUD, P['bung_z'])),
                                      (P['bung_r'], P['bung_r'])))]


# -- the build --------------------------------------------------------------------------------------------

# The staves' sides: at 12 the outline stays round at the read size.
STAVE_SIDES = 12
# The bung: its sides, how far it stands off the staves and how deep its open base is sunk into them (m).
BUNG_SIDES = 6
BUNG_PROUD = 0.008
BUNG_SINK = 0.01


def _staves(b, P, data):
    """The staves and the hoops as one loft up the barrel's axis (every ring level, the hoops' steps flat
    rings), the hoop bands and their steps in iron, the two ends flat in the end grain's colour."""
    rings = stave_rings(P)
    hoop = [k for _, _, k in rings]
    paint = lambda i, j, d: 'iron' if hoop[i] is not None or hoop[i + 1] is not None else 'wood'
    b.loft('barrel', [(Vector((0.0, 0.0, z)), r, r) for z, r, _ in rings], STAVE_SIDES, Vector((1.0, 0.0, 0.0)),
           paint, cap0='flat', cap1='flat', col0='head', col1='head', axis=Vector((0.0, 0.0, 1.0)))
    edits.apply(b, P, 'barrel', data)


def _bung(b, P, staves, data):
    """The bung: a short tube cast onto the staves' front at the bung's height, its open base sunk into
    them, its outer end flat. Raises ValueError when the cast misses the staves."""
    root = cast_point(b, staves, (0.0, -1.0, P['bung_z']), (0.0, 1.0, 0.0), sink=BUNG_SINK, distance=2.0,
                      part='bung')
    if root is None:
        raise ValueError('the bung missed the staves: check bung_z against the barrel\'s height')
    tip = root + Vector((0.0, -(BUNG_SINK + BUNG_PROUD), 0.0))
    r = P['bung_r']
    b.loft('bung', [(root, r, r), (tip, r, r)], BUNG_SIDES, Vector((0.0, 0.0, 1.0)), 'bung', cap1='flat')
    edits.apply(b, P, 'bung', data)


def build_mesh(P):
    """The body: the staves with their hoops, then the bung cast onto them. Each part replays its stored
    hand edits right after it is made (P['edits'], lpk.core.edits.apply). Returns (the body Builder, {}):
    the barrel has no colour source."""
    data = P['edits']
    b = Builder(PALETTE)
    _staves(b, P, data)
    _bung(b, P, bvh_of(b, ['barrel']), data)
    return b, {}


# -- the atlas ---------------------------------------------------------------------------------------------

# Flat colours only: one group.
ATLAS = (256, {'Prop': 1.0})
PREVIEW = 'neutral'


def sheet_of(colour, part):
    """The atlas group of every face: 'Prop'."""
    return 'Prop'


def seams(P):
    """A seamed unwrap: the colour borders (each hoop, each wood band between them, the ends, the bung) cut
    the islands, and each ring-shaped band is cut open at the back, out of sight."""
    return {'cuts': {'barrel': [(0.0, 1.0, 0.0)], 'bung': [(0.0, 0.0, -1.0)]}}


# -- export ------------------------------------------------------------------------------------------------

# No SKELETON: the barrel has no rig, and the export writes its body alone. The brief's engine imports
# binary glTF; a second output writes FBX from the same body.
EXPORTS = ('glb_generic', 'fbx_generic')
