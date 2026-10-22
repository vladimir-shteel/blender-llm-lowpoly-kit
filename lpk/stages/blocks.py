"""The shape blockout: every part as the primitive its shape reads as (a square head a box, a pointed
muzzle a wedge, a limb a loft through its sections), built beside the reference views before any detailed
form, so the forms are chosen to fit a reviewed shape and not a capsule's guess."""
import math

from mathutils import Euler, Vector

from lpk.core import builder as builders
from lpk.core.sections import loft_rings, profile_rings

# Sides of the round blocks: an ellipsoid's rings and a tube's, a loft's and a profile's sections.
SIDES = 8
ELLIPSOID_RINGS = 6
KINDS = ('box', 'wedge', 'ellipsoid', 'tube', 'loft', 'profile')


def _box(b, part, colour, centre, half, rotation_deg=(0.0, 0.0, 0.0)):
    rot = Euler(tuple(math.radians(a) for a in rotation_deg)).to_matrix().to_4x4()
    b.box(part, Vector(centre), tuple(half), rot, colour)


def _wedge(b, part, colour, a, c, half_a, half_c):
    # A four-sided block between two rectangles: p 40 squares the superellipse section.
    b.loft(part, [(Vector(a), half_a[0], half_a[1], {'p': 40.0}), (Vector(c), half_c[0], half_c[1], {'p': 40.0})],
           4, Vector((1, 0, 0)), colour, cap0='flat', cap1='flat')


def _ellipsoid(b, part, colour, centre, half):
    c, (rx, ry, rz) = Vector(centre), half
    angles = [i * math.pi / ELLIPSOID_RINGS for i in range(1, ELLIPSOID_RINGS)]
    rings = [(c + Vector((0, 0, -rz * math.cos(t))), rx * math.sin(t), ry * math.sin(t)) for t in angles]
    b.loft(part, rings, SIDES, Vector((1, 0, 0)), colour, cap0=tuple(c - Vector((0, 0, rz))),
           cap1=tuple(c + Vector((0, 0, rz))))


def _tube(b, part, colour, points, radii):
    b.loft(part, [(Vector(p), r, r) for p, r in zip(points, radii)], SIDES, Vector((1, 0, 0)), colour,
           cap0='flat', cap1='flat')


def _rings(b, part, colour, rings):
    b.loft(part, rings, SIDES, Vector(rings[0][3]['ref']), colour, cap0='flat', cap1='flat')


def _loft(b, part, colour, sections, ref):
    _rings(b, part, colour, loft_rings(sections, ref, SIDES))


def _profile(b, part, colour, origin, axis, up, keys):
    _rings(b, part, colour, profile_rings(origin, axis, up, keys, SIDES))


BUILDERS = {'box': _box, 'wedge': _wedge, 'ellipsoid': _ellipsoid, 'tube': _tube, 'loft': _loft,
            'profile': _profile}


def build(name, blocks, palette, collection, location=(0.0, 0.0, 0.0)):
    """The blocks as the object `name` (lpk.core.builder.finish) in `collection`, one part per block,
    triangulated, faces in the block's palette colour. blocks: [(kind, part, colour, args)], args a tuple:
      'box'       (centre, half sizes (x, y, z), rotation in degrees (x, y, z), optional);
      'wedge'     (a, b, (half x, half y) at a, (half x, half y) at b): four-sided between two rectangles
                  square to the line a-b, a box, a wedge or a taper;
      'ellipsoid' (centre, half sizes (x, y, z));
      'tube'      (points, radii): round, through the points;
      'loft'      (sections, ref): lpk.core.sections.Section records and the direction a starts from;
      'profile'   (origin, axis, up, keys): lpk.core.sections.ProfileKey records along axis.
    Points and sizes in metres. palette: {name: sRGB}. Raises ValueError for an unknown kind before the
    scene changes, and what the section kernel raises. Returns finish's report."""
    return builders.finish(make(blocks, palette), name, collection, location)[1]


def make(blocks, palette):
    """The blocks laid on a new Builder over `palette`, not finished (build's blocks and palette): each
    block's faces carry its colour and its vertices its part, so the builder's mesh tells the part of the
    block nearest a point (lpk.stages.zones reads it so). Raises ValueError for an unknown kind before any
    block is laid. Returns the Builder."""
    unknown = sorted({kind for kind, _, _, _ in blocks} - set(KINDS))
    if unknown:
        raise ValueError('block kinds %s: use %s' % (', '.join(unknown), ', '.join(KINDS)))
    b = builders.Builder(palette)
    for kind, part, colour, args in blocks:
        BUILDERS[kind](b, part, colour, *args)
    return b
