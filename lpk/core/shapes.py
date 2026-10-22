"""Organic primitives on top of Builder: path and silhouette lofts, volumetric lobes, joins."""
import math
from mathutils import Vector
from mathutils.bvhtree import BVHTree


# Metres every vertex of a bridge's two loops may lie off the plane through their centre and the loops still
# count as coplanar: Blender stores coordinates as float32, about 1e-7 m of noise on a body of a few metres,
# so within this the centre that winds the faces of other bridges outward cannot tell a face's sides apart.
COPLANAR_M = 1e-6


def path_rings(path, profile):
    """Rings for Builder.loft placed along a polyline by arc length.

    path: points (e.g. shoulder, elbow, wrist). profile: [(s, ra, rb[, opts])] with s in
    metres from path[0]; s < 0 or beyond the end extrapolates along the end segments, which
    is how a limb starts buried inside the body it joins. ra and rb are the half extents Builder.loft
    lays along its a axis (its `ref` projected off the path) and its b axis (the path direction
    crossed with a); one ring per profile entry.
    Returns [(centre Vector, ra, rb[, opts])]: rings for Builder.loft."""
    pts = [Vector(p) for p in path]
    segs = [(pts[i], pts[i + 1], (pts[i + 1] - pts[i]).length) for i in range(len(pts) - 1)]
    total = sum(L for _, _, L in segs)

    def at(s):
        if s <= 0:
            a, b, L = segs[0]
            return a + (b - a).normalized() * s
        if s >= total:
            a, b, L = segs[-1]
            return b + (b - a).normalized() * (s - total)
        for a, b, L in segs:
            if s <= L:
                return a + (b - a) * (s / L)
            s -= L
    return [(at(e[0]),) + tuple(e[1:]) for e in profile]


def bvh_of(b, parts):
    """BVH over the faces of the given parts only, so joins never snap onto unrelated geometry.
    Returns mathutils BVHTree over the faces of `parts`. Side effect: sets every vertex index of b.bm and
    updates b.bm's normals."""
    unknown = [p for p in parts if p not in b.parts]
    if unknown:
        raise ValueError('bvh_of: no part named %s in this builder (parts: %s)' % (unknown, b.parts))
    b.bm.normal_update()
    ids = {b.pid(p) for p in parts}
    verts = [v.co.copy() for v in b.bm.verts]
    for i, v in enumerate(b.bm.verts):
        v.index = i
    polys = [[v.index for v in f.verts] for f in b.bm.faces if f.verts[0][b.vpart] in ids]
    return BVHTree.FromPolygons(verts, polys)


def jitter_rings(rings, n, amount, seed, skip=(0,)):
    """Deterministic per-vertex radius noise for cloth lofts of n sides (path_rings output):
    each ring's 'mult' factors are multiplied by values in [1 - amount, 1 + amount], so a tube
    of baggy cloth reads as crumpled instead of machined. Rings listed in skip stay clean. amount
    sets how far the radii stray: choose it from the garment's drawn outline and check the built
    silhouette against it.
    Returns new rings with the jittered 'mult' in an opts dict; the input is not changed. Units: rings m
    (Builder.loft sections: centre, ra, rb[, opts]), amount ratio."""
    import random
    rnd = random.Random(seed)
    out = []
    for i, r in enumerate(rings):
        opts = r[3] if len(r) > 3 and r[3] else {}
        opts = dict(opts) if isinstance(opts, dict) else {'mult': list(opts)}
        if i not in skip:
            mult = opts.get('mult') or [1.0] * n
            opts['mult'] = [m * (1 + amount * (2 * rnd.random() - 1)) for m in mult]
        out.append(tuple(r[:3]) + (opts,))
    return out


def snap_ring(ring, toward, bvh, reach=0.25, inset=0.008, b=None):
    """Join a loft onto another surface: each vertex of `ring` travels along `toward` from
    `reach` outside and lands on the first surface it meets, `inset` below it. The loft wall
    then meets the surface without a gap, without welding topology. b: the ring's builder; when
    given, each vertex whose ray misses is counted in its probe misses (miss); a vertex whose ray
    misses stays where it is either way. Units: toward direction, reach m, inset m."""
    toward = Vector(toward).normalized()
    for v in ring:
        hit, _, _, _ = bvh.ray_cast(v.co - toward * reach, toward, reach * 2)
        if hit is not None:
            v.co = hit + toward * inset
        elif b is not None:
            miss(b, 'snap_ring', b.parts[v[b.vpart]], v.co)


def cast_point(b, bvh, origin, direction, sink=0.0, distance=None, *, part=None):
    """A point seated on a surface (the base of an ear, a horn or a spike): the first hit of the ray
    from `origin` along `direction` on `bvh`, moved `sink` further along the ray, into the surface by
    the depth a buried base needs. distance: how far the ray reaches, None for no limit. Returns None
    when the ray meets nothing, and counts the miss in the probe misses of b (miss), the builder the
    point is for: a cast written inline that falls back to its origin, or to a landmark, places the
    part silently where no surface is. part: the destination part name the miss is counted for; None
    records '<unknown>', so the record stays plain JSON. A miss records the ray origin
    in model space (metres).
    Units: distance m."""
    d = Vector(direction).normalized()
    o = Vector(origin)
    hit = (bvh.ray_cast(o, d) if distance is None else bvh.ray_cast(o, d, distance))[0]
    if hit is None:
        miss(b, 'cast_point', '<unknown>' if part is None else part, o)
        return None
    return hit + d * sink


def hug_rings(rings, bvh, offset=0.006, reach=0.03):
    """Lay ring vertices onto another surface: any vertex inside it, or within `reach` above
    it, moves to the nearest surface point plus `offset` along its normal. Used where a limb
    continues over its parent (a sleeve running up over the shoulder to the collar), so the
    limb reads as a layer of the parent instead of a tube butted against it.
    Units: offset m, reach m."""
    for ring in rings:
        for v in ring:
            hit, nrm, _, dist = bvh.find_nearest(v.co)
            if hit is None:
                continue
            inside = (v.co - hit).dot(nrm) < 0
            if inside or dist < reach:
                v.co = hit + nrm * offset


# ---------------- welded joins: a limb grown out of a hole in its parent ----------------

def cut_loop(b, lower, upper, cols):
    """Delete the faces between two rings of a loft over ring positions `cols` (consecutive, in
    ring order) with their inner edges, and return the hole's boundary: lower[cols] then
    upper[cols] reversed, 2 * len(cols) vertices (three positions give a 6-vertex hole, four an
    8-vertex one, as torso.ARMHOLE_COLS do).
    Units: cols ring positions (vertex indices)."""
    import bmesh
    loop = [lower[c] for c in cols] + [upper[c] for c in reversed(cols)]
    vs = set(loop)
    bmesh.ops.delete(b.bm, geom=[f for f in b.bm.faces if all(v in vs for v in f.verts)], context='FACES')
    return loop


def split_bottom_ring(b, ring, part, seam_z, seam_y=0.35):
    """Two leg holes out of an open bottom ring with a front and a back centre vertex (an even
    loft whose sections start off the side axis): {'L': [F, four +X flank vertices front to back, B,
    cB, cF], 'R': the same on -X}. F and B are shared; cB and cF are new midline vertices at
    seam_z, `seam_y` of the centre depth from the middle, the crotch seam both legs share.
    Returns {'L': [F, +X flank vertices front to back, B, cB, cF], 'R': the same on -X}; F, B, cB and cF
    are shared. Units: seam_z m, seam_y ratio. A hole has (len(ring) + 6) / 2 vertices: 8 on the 10-vertex
    bottom ring of torso.trunk, the one density the welded family is built for (leg_holes tilts the flank
    by index, weld_leg's n must equal the hole); seam_y scales the y of F and B about y = 0, not about the
    ring centre."""
    pid = b.pid(part)
    F = min((v for v in ring if abs(v.co.x) < 1e-4), key=lambda v: v.co.y)
    B = max((v for v in ring if abs(v.co.x) < 1e-4), key=lambda v: v.co.y)
    cF = b.vert((0, F.co.y * seam_y, seam_z), pid)
    cB = b.vert((0, B.co.y * seam_y, seam_z), pid)
    holes = {}
    for side, sx in (('L', 1), ('R', -1)):
        flank = sorted((v for v in ring if v.co.x * sx > 1e-4), key=lambda v: v.co.y)
        holes[side] = [F] + flank + [B, cB, cF]
    return holes


def matched_loop(loop, pts):
    """`loop` re-ordered (cyclic shift and direction) to lie closest to the points `pts`.
    Returns a new list: `loop` cyclically shifted and possibly reversed. Units: pts m."""
    n = len(pts)
    best = None
    for seq in (loop, loop[::-1]):
        for k in range(n):
            L = seq[k:] + seq[:k]
            cost = sum((L[j].co - Vector(pts[j])).length for j in range(n))
            if best is None or cost < best[0]:
                best = (cost, L)
    return best[1]


def tilt_section(ring, d, up, s0, s_bot):
    """Slide a limb ring built at arc length s0 along the limb direction d: its top (along `up`)
    stays at s0, its bottom moves to s_bot, linearly in between. A limb hanging at an angle
    meets its parent in a tilted section; a perpendicular one has its inner side inside the
    parent.
    Units: s_bot m. The direction d must be a mathutils Vector of unit length: its length scales the slide."""
    c = sum((v.co for v in ring), Vector()) / len(ring)
    hs = [(v.co - c).dot(up) for v in ring]
    m = max(abs(h) for h in hs)
    for v, h in zip(ring, hs):
        v.co = v.co + d * ((s_bot - s0) * (1 - h / m) / 2)


def bridge(b, loop, ring, col):
    """Faces from a parent's hole loop to a limb's first ring (equal counts), matched by
    matched_loop and wound outward: away from the centre of the two loops. Corners that coincide
    are left for bmesh.ops.weld_verts: a quad with one coinciding pair becomes a triangle, one with
    two is skipped. Other quads are split on the diagonal that makes a ridge; the other one folds a
    valley between limb and body.
    Coplanar loops (every vertex within COPLANAR_M of their plane, a flat ring such as a ledge at
    the top of a trunk) have no side away from their centre. Their faces face the side the faces
    already on the loops face: each is wound against the faces that share a loop edge with it, those
    on the parent's loop deciding, the ring's when the loop has none (or as many each way), and the
    normal of `loop` in its given order when neither has any; each quad is split on its shorter
    diagonal, since neither diagonal folds."""
    n = len(ring)
    L = matched_loop(loop, [v.co for v in ring])
    hint = (sum((v.co for v in L), Vector()) + sum((v.co for v in ring), Vector())) / (2 * n)
    up = _flat_side(loop, ring)
    same = lambda p, q: (p.co - q.co).length < 1e-6
    for j in range(n):
        q = [L[j], L[(j + 1) % n], ring[(j + 1) % n], ring[j]]
        if same(q[0], q[3]) and same(q[1], q[2]):
            continue
        c = sum((v.co for v in q), Vector()) / 4
        h = hint if up is None else c - up
        if same(q[0], q[3]) or same(q[1], q[2]):
            b.face(q, col, hint=h)
            continue
        nrm = (q[2].co - q[0].co).cross(q[3].co - q[1].co)
        if nrm.dot(c - h) < 0:
            nrm = -nrm
        if up is not None:
            first = (q[2].co - q[0].co).length <= (q[3].co - q[1].co).length
        else:
            first = ((q[0].co + q[2].co) / 2 - c).dot(nrm) >= ((q[1].co + q[3].co) / 2 - c).dot(nrm)
        tris = ((q[0], q[1], q[2]), (q[0], q[2], q[3])) if first else ((q[0], q[1], q[3]), (q[1], q[2], q[3]))
        for t in tris:
            b.face(list(t), col, hint=h)


def _edge_runs(a, c):
    """+1 for each face of the mesh that runs the edge a -> c in its vertex order, -1 for each that runs
    c -> a: the faces the edge already has."""
    out = 0
    for f in a.link_faces:
        fv = list(f.verts)
        if c in fv:
            i, k = fv.index(a), fv.index(c)
            out += 1 if k == (i + 1) % len(fv) else -1 if i == (k + 1) % len(fv) else 0
    return out


def _flat_side(loop, ring):
    """The unit normal the faces of a bridge between two coplanar loops face, None when the loops are not
    coplanar: a vertex lies farther than COPLANAR_M from the plane through their centre normal to `loop`
    (by Newell's method, in its order). loop, ring: the two loops' vertices (BMVerts), as bridge takes them.

    Outward is the side the faces already on the loops face: a bridge face is wound against each face that
    shares an edge of a loop with it, so the bridge continues the surface it joins consistently. The faces on
    the parent loop's edges decide; the ring's when the parent loop has none, or as many each way; with no face
    on either loop, the normal of `loop` in its order holds."""
    normal = _newell([v.co for v in loop])
    if normal.length == 0:
        return None
    normal = normal.normalized()
    pts = [Vector(v.co) for v in list(loop) + list(ring)]
    centre = sum(pts, Vector()) / len(pts)
    if any(abs((p - centre).dot(normal)) > COPLANAR_M for p in pts):
        return None
    L, n = matched_loop(loop, [v.co for v in ring]), len(ring)
    quads = [[L[j], L[(j + 1) % n], ring[(j + 1) % n], ring[j]] for j in range(n)]
    for edge in (lambda q: (q[0], q[1]), lambda q: (q[2], q[3])):
        vote = 0
        for q in quads:
            facing = _newell([v.co for v in q]).dot(normal)
            if facing:
                # A face over q facing +normal runs q's order when q winds about normal; it runs the edge
                # against each face already on it.
                vote -= _edge_runs(*edge(q)) * (1 if facing > 0 else -1)
        if vote:
            return normal if vote > 0 else -normal
    return normal


def _newell(points):
    """The normal of a polygon by Newell's method, twice its area long, following the order of the points by
    the right-hand rule."""
    out = Vector((0.0, 0.0, 0.0))
    for p, q in zip(points, points[1:] + points[:1]):
        out = out + Vector(p).cross(Vector(q))
    return out


def _valley(e):
    # Signed fold across an edge between two faces: > 0 a valley (the second face's centre lies
    # outside the first face's plane), < 0 a ridge.
    f1, f2 = e.link_faces
    f1.normal_update(); f2.normal_update()
    s = 1.0 if (f2.calc_center_median() - f1.calc_center_median()).dot(f1.normal) > 0 else -1.0
    return s * f1.normal.angle(f2.normal, 0.0)


def ridge_flip(b, verts, parents, passes=4):
    """Triangulate the faces around a join that touch the `parents` parts and rotate each edge
    folding a valley into the other diagonal of its two triangles when that lowers the summed
    valley of the edge and its four neighbours. Moving a hole's corner onto the limb stretches the
    parent's ring edges across the join, and those fold a dent between limb and body (the back of
    the shoulder). The limb's own tube stays as built: pass the parent parts only, since rotating the
    tube's edges too can crease the limb and deepen the armpit. Run it before anything is projected
    onto the body: a rotation moves the surface, so a mark projected before it can lie under the new
    ridge and bake a hole. bmesh's rotation does not carry the colours over: a new triangle takes the
    colour of the old one under its centre, and a rotation undone gets its colours back. Returns the
    number of edges rotated."""
    import bmesh
    from mathutils.geometry import intersect_point_tri
    pids = {b.parts.index(p) for p in parents}
    vs = {v for v in verts if v.is_valid}
    region = lambda f: any(v[b.vpart] in pids for v in f.verts)

    def recolour(faces, old):
        for g in faces:
            match = [c for vset, c, _ in old if vset == set(g.verts)]
            if not match:
                m = g.calc_center_median()
                match = [c for _, c, co in old if intersect_point_tri(m, *co) is not None]
                match = match or [min(old, key=lambda o: (sum(o[2], Vector()) / 3 - m).length)[1]]
            g[b.fpal] = match[0]
    bmesh.ops.triangulate(b.bm, faces=[f for f in {f for v in vs for f in v.link_faces} if region(f)],
                          quad_method='BEAUTY', ngon_method='EAR_CLIP')
    tri = lambda e: len(e.link_faces) == 2 and all(len(f.verts) == 3 for f in e.link_faces)

    def energy(e):
        return sum(max(0.0, _valley(x)) ** 2 for x in [e] + [x for f in e.link_faces for x in f.edges if x is not e]
                   if tri(x))
    flipped = 0
    for _ in range(passes):
        changed = False
        # In index order: the flips are greedy, and a set's order follows memory addresses, which
        # would change the result from run to run.
        b.bm.edges.index_update()
        for e in sorted({e for v in vs if v.is_valid for e in v.link_edges}, key=lambda e: e.index):
            if not e.is_valid or not tri(e) or not all(region(f) for f in e.link_faces) or _valley(e) <= 0.05:
                continue
            before = energy(e)
            n_before = (e.link_faces[0].normal + e.link_faces[1].normal).normalized()
            old = [(set(f.verts), f[b.fpal], [v.co.copy() for v in f.verts]) for f in e.link_faces]
            res = bmesh.ops.rotate_edges(b.bm, edges=[e], use_ccw=False)['edges']
            if not res or len(res[0].link_faces) != 2:
                continue
            ne = res[0]
            for f in ne.link_faces:
                f.normal_update()
            if all(f.normal.dot(n_before) > 0.3 for f in ne.link_faces) and energy(ne) < before - 1e-3:
                recolour(ne.link_faces, old)
                flipped += 1; changed = True
            else:
                back = bmesh.ops.rotate_edges(b.bm, edges=[ne], use_ccw=True)['edges']
                if back:
                    recolour(back[0].link_faces, old)
        if not changed:
            break
    return flipped


def join_report(ob, parent, children, zmin=-1e9, inside=0.02, locate=False):
    """Checks for a welded join on a finished mesh object: wire and non-manifold edges overall,
    open edges inside the parent and children parts above zmin (expect only the parts' designed
    open ends), child vertices under the parent's surface and parent/child face intersections that
    share no vertex.

    A child vertex counts as under the surface when the parent's nearest face lies within `inside`
    metres and the vertex lies more than a millimetre behind it, so one on the surface does not count.
    Both are absolute search parameters, not bars, and neither scales with the body: the parent is
    open at the hole, so no closed inside test applies; a vertex deeper than the window is not seen,
    and a wider window reaches parent faces the limb does not sink into, such as a slanted face
    nearby. The intersections are exact (a BVH overlap): trust them first.

    Returns {'wire_edges', 'nonmanifold_edges', 'open_edges', 'child_verts_inside',
    'intersections'}: the counts. locate adds 'ids': for each of those keys {'verts': the vertex ids,
    'faces': the face ids}, sorted, in the object's mesh: an edge's vertices and its faces, a child
    vertex under the parent with the parent face it lies under, and both faces of an intersecting
    pair with their vertices; and 'depths': [[vertex id, metres behind the parent face]] of the child
    vertices under it, by vertex id, to 0.1 mm.
    Reads a finished object (its 'part' attribute and 'parts' property), not a Builder."""
    import bmesh
    me = ob.data
    parts = list(ob['parts']); pa = [a.value for a in me.attributes['part'].data]
    bm = bmesh.new(); bm.from_mesh(me)
    bm.faces.index_update()
    co = [v.co.copy() for v in bm.verts]
    pp = parts.index(parent); cps = {parts.index(c) for c in children}
    A = [f for f in bm.faces if all(pa[v.index] == pp for v in f.verts)]
    C = [f for f in bm.faces if any(pa[v.index] in cps for v in f.verts)]
    ta = BVHTree.FromPolygons(co, [tuple(v.index for v in f.verts) for f in A])
    tc = BVHTree.FromPolygons(co, [tuple(v.index for v in f.verts) for f in C])
    under = []
    for v in bm.verts:
        if pa[v.index] in cps and v.co.z > zmin:
            h, nr, i, dist = ta.find_nearest(v.co)
            if h is not None and dist < inside and (v.co - h).dot(nr) < -0.001:
                under.append((v, A[i], -(v.co - h).dot(nr)))
    found = {'wire_edges': [(e.verts, ()) for e in bm.edges if not e.link_faces],
             'nonmanifold_edges': [(e.verts, e.link_faces) for e in bm.edges if len(e.link_faces) > 2],
             'open_edges': [(e.verts, e.link_faces) for e in bm.edges if len(e.link_faces) == 1
                            and e.verts[0].co.z > zmin and all(pa[v.index] in cps | {pp} for v in e.verts)],
             'child_verts_inside': [((v,), (f,)) for v, f, _ in under],
             'intersections': [(tuple(A[i].verts) + tuple(C[j].verts), (A[i], C[j])) for i, j in ta.overlap(tc)
                               if not {v.index for v in A[i].verts} & {v.index for v in C[j].verts}]}
    rep = {k: len(items) for k, items in found.items()}
    if locate:
        rep['ids'] = {k: {'verts': sorted({v.index for vs, _ in items for v in vs}),
                          'faces': sorted({f.index for _, fs in items for f in fs})} for k, items in found.items()}
        rep['depths'] = sorted([v.index, round(d, 4)] for v, _, d in under)
    bm.free()
    return rep


def conform_plate(b, part, bvh, center, u, v, size_u, size_v, focus, col, side_col=None, n_u=3, n_v=3,
                  offset=0.004, thick=0.016, chamfer=0.25, jitter=0.0, seed=0):
    """Armour/panel plate that follows a curved surface. A n_u x n_v grid on the plane through
    `center` (axes u, v) is raycast toward `focus` (a point inside the body), each hit lifted by
    offset (gap) and offset + thick (top). Corner points are pulled toward the centre by
    `chamfer` so the outline reads as a cut panel, not a rectangle. jitter moves every border point
    in or out by up to that fraction of the plate size (deterministic by seed), a chipped, battered
    outline. Builds the top and the rim walls; the underside stays open against the body.
    Returns {'top': grid of top points, 'normal': grid of surface normals} for placing details.
    The rays converge on `focus`: a focus near the surface shrinks the plate, one deep inside the body
    keeps it close to the size of its grid. n_u=2, n_v=3 and chamfer=0.5 give an elongated hexagon.
    Choose offset and thick from the drawn gap and profile, and check the plate's outline in the side
    capture.
    Units: center m, u direction, v direction, size_u m, size_v m, focus m, offset m, thick m, chamfer
    ratio. A grid point whose ray misses stays on the plane, its normal back along the ray."""
    import random
    rnd = random.Random(seed)
    pid = b.pid(part)
    center = Vector(center); u = Vector(u).normalized(); v = Vector(v).normalized(); focus = Vector(focus)
    top, low, nrms = [], [], []
    for i in range(n_u + 1):
        row_t, row_l, row_n = [], [], []
        for j in range(n_v + 1):
            su, sv = i / n_u - 0.5, j / n_v - 0.5
            corner = i in (0, n_u) and j in (0, n_v)
            k = 1.0 - chamfer if corner else 1.0
            if jitter and (i in (0, n_u) or j in (0, n_v)):
                k *= 1.0 + jitter * (2 * rnd.random() - 1)
            p = center + u * (su * size_u * k) + v * (sv * size_v * k)
            d = (focus - p).normalized()
            hit, nrm, _, _ = bvh.ray_cast(p - d * 0.3, d, 1.0)
            if hit is None:
                miss(b, 'conform_plate', part, p)
                hit, nrm = p, -d
            row_t.append(b.vert(hit + nrm * (offset + thick), pid))
            row_l.append(b.vert(hit + nrm * offset, pid))
            row_n.append(nrm.copy())
        top.append(row_t); low.append(row_l); nrms.append(row_n)
    mid = sum((nrms[i][j] for i in range(n_u + 1) for j in range(n_v + 1)), Vector()).normalized()
    for i in range(n_u):
        for j in range(n_v):
            f = b.face([top[i][j], top[i + 1][j], top[i + 1][j + 1], top[i][j + 1]], col)
            f.normal_update()
            if f.normal.dot(mid) < 0:
                f.normal_flip()
    rim = [(i, 0) for i in range(n_u)] + [(n_u, j) for j in range(n_v)] + \
          [(i, n_v) for i in range(n_u, 0, -1)] + [(0, j) for j in range(n_v, 0, -1)]
    cen = sum((top[i][j].co for i in range(n_u + 1) for j in range(n_v + 1)), Vector()) / ((n_u + 1) * (n_v + 1))
    for k in range(len(rim)):
        (i0, j0), (i1, j1) = rim[k], rim[(k + 1) % len(rim)]
        b.face([top[i0][j0], top[i1][j1], low[i1][j1], low[i0][j0]], side_col or col, hint=cen - mid * thick)
    return {'top': [[x.co.copy() for x in row] for row in top], 'normal': nrms}


def miss(b, what, part, point, n=1):
    """Count on the builder `b` the `n` probes of operation `what` (a name, e.g. 'snap_ring') for the part
    named `part` that missed their surface, and keep the first missed one's point in model space (metres,
    rounded to 0.1 mm): the point the probe was cast for, or where its ray starts when it has none of its
    own. b.misses holds {what: {part: {'count', 'point'}}}, plain JSON a caller can report. Returns None;
    the geometry is not touched."""
    by_part = b.__dict__.setdefault('misses', {}).setdefault(what, {})
    if part in by_part:
        by_part[part]['count'] += n
    else:
        by_part[part] = {'count': n, 'point': [round(float(c), 4) for c in point]}


def mark(b, tool, part, width, points, kind='line', widths=None):
    """Record on the builder `b` a painted mark that tool `tool` (a name, e.g. 'surface_strip') made on the
    part named `part`: its width in metres and points along it, in the builder's space, appended to
    b.marks as {'tool', 'part', 'kind', 'width', 'points'[, 'widths']} (plain JSON; lpk.stages.texture
    reads the texel density under the points). kind: 'line' for a strip or a line, 'eye' for an eye,
    whose width is across the eye. widths: the width in metres at each point, for a line whose width
    changes along it (a tapered stripe); None when `width` holds everywhere. Returns None; the geometry
    is not touched."""
    record = {'tool': tool, 'part': part, 'kind': kind, 'width': round(float(width), 6),
              'points': [[round(float(c), 5) for c in p] for p in points]}
    if widths is not None:
        record['widths'] = [round(float(w), 6) for w in widths]
    b.__dict__.setdefault('marks', []).append(record)


def _on_surface(bvh, p, lift):
    hit, nrm, _, _ = bvh.find_nearest(Vector(p))
    if hit is None:
        return Vector(p), Vector((0, 0, 1))
    return hit + nrm * lift, nrm


def surface_strip(b, part, bvh, guide, width, col, lift=0.003, step=0.025):
    """Ribbon of `width` laid along a polyline on a surface (piping, seams, straps drawn flat).
    The guide is resampled every `step` metres and each point snapped to the nearest surface,
    so it follows curvature. Built for baking into the texture, not as final geometry.
    Units: width m, lift m."""
    pid = b.pid(part)
    pts = []
    guide = [Vector(g) for g in guide]
    for a, c in zip(guide, guide[1:]):
        n = max(1, int((c - a).length / step))
        pts += [a + (c - a) * (i / n) for i in range(n)]
    pts.append(guide[-1])
    snapped = [_on_surface(bvh, p, lift) for p in pts]
    left, right = [], []
    for i, (p, nrm) in enumerate(snapped):
        t = (snapped[min(i + 1, len(snapped) - 1)][0] - snapped[max(i - 1, 0)][0]).normalized()
        side = t.cross(nrm).normalized() * (width / 2)
        left.append(b.vert(p + side, pid)); right.append(b.vert(p - side, pid))
    for i in range(len(pts) - 1):
        f = b.face([left[i], right[i], right[i + 1], left[i + 1]], col)
        f.normal_update()
        if f.normal.dot(snapped[i][1]) < 0:
            f.normal_flip()
    mark(b, 'surface_strip', part, width, [p for p, _ in snapped])


def surface_patch(b, part, bvh, center, u, v, size_u, size_v, col, n=2, lift=0.004):
    """Flat-coloured patch (pocket, label, screen) laid onto a surface as an n x n grid snapped
    to the nearest surface points. Built for baking into the texture.
    Units: center m, u direction, v direction, size_u m, size_v m, lift m."""
    pid = b.pid(part)
    center = Vector(center); u = Vector(u).normalized(); v = Vector(v).normalized()
    grid = [[_on_surface(bvh, center + u * ((i / n - 0.5) * size_u) + v * ((j / n - 0.5) * size_v), lift)
             for j in range(n + 1)] for i in range(n + 1)]
    verts = [[b.vert(p, pid) for p, _ in row] for row in grid]
    for i in range(n):
        for j in range(n):
            f = b.face([verts[i][j], verts[i + 1][j], verts[i + 1][j + 1], verts[i][j + 1]], col)
            f.normal_update()
            if f.normal.dot(grid[i][j][1]) < 0:
                f.normal_flip()


def surface_fill(b, part, bvh, outline, col, lift=0.004, level=2):
    """Flat-coloured region of any outline laid onto a surface (a cut-away panel, a neckline):
    the outline is triangulated in its own best-fit plane, each triangle split into 4 ** level
    and every vertex snapped to the nearest surface point, so the region follows curvature.
    Built for baking into the texture, like surface_patch.
    Units: outline m, lift m."""
    from mathutils.geometry import tessellate_polygon
    pid = b.pid(part)
    pts = [Vector(p) for p in outline]
    centre = sum(pts, Vector()) / len(pts)
    nrm = Vector()
    for p, q in zip(pts, pts[1:] + pts[:1]):
        nrm += (p - centre).cross(q - centre)
    nrm.normalize()
    u = (pts[0] - centre); u = (u - nrm * u.dot(nrm)).normalized(); v = nrm.cross(u)
    flat = [Vector(((p - centre).dot(u), (p - centre).dot(v), 0.0)) for p in pts]
    tris = [[pts[i] for i in t] for t in tessellate_polygon([flat])]
    for _ in range(level):
        split = []
        for a, c, d in tris:
            ac, cd, da = (a + c) / 2, (c + d) / 2, (d + a) / 2
            split += [[a, ac, da], [ac, c, cd], [da, cd, d], [ac, cd, da]]
        tris = split
    for tri in tris:
        snapped = [_on_surface(bvh, p, lift) for p in tri]
        f = b.face([b.vert(p, pid) for p, _ in snapped], col)
        f.normal_update()
        if f.normal.dot(snapped[0][1]) < 0:
            f.normal_flip()


def profile_loft(b, part, origin, axis, up, keys, n, color, cap0='flat', cap1='flat'):
    """Loft sculpted from a side silhouette and a width curve.

    keys: [(s, top, bottom, half_width[, opts])]: s along `axis` from `origin`, top/bottom
    along `up` (the side-view outline), half_width across. Sections stay perpendicular to
    `axis`, so the outline is reproduced exactly as given. opts: Builder.loft's ring options, its a
    axis across and its b axis `up`: 'ra_bneg' is the half width of the section's lower half, below
    its mid-height, and 'rb_neg' and 'off' move the section off the given top and bottom.

    How the keys make the form seen along the axis (a head's front and three-quarter form). Each key
    is one section, a superellipse centred at its mid-height, (top + bottom) / 2, with a half height of
    (top - bottom) / 2 and its half width at that mid-height, where the section is widest; the exponent
    ('p' in opts) sets round (2) against box (higher). The loft runs straight from section to section,
    so the outline seen along the axis is the envelope of all the sections: it gives a width per
    height, not per key. Read each key's half width at its own mid-height, on the part alone, then
    check the envelope (lpk.forms.head.front_envelope does it for a head); a section the envelope hides
    shows its width only on its own drawn outline. A section is as wide below its mid-height as above
    it unless 'ra_bneg' gives its lower half a half width of its own. A mass standing out of another (a
    muzzle from a face plane, a brow over the eyes) is a width or height step from one key to a close
    neighbour. An apex cap turns the last band into a cone: how far it sits past the last key sets how
    pointed the end reads, a point with the apex well ahead of a small last key, a blunt end with a
    nearly full last key just behind it.

    Returns rings (lists of BMVerts), as Builder.loft. Units: origin m, color palette name or fn(i, j, d)
    (Builder.loft's)."""
    axis = Vector(axis).normalized(); up = Vector(up).normalized()
    across = up.cross(axis).normalized()      # loft a-axis such that b = axis x a == up
    rings = []
    for k in keys:
        s, top, bot, hw = k[:4]
        opts = dict(k[4]) if len(k) > 4 and k[4] else {}
        rings.append((Vector(origin) + axis * s + up * ((top + bot) / 2), hw, (top - bot) / 2, opts))
    return b.loft(part, rings, n, across, color, cap0=cap0, cap1=cap1, axis=axis)


def point_loft(b, part, rings, color, cap0=None, cap1=None):
    """Loft through rings given as explicit point lists (equal counts, the same winding), for
    sections no ellipse describes: a face with a brow ledge, a hood narrowing to its peak.
    cap0/cap1: None or an apex point. Faces are oriented outward as a whole (by the signed
    volume), which stays right where single bands are nearly flat, like the top of a ledge.
    color(i, j, normal), called once per face: i is the band between ring i and i + 1, cap faces get
    i = -1 (cap0) / len(rings) - 1 (cap1); j is the column, 0 to len(ring) - 1: a band face spans
    point j to point j + 1 of its two rings, a cap face is the fan triangle on that edge of its ring;
    normal is the face's own normal after the shell is oriented outward, so a cap is coloured per face
    like the bands.
    Returns rings (lists of BMVerts). Units: rings m, color palette name or fn(i, j, normal)."""
    pid = b.pid(part)
    R = [[b.vert(p, pid) for p in ring] for ring in rings]
    n = len(R[0])
    faces = []
    for i in range(len(R) - 1):
        for j in range(n):
            faces.append((i, j, b.face([R[i][j], R[i][(j + 1) % n], R[i + 1][(j + 1) % n], R[i + 1][j]], b.keys[0])))
    # Bands run the first ring's edges j -> j + 1 and the last ring's j + 1 -> j; each fan takes
    # the opposite direction, so the whole shell is wound one way before the volume check.
    for cap, ring, i, flip in ((cap0, R[0], -1, True), (cap1, R[-1], len(R) - 1, False)):
        if cap is not None:
            a = b.vert(cap, pid)
            for j in range(n):
                edge = [ring[(j + 1) % n], ring[j]] if flip else [ring[j], ring[(j + 1) % n]]
                faces.append((i, j, b.face(edge + [a], b.keys[0])))
    centre = sum((v.co for ring in R for v in ring), Vector()) / (len(R) * n)
    vol = 0.0
    for _, _, f in faces:
        f.normal_update()
        vol += (f.calc_center_median() - centre).dot(f.normal) * f.calc_area()
    for i, j, f in faces:
        if vol < 0:
            f.normal_flip()
        f[b.fpal] = b.keys.index(color(i, j, f.normal) if callable(color) else color)
    return R


def lobe(b, part, base, tip, width, thick, front, col, inner_col=None, n=8, cup=0.35,
         profile=((0.0, 0.75, 0.9), (0.35, 1.0, 1.0), (0.72, 0.68, 0.8)), tip_col=None):
    """Thick pointed lobe (ear, fin, leaf) from `base` to an apex at `tip`.

    width: the section's half size across the cupped face, along the lobe's axis (base to tip)
    crossed with `front`; thick: its half size through the lobe, along `front`. front: the side that
    gets the cupped, inner_col face, the direction the opening faces: for an ear, the way its opening
    faces in the drawing, between the front and the side when both views show the opening. A front
    along the lobe's axis leaves no direction across it; turned toward the axis, the lobe's width
    turns with it (a side ear whose front points along the side shows the front view its thickness,
    not its width: a thin vertical spike). profile: (t along base->tip, width scale, thickness scale).
    cup: the radius scale of the `front` side's vertices from the second ring on; under about 0.4
    (the default included) the inner side is concave.
    tip_col colours the apex cone past the last profile ring (a fox ear's dark tip).
    The base is left open to be buried in the parent shape.
    Returns rings (lists of BMVerts). Units: cup ratio, profile (ratio, ratio, ratio)."""
    base = Vector(base); tip = Vector(tip); axis = (tip - base).normalized()
    front = Vector(front).normalized()
    across = axis.cross(front).normalized()        # loft a-axis; b = t x a then points away from `front`

    def mult_for(i):
        if i == 0:
            return None
        m = []
        for j in range(n):
            th = math.pi / n + 2 * math.pi * j / n
            m.append(cup if math.sin(th) < -0.5 else 1.0)   # sin < 0 is the `front` side
        return m
    rings = []
    for i, (t, ws, ts) in enumerate(profile):
        m = mult_for(i)
        rings.append((base + (tip - base) * t, width * ws, thick * ts, {'mult': m} if m else None))

    def color(i, j, d):
        return inner_col if (inner_col and i >= 1 and d.dot(front) > 0.5) else col
    return b.loft(part, rings, n, across, color, cap1=tip, col1=tip_col or col)


def star_prism(b, part, center, normal, up, r_out, r_in, depth, rim_col, face_col=None, inner=0.62, recess=0.4,
               points=5):
    """Star-shaped plate (badge, buckle, star glasses) standing `depth` off `center` along
    `normal`, one point toward `up`. With face_col the face is a rim of rim_col around a recessed
    inner star of face_col (a lens in a frame); otherwise a flat face. The back stays open
    against the surface it sits on. 50 triangles with five points and a lens.
    Units: center m, normal direction, up direction, r_out m, r_in m, depth m, inner ratio, recess ratio."""
    pid = b.pid(part)
    c = Vector(center); n = Vector(normal).normalized()
    up = Vector(up); up = (up - n * up.dot(n)).normalized(); side = up.cross(n)
    outline = []
    for k in range(points * 2):
        r = r_out if k % 2 == 0 else r_in
        a = math.pi * k / points
        outline.append(up * (math.cos(a) * r) + side * (math.sin(a) * r))
    m = len(outline)
    front = [b.vert(c + n * depth + o, pid) for o in outline]
    back = [b.vert(c + o, pid) for o in outline]
    for k in range(m):
        b.face([front[k], back[k], back[(k + 1) % m], front[(k + 1) % m]], rim_col, hint=c + n * (depth / 2))
    if face_col:
        lens = [b.vert(c + n * (depth * (1 - recess)) + o * inner, pid) for o in outline]
        for k in range(m):
            b.face([front[k], front[(k + 1) % m], lens[(k + 1) % m], lens[k]], rim_col, hint=c - n)
        hub = b.vert(c + n * (depth * (1 - recess)), pid)
        for k in range(m):
            b.face([lens[k], lens[(k + 1) % m], hub], face_col, hint=c - n)
    else:
        hub = b.vert(c + n * depth, pid)
        for k in range(m):
            b.face([front[k], front[(k + 1) % m], hub], rim_col, hint=c - n)


def surface_star(b, part, bvh, center, u, v, r_out, r_in, col, points=5, lift=0.004):
    """Flat star decal laid onto a surface: the outline in the (u, v) plane, one point toward v,
    each vertex snapped to the nearest surface point and fanned from the snapped centre. Built
    for baking into the texture, like surface_patch.
    Units: center m, u direction, v direction, r_out m, r_in m, lift m."""
    pid = b.pid(part)
    center = Vector(center); u = Vector(u).normalized(); v = Vector(v).normalized()
    hub, hub_n = _on_surface(bvh, center, lift)
    rim = []
    for k in range(points * 2):
        r = r_out if k % 2 == 0 else r_in
        a = math.pi * k / points
        rim.append(b.vert(_on_surface(bvh, center + v * (math.cos(a) * r) + u * (math.sin(a) * r), lift)[0], pid))
    hv = b.vert(hub, pid)
    for k in range(len(rim)):
        f = b.face([rim[k], rim[(k + 1) % len(rim)], hv], col)
        f.normal_update()
        if f.normal.dot(hub_n) < 0:
            f.normal_flip()


def surface_blotches(b, part, bvh, center, u, v, size_u, size_v, count, r, cols, seed=1, lift=0.004, sides=6):
    """Irregular flat blotches (burn-scar tissue, scuffs, grime) scattered over an ellipse of
    size_u x size_v around `center` in the (u, v) plane: each is a jittered n-gon of radius ~r fanned
    from its centre, every vertex snapped to the nearest surface point. Colours cycle through `cols`
    and each blotch sits a little higher than the previous one, so overlaps stay clean in the bake.
    Built for baking into the texture, like surface_patch.
    Units: center m, u direction, v direction, size_u m, size_v m, r m, lift m. The sizes size_u and size_v
    are the full axes of the scatter ellipse; blotch k sits 0.3 mm * k above lift."""
    import random
    rnd = random.Random(seed)
    pid = b.pid(part)
    center = Vector(center); u = Vector(u).normalized(); v = Vector(v).normalized()
    for k in range(count):
        a, rr = 2 * math.pi * rnd.random(), math.sqrt(rnd.random())
        c = center + u * (math.cos(a) * rr * size_u / 2) + v * (math.sin(a) * rr * size_v / 2)
        rad = r * (0.6 + 0.8 * rnd.random())
        h = lift + 0.0003 * k
        hub, hub_n = _on_surface(bvh, c, h)
        rim = []
        for j in range(sides):
            t = 2 * math.pi * (j + 0.4 * rnd.random()) / sides
            q = c + (u * math.cos(t) + v * math.sin(t)) * (rad * (0.55 + 0.6 * rnd.random()))
            rim.append(b.vert(_on_surface(bvh, q, h)[0], pid))
        hv = b.vert(hub, pid)
        col = cols[k % len(cols)]
        for j in range(sides):
            f = b.face([rim[j], rim[(j + 1) % sides], hv], col)
            f.normal_update()
            if f.normal.dot(hub_n) < 0:
                f.normal_flip()


def _breadth(points, d):
    """The narrowest breadth of a point set seen along d: the least distance between two parallel lines
    enclosing its projection, which lies along an edge of the projection's convex hull."""
    ref = Vector((1, 0, 0)) if abs(d[0]) < 0.9 else Vector((0, 1, 0))
    u = (ref - d * ref.dot(d)).normalized(); v = d.cross(u)
    pts = sorted({(round(p.dot(u), 9), round(p.dot(v), 9)) for p in points})
    if len(pts) < 3:
        return 0.0
    turn = lambda o, p, q: (p[0] - o[0]) * (q[1] - o[1]) - (p[1] - o[1]) * (q[0] - o[0])
    hull = []
    for seq in (pts, pts[::-1]):
        half = []
        for q in seq:
            while len(half) >= 2 and turn(half[-2], half[-1], q) <= 0:
                half.pop()
            half.append(q)
        hull += half[:-1]
    best = None
    for i, p in enumerate(hull):
        q = hull[(i + 1) % len(hull)]
        ex, ey = q[0] - p[0], q[1] - p[1]
        n = math.hypot(ex, ey)
        far = max(abs(ex * (r[1] - p[1]) - ey * (r[0] - p[0])) for r in hull) / n
        best = far if best is None else min(best, far)
    return best or 0.0


def fan_decal(b, part, bvh, outline, direction, col, lift=0.0015, dome=0.0, rings=1, centre=None, mark=None):
    """Flat-coloured polygon built into the mesh itself on a curved surface (a big eye wrapping round
    a head, a light on a suit): each outline point is cast along `direction` onto `bvh` and lifted by
    `lift`, and the polygon is fanned from its centre through `rings` intermediate rings, so it follows
    the curvature where a single n-gon decal is triangulated across the bend and cuts into the surface.
    dome lifts the centre by that much more than the rim (a glossy, bulging eye).
    n * (2 * rings + 1) triangles for n outline points. Each point casts from 0.5 m behind itself
    (against `direction`) over 1 m: keep outlines within that of the surface they land on. dome is
    metres whatever the head's size: judge it in the profile capture against the drawn eye.
    mark records the decal for the bake's texel readings (mark; lpk.stages.texture): 'eye' as an eye
    at its cast centre, as wide as its cast rim's widest extent across `direction`; 'line' as a line
    over its cast rim points, as wide as the rim's narrowest breadth seen along `direction` (a mouth,
    a brow, a stripe drawn as an outline). None records nothing: an unmarked decal is not known to
    the texel readings. The forms that draw an eye with this record their own mark (eyes.traced_eye,
    eyes.bevel_eye) and leave mark None. Raises ValueError for another mark.
    A point whose ray misses snaps to the nearest surface point instead."""
    if mark not in (None, 'eye', 'line'):
        raise ValueError("fan_decal: mark must be None, 'eye' or 'line', got %r" % (mark,))
    pid = b.pid(part)
    d = Vector(direction).normalized()
    pts = [Vector(p) for p in outline]
    c = Vector(centre) if centre is not None else sum(pts, Vector()) / len(pts)

    def cast(p, extra):
        hit, nrm, _, _ = bvh.ray_cast(p - d * 0.5, d, 1.0)
        if hit is None:
            miss(b, 'fan_decal', part, p)
            hit, nrm, _, _ = bvh.find_nearest(p)
        return b.vert(hit + nrm * (lift + extra), pid), nrm
    hub, hub_n = cast(c, dome)
    R = []
    for k in range(1, rings + 2):
        f = k / (rings + 1)
        R.append([cast(c + (p - c) * f, dome * (1 - f * f)) for p in pts])
    n = len(pts)

    def add(vs):
        fc = b.face([v for v, _ in vs], col)
        fc.normal_update()
        if fc.normal.dot(sum((nm for _, nm in vs), Vector())) < 0:
            fc.normal_flip()
    for j in range(n):
        add([R[0][j], R[0][(j + 1) % n], (hub, hub_n)])
    for k in range(rings):
        for j in range(n):
            add([R[k][j], R[k][(j + 1) % n], R[k + 1][(j + 1) % n], R[k + 1][j]])
    if mark is not None:
        _mark_decal(b, part, mark, [v.co.copy() for v, _ in R[-1]], hub.co.copy(), d)


def _mark_decal(b, part, kind, rim, hub, d):
    """fan_decal's mark of kind 'eye' or 'line' (its own parameter `mark` hides the recorder there): an eye
    at `hub`, as wide as the rim's widest extent across the unit direction d; a line over the rim points,
    as wide as the rim's narrowest breadth seen along d."""
    if kind == 'eye':
        flat = [p - d * p.dot(d) for p in rim]
        mark(b, 'fan_decal', part, max((p - q).length for p in flat for q in flat), [hub], kind='eye')
    else:
        mark(b, 'fan_decal', part, _breadth(rim, d), rim)


def axis_fill(b, part, bvh, a, c, ref, outline, col, lift=0.004, level=2, reach=0.5):
    """Flat-coloured region wrapped round a body segment (a suit's side panel round a torso, a pad
    over a shoulder, a panel down the outer forearm). outline: (azimuth in degrees, s) points, s in
    metres along a -> c and the azimuth about that axis from `ref` (0) toward axis x ref (90). The
    outline is triangulated in that parameter plane, each triangle split into 4 ** level, and every
    vertex is cast from `reach` outside toward the axis onto the first (outermost) surface of `bvh`,
    so a region can run round the side, which a fill in its best-fit plane (surface_fill) cannot.
    Built for baking into the texture, like surface_patch. A point read off a front view at x, on a
    segment of half depth D there, lies at an azimuth of about degrees(atan2(x, D)) from the front.
    Units: ref direction, lift m, reach m."""
    from mathutils.geometry import tessellate_polygon
    pid = b.pid(part)
    a = Vector(a); c = Vector(c); ax = (c - a).normalized()
    r0 = Vector(ref); r0 = (r0 - ax * r0.dot(ax)).normalized(); r1 = ax.cross(r0)
    flat = [Vector((math.radians(az) * 0.1, s, 0.0)) for az, s in outline]
    tris = [[flat[i] for i in t] for t in tessellate_polygon([flat])]
    for _ in range(level):
        split = []
        for p, q, r in tris:
            pq, qr, rp = (p + q) / 2, (q + r) / 2, (r + p) / 2
            split += [[p, pq, rp], [pq, q, qr], [rp, qr, r], [pq, qr, rp]]
        tris = split
    cache = {}

    def cast(p):
        key = (round(p.x, 7), round(p.y, 7))
        if key not in cache:
            th = p.x * 10.0
            dr = r0 * math.cos(th) + r1 * math.sin(th)
            o = a + ax * p.y + dr * reach
            hit, nrm, _, _ = bvh.ray_cast(o, -dr, reach)
            if hit is None:
                miss(b, 'axis_fill', part, o)
            cache[key] = None if hit is None else (b.vert(hit + nrm * lift, pid), nrm)
        return cache[key]
    for tri in tris:
        vs = [cast(p) for p in tri]
        if any(v is None for v in vs):
            continue
        f = b.face([v for v, _ in vs], col)
        f.normal_update()
        if f.normal.dot(sum((nm for _, nm in vs), Vector())) < 0:
            f.normal_flip()


def polygon_rings(rings, n, drop, ref=Vector((1, 0, 0))):
    """Explicit point rings (for point_loft) of Builder.loft's n-gon sections: the same apothem
    radii, per-vertex `mult` and transported frame, with the vertex indices in `drop` removed. An
    n-gon's outline on fewer sides: a 10-gon without its front and back centre vertices gives 8
    sides whose front and back faces span two of the 10-gon's: the 10-gon's angular layout on fewer
    triangles, where an even 8-gon is another outline. Compare the built silhouette and shading with
    the drawing, and the triangle cost. Not for a welded trunk: torso.ARMHOLE_COLS and
    split_bottom_ring index the full 10-gon.
    Returns point rings (lists of Vectors) for point_loft. Units: rings m (centre, ra, rb[, mult]), drop
    vertex indices, ref direction. A ring's fourth entry is a plain list of per-vertex multipliers;
    Builder.loft's opts dict is not read here."""
    cs = [Vector(r[0]) for r in rings]
    k = len(cs)
    ts = [(cs[min(i + 1, k - 1)] - cs[max(i - 1, 0)]).normalized() for i in range(k)]
    A = [(ref - ts[0] * ref.dot(ts[0])).normalized()]
    for i in range(1, k):
        a = ts[i - 1].rotation_difference(ts[i]) @ A[-1]
        A.append((a - ts[i] * a.dot(ts[i])).normalized())
    sc = 1.0 / math.cos(math.pi / n)
    out = []
    for i, r in enumerate(rings):
        ra, rb = r[1], r[2]
        mult = r[3] if len(r) > 3 and r[3] else [1.0] * n
        a = A[i]; b = ts[i].cross(a)
        ring = []
        for j in range(n):
            if j in drop:
                continue
            th = math.pi / n + 2 * math.pi * j / n
            ring.append(cs[i] + (a * (math.cos(th) * ra) + b * (math.sin(th) * rb)) * sc * mult[j])
        out.append(ring)
    return out


def lift_rings(rings, lift, apexes=(), centre=None):
    """Push every ring vertex `lift` out from its ring's centre (and each apex vertex out from
    `centre`): a copy of a loft turned into a colour source lying just above the mesh.
    Units: lift m, centre m."""
    for ring in rings:
        c = sum((v.co for v in ring), Vector()) / len(ring)
        for v in ring:
            v.co += (v.co - c).normalized() * lift
    for v in apexes:
        v.co += (v.co - Vector(centre)).normalized() * lift


def band_source(b, part, R, n_bands, tip, bands, tip_col, lift=0.003):
    """Colour source for a banded loft lying on the loft itself: its rings R plus a ring
    interpolated at every band boundary (n_bands equal bands by arc length), so the boundaries
    fall on the loft's texel rows whatever its ring count. Bands alternate `bands` from the root;
    the tip cone takes tip_col. R: the loft's rings from the root to the tip, each a list of the
    BMVerts a loft returns or of their positions; tip: the apex the tip cone closes on.
    Units: tip m, lift m. Only bands[0] and bands[1] are used, alternating."""
    pid = b.pid(part)
    rings = [[Vector(getattr(v, 'co', v)) for v in r] for r in R]
    n = len(rings[0])
    cent = [sum(r, Vector()) / n for r in rings]
    s = [0.0]
    for a, c in zip(cent, cent[1:]):
        s.append(s[-1] + (c - a).length)
    total = s[-1]
    cuts = [total * k / n_bands for k in range(1, n_bands)]
    seq = [(0.0, rings[0])]
    for m in range(len(rings) - 1):
        for cut in cuts:
            if s[m] < cut < s[m + 1]:
                t = (cut - s[m]) / (s[m + 1] - s[m])
                seq.append((cut, [p.lerp(q, t) for p, q in zip(rings[m], rings[m + 1])]))
        seq.append((s[m + 1], rings[m + 1]))

    def lifted(ring):
        c = sum(ring, Vector()) / n
        return [b.vert(p + (p - c).normalized() * lift, pid) for p in ring]
    vs = [lifted(r) for _, r in seq]
    for i in range(len(seq) - 1):
        band = min(int((seq[i][0] + seq[i + 1][0]) / 2 / total * n_bands), n_bands - 1)
        A, B = vs[i], vs[i + 1]
        for j in range(n):
            b.face([A[j], A[(j + 1) % n], B[(j + 1) % n], B[j]], bands[band % 2])
    apex = b.vert(Vector(tip) + (Vector(tip) - cent[-1]).normalized() * lift, pid)
    for j in range(n):
        b.face([vs[-1][j], vs[-1][(j + 1) % n], apex], tip_col)


def ring_band(b, part, rings, col, half, lift=0.003):
    """Colour band round a loft at one of its rings: quads from `half` toward the ring above to
    `half` toward the ring below (rings: above, middle, below, each a list of the BMVerts a loft
    returns or of their positions), lifted off the loft. Follows the loft's own facets, where a
    ribbon snapped to the surface twists at corners.
    Units: half m, lift m."""
    above, mid, below = ([Vector(getattr(v, 'co', v)) for v in r] for r in rings)
    n = len(mid)
    c = sum(mid, Vector()) / n
    pid = b.pid(part)

    def toward(other):
        k = half / ((sum(other, Vector()) / n) - c).length
        return [b.vert(p.lerp(q, k) + (p.lerp(q, k) - c).normalized() * lift, pid) for p, q in zip(mid, other)]
    top, bot = toward(above), toward(below)
    for j in range(n):
        b.face([top[j], top[(j + 1) % n], bot[(j + 1) % n], bot[j]], col)
    mark(b, 'ring_band', part, 2 * half, mid)


def ray_grid(b, part, bvh, centre, axis, front, up, angles, offsets, col, lift=0.005):
    """Patch laid as a grid of rays onto the outermost surface of `bvh`: rows at `angles` (degrees
    from `front` toward `up`, round `axis` through `centre`), columns at `offsets` along `axis`.
    Every vertex is a first hit from outside lifted by `lift`; nearest-point snapping instead
    falls onto a surface lying under the outer one (a torso under a hugged yoke). The faces run as
    chords between the hits, so over a ridge a coarse grid's flat faces dip under the surface and bake
    a hole there: refine `angles` and `offsets` until the faces stay above the ridge, and check the
    bake's coverage.
    Units: centre m, axis direction, offsets m, lift m. Rays start 0.4 m out from the axis: the surface
    must lie within that."""
    pid = b.pid(part)
    centre = Vector(centre); axis = Vector(axis).normalized(); front = Vector(front); up = Vector(up)
    rows = []
    for ang in angles:
        dv = (front * math.cos(math.radians(ang)) + up * math.sin(math.radians(ang))).normalized()
        row = []
        for o in offsets:
            start = centre + axis * o + dv * 0.4
            hit, nrm, _, _ = bvh.ray_cast(start, -dv)
            if hit is None:
                miss(b, 'ray_grid', part, start)
            row.append(None if hit is None else b.vert(hit + nrm * lift, pid))
        rows.append(row)
    for r0, r1 in zip(rows, rows[1:]):
        for j in range(len(offsets) - 1):
            q = [r0[j], r0[j + 1], r1[j + 1], r1[j]]
            if all(q):
                b.face(q, col, hint=centre)
