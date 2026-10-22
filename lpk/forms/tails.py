"""Tails."""
import math
from mathutils import Vector

from lpk.core.shapes import path_rings


X = Vector((1, 0, 0)); Y = Vector((0, 1, 0)); Z = Vector((0, 0, 1))


def straight_tail(b, part, root, direction, length, profile, n, ref, color, cap0=None, cap1=None, col0=None,
                  col1=None):
    """A tail at rest: one straight loft along `direction` from `root`, through the sections of
    `profile` as shapes.path_rings reads them ([(s, ra, rb[, opts])], s in metres from root, ra along
    `ref` projected off the path, rb across it), closed on an apex at its tip, root + direction *
    length. A tail's rest shape is straight because the rig's bone chain, spaced evenly along it, gives
    every curl: put rings where the chain must bend. Every section stays perpendicular to `direction`;
    keep the profile's last s short of `length`, or the tip's cone folds back over it.
    cap0: the root's close: a point closes it on an apex there, buried in the body, as a plain tail's
    root is closed; None, the default, leaves it open, which only a part ATLAS.strips unrolls
    needs (its root then starts deep enough in the body that no neighbour uncovers the opening);
    'flat' closes it flat. cap1: the tip's close: None the apex at root + direction * length, 'flat'
    a flat end, a point an apex there. col0, col1: one colour for each cap, as Builder.loft takes
    them.
    Returns the rings from the root to the tip, each the list of its BMVerts as Builder.loft returns
    it: what shapes.band_source and shapes.ring_band read. With the root open, the tip on an apex and
    nothing else in the part, ATLAS.strips unrolls the part as one strip.
    Units: color palette name or fn(i, j, d) (Builder.loft's), cap0 None, 'flat' or an apex point (m)."""
    d = Vector(direction).normalized()
    root = Vector(root)
    tip = root + d * length
    return b.loft(part, path_rings((root, tip), profile), n, ref, color, cap0=cap0,
                  cap1=tip if cap1 is None else cap1, col0=col0, col1=col1, axis=d)


def lock_fan(b, part, root, locks, col, knot=((0.05, 0.05), (0.06, 0.055), (0.04, 0.04)), spread=0.18, drop=0.25,
             thick=0.012, wide=0.045, bend=0.5):
    """A tail of long flat locks fanning back and down from a small knot buried under clothing (a
    feathered tail): locks (angle under the horizontal backward in degrees, length); every
    other one splits into a mirrored pair `spread` to the sides, the others run on the midline; all
    curl down. spread, drop: the sideways and downward components of a lock's direction before it is
    normalised, not distances: a larger value turns the lock further, it does not move it.
    knot: the (ra, rb) of a closed six-sided loft along +Y round the roots.
    Units: root m, knot ((m, m) half sizes, ...), thick m (half size), wide m (half size), bend rad. Spread
    and drop are components of a lock's direction before normalising, not distances."""
    from lpk.forms.hands import talon
    offs = (Vector((0, -0.04, 0)), Vector((0, 0.03, -0.01)), Vector((0, 0.08, -0.03)))
    b.loft(part, [(root + o, ra, rb) for o, (ra, rb) in zip(offs, knot)], 6, X, col,
           cap0=root + Vector((0, -0.07, 0)), cap1=root + Vector((0, 0.11, -0.05)))
    for k, (ang, ln) in enumerate(locks):
        a = math.radians(ang)
        for sx in ((-1, 1) if k % 2 else (0,)):
            d = Vector((sx * spread, math.cos(a), math.sin(a) - drop)).normalized()
            curl = Vector((0, 0, -1)) - d * d.z
            talon(b, part, root + Vector((sx * 0.02, 0.02, 0)), d, curl, ln, thick, wide, col, tip_col=col,
                  bend=bend, n=4, tip=0.2)
