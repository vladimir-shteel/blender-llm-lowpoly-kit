"""Fur tufts and shaggy fringes."""
import math
from mathutils import Vector


X = Vector((1, 0, 0)); Y = Vector((0, 1, 0)); Z = Vector((0, 0, 1))


def tuft(b, part, base, tip, width, col, tip_col=None, thick=None, front=None, n=3, neck=0.6, seal=False):
    """Volumetric spike for hair locks and fur tufts: one tapering section and a cone to `tip`.
    Base left open to be buried, or closed flat with `seal` where the host is too thin to bury it or a
    neighbour can uncover it: an open base that shows lets the tuft's inside show. thick/front flatten
    it across `front`; tip_col colours the cone,
    which starts at `neck` (fraction of the length), so a later neck keeps the tint to the tip.
    Four round sides read as a spike; three flattened ones (a small thick, front set) as a shard or a
    blade. It runs straight from base to tip: tufts all round a crown read as a hedgehog's spikes where
    the drawing sweeps a forelock forward and a ruff back. A lock that sweeps or hooks is hands.talon,
    bending toward a curl direction through `bend` on a circular arc with its base buried (a wide
    section in the curl plane and a thin one across it gives a curved blade), or fur.flame_locks for a
    fan of them from one root. Tufts rooted on a surface go through the forms that find their roots:
    hair.hair_locks casts each straight down onto a head, fur.fur_fringe roots them round a loft's
    ring.
    Returns rings (lists of BMVerts). Units: base m, tip m, width m (half size), thick m (half size)."""
    base = Vector(base); tip = Vector(tip); axis = (tip - base).normalized()
    front = Vector(front) if front is not None else (Z if abs(axis.dot(Z)) < 0.9 else Y)
    across = axis.cross(front).normalized()
    thick = thick or width
    mid = base + (tip - base) * neck
    return b.loft(part, [(base, width, thick), (mid, width * 0.62, thick * 0.62)], n, across, col,
                  cap0='flat' if seal else None, cap1=tip, col1=tip_col or col)


def tuft_fan(b, part, root, out, up, across, spikes, col, tip_col=None, flat=0.4):
    """Tufts fanning from one buried `root` in the plane of `out` and `up` (shoulder
    epaulettes). spikes: (angle from `out` toward `up` in degrees, lean along `across`, length,
    width); `flat` is the thickness over the width. `across` is given, not derived, so a mirrored
    pair (out = +-X) leans the same way.
    Units: root m, flat ratio. A spike's lean is a weight on `across` added to its unit direction before
    normalising, not a distance."""
    out = Vector(out).normalized(); up = Vector(up).normalized(); across = Vector(across).normalized()
    for ang, dy, ln, wd in spikes:
        a = math.radians(ang)
        tip = root + (out * math.cos(a) + up * math.sin(a) + across * dy).normalized() * ln
        tuft(b, part, root, tip, wd, col, tip_col=tip_col, thick=wd * flat, front=across)


def fur_fringe(b, part, ring, along, length, width, col, tip_col=None, keep=None, out=0.45, step=2, seal=False):
    """Shaggy edge on a fur loft: tufts rooted just inside every `step`-th vertex of `ring` (BMVerts
    returned by a loft), leaning outward from the ring centre by `out` and otherwise along `along`
    (a vector, or fn(radial) -> vector). keep(radial) can restrict them to one side of the ring.
    out about 0.5 sweeps the tufts back; about 0.65 radiates them like a sunburst.
    Units: along direction, or fn(radial) -> direction, length m, width m (half size), out ratio."""
    centre = sum((v.co for v in ring), Vector()) / len(ring)
    for k in range(0, len(ring), step):
        p = ring[k].co.copy()
        radial = (p - centre).normalized()
        if keep and not keep(radial):
            continue
        a = along(radial) if callable(along) else Vector(along)
        base = centre + (p - centre) * 0.8
        tip = p + (radial * out + a.normalized() * (1 - out)).normalized() * length
        tuft(b, part, base, tip, width, col, tip_col=tip_col, thick=width * 0.55, front=radial, seal=seal)


def fur_mass(b, part, rings, n, ref, col, fringes=(), cap0=None, cap1=None, axis=None):
    """A huge mass of fur or hair (a giant's mane round the neck, a fringe falling from the crown
    down one side): one smooth loft through `rings` (Builder.loft sections), with big fur_fringe tufts
    only where the outline needs them; the inner mass stays smooth and its jagged pattern is texture.
    fringes: dicts with 'ring' (index into the loft's rings), 'along', 'length', 'width', 'col' and
    optionally 'shift' (start the tufts that many vertices round the ring, to alternate rows),
    'tip_col', 'keep', 'out', 'step', 'seal' (as fur_fringe). Returns the rings.
    The drawn outline runs over the tuft tips, so the smooth volume sits inside it by the tufts'
    reach: compare the mass with its fringes against the drawing. A shallow cap0 can fold the first
    band across the cone: bury it well inside the head when the mass starts on it. How far an apex
    sits behind the last ring sets how the end reads, close behind it a flat disc: match the end to
    the drawing in the side capture.
    Units: rings m (Builder.loft sections), ref direction, col palette name or fn(i, j, d)
    (Builder.loft's)."""
    R = b.loft(part, rings, n, ref, col, cap0=cap0, cap1=cap1, axis=axis)
    for f in fringes:
        s = f.get('shift', 0)
        ring = R[f['ring']][s:] + R[f['ring']][:s]
        fur_fringe(b, part, ring, f['along'], f['length'], f['width'], f['col'], tip_col=f.get('tip_col'),
                   keep=f.get('keep'), out=f.get('out', 0.45), step=f.get('step', 2), seal=f.get('seal', False))
    return R


def flame_locks(b, part, root, locks, col, side, scale=1.0, thick=0.010, wide=0.045, spread=0.045, tip=0.15):
    """A mane of flat flame-shaped locks fanning from one root inside the skull: each a
    curved blade (hands.talon with a wide section in the curl plane and a thin one across it).
    locks: (angle in the front plane from straight up toward the side, length, lean back along +Y,
    curl sign, bend in radians); a lock starts `spread` out from the root along its angle. Curl 1
    flicks the tip up and out like a flame, -1 hooks it down; alternating signs read as a spider's
    legs, and a single arc cannot give a drawn mane's S-curves. 5 * 4 triangles a lock.
    Units: root m, locks (deg, m, ratio, sign, rad), scale ratio, thick m (half size), wide m (half size)."""
    from lpk.forms.hands import talon
    for k, (ang, ln, back, curl_s, bend) in enumerate(locks):
        a = math.radians(ang)
        out = Vector((side * math.sin(a), 0, math.cos(a)))
        d = (out + Y * back).normalized()
        base = root + out * spread + Y * (0.012 * (k % 3))
        curl = out.cross(Y).normalized()
        if curl.dot(Z + X * (side * 0.3)) < 0:
            curl = -curl
        curl *= curl_s
        talon(b, part, base, d, curl, ln * scale, thick, wide, col, tip_col=col, bend=bend, n=4, tip=tip)
