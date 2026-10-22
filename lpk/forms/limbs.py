"""Limb lofts along a joint path, and the A-pose arm frame.

A digitigrade leg is a limb along hip, knee, hock and ball (knee forward, hock back, the ball on the
floor); a plantigrade one along hip, knee and ankle."""
import math
from mathutils import Vector

from lpk.core.shapes import path_rings

X = Vector((1, 0, 0)); Y = Vector((0, 1, 0)); Z = Vector((0, 0, 1))


def arm_frame(P, sx, ang):
    """A-pose arm `ang` radians off vertical from P's 'sh_x', 'sh_z', 'upper_arm' and 'forearm';
    sx = 1 for the left (+X) arm. Returns the shoulder S, elbow E, wrist W, the direction d down
    the arm, and `out`: away from the body, perpendicular to the arm (the back of the hand)."""
    S = Vector((sx * P['sh_x'], 0.0, P['sh_z'])); d = Vector((sx * math.sin(ang), 0, -math.cos(ang)))
    E = S + d * P['upper_arm']; W = E + d * P['forearm']
    out = Vector((sx * math.cos(ang), 0, math.sin(ang)))
    return S, E, W, d, out


def limb(b, part, path, profile, n, ref, color):
    """Loft along `path` (e.g. hip, knee, ankle) by an arc-length profile, see path_rings. A limb
    welded into a hole of its parent is joins.weld_limb or joins.weld_leg; shapes.snap_ring snaps a
    buried first ring onto a parent's surface.
    ra runs along `ref` projected off the path and rb across it (Builder.loft: b = t x a). On a
    horizontal path with ref = Z, ra is the height (a sole given its width as ra builds a tall slab).
    On a leg with ref = X, b points to -Y, so a positive 'off' along b moves the ring forward,
    and a is +X on both legs: the inner side is ra_neg on the left leg and ra on the right.
    A joint bends on the rings round it: give it rings above it, at it and below it, since with fewer
    the limb can crumple there in a pose. No spacing or side count fits every limb: set them for this
    limb's size and check the bends in the pose captures. A sleeve's hem, where the sleeve steps out
    from the forearm's width, needs a pair of rings a few millimetres apart.
    Returns rings (lists of BMVerts). Units: path m, profile m (s, ra, rb[, opts]), ref direction, color
    palette name or fn(i, j, d) (Builder.loft's)."""
    return b.loft(part, path_rings(path, profile), n, ref, color)

