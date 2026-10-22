"""Welded joins: limbs grown out of holes in the body, sharing its vertices. The hole loops are
tagged 1 in the int vertex layer `join_loop` (LAYER: the body's Builder needs it among its vert_layers;
armholes and leg_holes raise without it), which the skin smoothing reads for its zones
(lpk.stages.rig.join_zones)."""
import bmesh
from mathutils import Vector

from lpk.core.shapes import bridge, cut_loop, matched_loop, split_bottom_ring, tilt_section
from lpk.forms.limbs import limb

LAYER = 'join_loop'                     # the int vertex layer that tags the hole loops
# Leg loop tilt sized for a figure about 1.7 to 2.1 m tall: high over the hip, low under the buttock (metres on
# the 8-vertex hole).
LEG_TILT = {'front': 0.0, 'out': 0.035, 'back': -0.03, 'back_centre': -0.02, 'crotch_back': -0.01}
# The most a hole vertex rises, as a share of the band up to the ring above it: a vertex raised onto that
# ring would leave a band of no height there, a sliver that reads as a double crease over the hip.
TILT_ROOM = 0.5


def _layer(b):
    """The builder's join_loop layer. Raises ValueError without it: the hole loops would go untagged and
    the smoothing would find no zones."""
    layer = b.bm.verts.layers.int.get(LAYER)
    if layer is None:
        raise ValueError("this builder has no %r vertex layer to tag the hole loops in (the skin smoothing "
                         "reads it): pass vert_layers=(%r,) to the body's builder" % (LAYER, LAYER))
    return layer


def _tag(b, verts):
    layer = _layer(b)
    for v in verts:
        v[layer] = 1


def _hole_size(n, hole, form):
    """n for a limb grown out of `hole`: the hole's size when n is None. Raises ValueError when a given n
    differs from it (bridge and the weld would match only part of the loop)."""
    if n is None:
        return len(hole)
    if n != len(hole):
        raise ValueError('%s: n=%r differs from the hole size %d; pass %d, or None to take it from the hole'
                         % (form, n, len(hole), len(hole)))
    return n


def armholes(b, lower, upper, cols):
    """{'L' | 'R': hole loop}: the torso faces between ring `lower` and `upper` over the columns
    cols[side] (ring positions of the front-diagonal, side and back-diagonal vertices), cut out.
    A loop is shapes.cut_loop's, 2 * len(cols[side]) vertices: lower[cols] then upper[cols] reversed.
    With torso.ARMHOLE_COLS that is 8 vertices: 1-2 are the lower ring's side pair (the armpit),
    5-6 the upper ring's (the shoulder corner), 0, 3, 4 and 7 the front and back diagonals.
    Raises ValueError before cutting when the builder has no join_loop layer.
    Returns {'L' | 'R': hole loop of 2 * len(cols[side]) vertices}. Units: cols {'L' | 'R': ring
    positions}. The welded family is built for one density: torso.ARMHOLE_COLS on the 10-vertex rings of
    torso.trunk give the 8-vertex holes whose vertices weld_limb reads by index; other columns give holes
    weld_limb does not weld right."""
    _layer(b)
    holes = {side: cut_loop(b, lower, upper, c) for side, c in cols.items()}
    _tag(b, holes['L'] + holes['R'])
    return holes


def _room_above(v):
    """The height (m) from the bottom-ring vertex v up to the vertex of the ring above it: the vertex an edge
    leads to upward, the nearest across when there are several; infinite when no edge leads up."""
    up = [e.other_vert(v) for e in v.link_edges if e.other_vert(v).co.z > v.co.z]
    if not up:
        return float('inf')
    u = min(up, key=lambda w: ((w.co.x - v.co.x) ** 2 + (w.co.y - v.co.y) ** 2, w.co.z))
    return u.co.z - v.co.z


def leg_holes(b, ring, part, seam_z, seam_y=0.35, tilt=LEG_TILT):
    """The pelvis's open bottom ring split into two 8-vertex leg holes round a crotch seam, each
    tilted after `tilt`; see shapes.split_bottom_ring. Raises ValueError before splitting when the
    builder has no join_loop layer.
    The crotch: two new midline vertices at the height seam_z, cF in front at seam_y of the depth of
    the ring's front centre vertex F, and cB behind at seam_y of the depth of its back centre vertex
    B (y scaled about y = 0). Both holes run F, their four flank vertices front to back, B, cB, cF,
    so they share F, B, cB and cF and the legs' bridges meet along the seam F-cF-cB-B. tilt moves
    each hole's flank in z, front to back, by 'front', 'out', 'out' and 'back', and the shared B and
    cB by 'back_centre' and 'crotch_back'; F and cF stay. In body terms 'out' raises the flank
    toward the hip, and 'back' and 'back_centre' lower the seam under the buttock. A rise stops at
    TILT_ROOM of the band up to the ring above the vertex, so a short band (a hem ring just above the
    crotch ring) never collapses into a sliver. The values are metres added to z as they are, unscaled,
    whatever the figure's size: LEG_TILT holds values sized for a figure about 1.7 to 2.1 m tall.
    No thigh top overlaps the pelvis's lower rings, so they alone give its outer corners.
    Returns {'L' | 'R': 8-vertex hole loop}. Units: seam_z m, seam_y ratio, tilt m per vertex group. Built
    for the 10-vertex bottom ring of torso.trunk, the one density of the welded family: tilt moves vertices
    by their index in the holes, which on another ring count are other vertices, and weld_leg's n must
    equal the hole."""
    _layer(b)
    holes = split_bottom_ring(b, ring, part, seam_z, seam_y)
    for side in ('L', 'R'):
        for v, dz in zip(holes[side][1:5], (tilt['front'], tilt['out'], tilt['out'], tilt['back'])):
            v.co.z += min(dz, TILT_ROOM * _room_above(v)) if dz > 0 else dz
    back, crotch_back = holes['L'][5:7]                             # shared by both holes
    back.co.z += tilt['back_centre']; crotch_back.co.z += tilt['crotch_back']
    _tag(b, holes['L'] + holes['R'])
    return holes


def weld_limb(b, part, loop, path, first, second, rest, n, ref, col, bridge_col, d, out,
              socket_r=0.92, socket_in=0.03, next_gap=0.04):
    """An arm grown out of an armhole `loop` (armholes). The sleeve starts with a socket section
    `socket_in` inside the shoulder joint path[0], `first` scaled by socket_r and tilted: its top
    stays at the shoulder corner, its bottom slides down the arm to the armpit (a perpendicular
    section's inner side would lie inside the torso and fold the armpit). The next ring (`second`)
    starts `next_gap` under the armpit. Only the loop's shoulder-corner and armpit vertices weld; the
    front and back of the hole fill as a bridge from the torso's own vertices, which keeps the chest
    and back full: moving the whole loop onto the socket would sink the chest, and a shoulder corner
    left where it was would leave a flat ledge. The shoulder corner moves up to the socket's top, so a
    shoulder ring below it peaks the shoulder: raise that ring, or narrow the socket with socket_r.
    first, second, rest: limb profile entries (s, ra, rb[, opts]); the socket section sits socket_in
    before first's s (normally 0); d: down the arm; out: away from the body, perpendicular to it.
    n: the sleeve's sides, the loop's size; None takes it from the loop. A different n raises
    ValueError: the weld and the bridge would match only part of the loop.
    Returns {'R': rings, 'sock', 'nxt': the two first sections, 'top', 'bottom': the loop's welded
    vertices, 's_bot', 'verts': the join's vertices for ridge_flip}.
    Units: path m, first m (s, ra, rb[, opts]), second m (s, ra, rb[, opts]), rest m (s, ra, rb[, opts])
    entries, ref direction, d unit direction, out direction, col palette name or fn(i, j, d)
    (Builder.loft's), socket_r ratio, socket_in m, next_gap m. Loop must be an 8-vertex armholes loop:
    its vertices 5-6, the shoulder corner, move onto the socket ring; the socket ring vertices matched to
    its vertices 1-2, the armpit, move onto them; 0, 3, 4 and 7 stay and bridge to the socket ring. ra and
    rb follow limb."""
    n = _hole_size(n, loop, 'weld_limb')
    S = Vector(path[0])
    top, bottom = set(loop[5:7]), set(loop[1:3])
    s_bot = sum((v.co - S).dot(d) for v in bottom) / 2
    sock = (first[0] - socket_in,) + tuple(x * socket_r for x in first[1:3]) + tuple(first[3:4])
    nxt = (max(second[0], s_bot + next_gap),) + tuple(second[1:])
    R = limb(b, part, path, [sock, nxt] + list(rest), n, ref, col)
    tilt_section(R[0], d, out, -socket_in, s_bot)
    weld = {}
    for j, v in enumerate(matched_loop(loop, [r.co for r in R[0]])):
        if v in top:
            v.co = R[0][j].co.copy(); weld[R[0][j]] = v
        elif v in bottom:
            R[0][j].co = v.co.copy(); weld[R[0][j]] = v
    bridge(b, loop, R[0], bridge_col)
    bmesh.ops.weld_verts(b.bm, targetmap=weld)
    return {'R': R, 'sock': sock, 'nxt': nxt, 'top': top, 'bottom': bottom, 's_bot': s_bot,
            'verts': list(loop) + [v for v in R[0] if v.is_valid]}


def weld_leg(b, part, hole, path, profile, n, ref, col, bridge_col, follow=None):
    """A leg grown out of a leg hole (leg_holes): its first ring bridged to the hole. n: the leg's
    sides, the hole's size; None takes it from the hole. A different n raises ValueError: the bridge
    would match only part of the hole. follow: the first ring takes the hole's outline moved this far
    down the leg, so the leg leaves the body in line with it and the profile's shape starts at the
    next ring (thighs out of tight shorts, where a first ring of an outline of its own can sit off the
    hole and break the hem's outline). Returns (rings, the join's vertices for ridge_flip).
    Units: path m, profile m (s, ra, rb[, opts]), ref direction, col palette name or fn(i, j, d)
    (Builder.loft's), follow m. The hole is 8 vertices from leg_holes on torso.trunk; ra and rb follow
    limb."""
    n = _hole_size(n, hole, 'weld_leg')
    R = limb(b, part, path, profile, n, ref, col)
    if follow:
        d = (Vector(path[1]) - Vector(path[0])).normalized() * follow
        for v, h in zip(R[0], matched_loop(hole, [v.co for v in R[0]])):
            v.co = h.co + d
    bridge(b, hole, R[0], bridge_col)
    return R, list(hole) + list(R[0])
