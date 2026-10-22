"""Geometry checks for what pictures and landmark numbers let through: whether the front silhouette
shows background between a limb and the body (limb_separation), the size of the welded hole loops and
the parts they join (armhole_report), whether a shell clears the parts it covers (shell_clearance) and
whether the parts mirror across the midline (mirror_report).

The checks read the object's mesh data in world space (the rest shape: an armature pose is not
applied), except shell_clearance and mirror_report, which read it in the object's own space, the
space a build places geometry in; all are deterministic and return plain numbers and dicts. A face
belongs to the part most of its vertices carry, the first vertex breaking a tie, so a bridge triangle
of a welded join goes to the side that holds two of its three vertices. Only the readers import bpy;
the numpy helpers run on the host as well."""
import itertools
import math

import numpy as np

# Metres per pixel separation samples the silhouettes at when the caller gives none; a drawing's own
# metres per pixel asks whether the drawing could show the gap.
SEPARATION_PX = 0.005
# How shell_clearance casts its rays: 'centre' from a point inside what the shell covers through each
# covered vertex (a cap, a hood, a helmet), 'normal' along each covered vertex's normal (a plate or a
# collar lying on a surface).
SHELL_RAYS = ('centre', 'normal')
# Metres by which two positions of a mesh may differ from what they would be exactly: positions are
# stored as float32, whose step is about 1.2e-7 m at 1-2 m from the origin, and the tests here run in
# float64, so a reading this small is the noise of the storage (a covered vertex this far outside its
# shell still lies on it).
POSITION_NOISE = 1e-06
# Metres within which a vertex's mirror image must meet another vertex for the two to be twins. It is
# not a numeric noise but a coupling: the smooth bake's mirror (lpk.stages.rig._mirror) copies a vertex's
# weights to the vertex within this distance of its mirror image, so mirror_report's twins are exactly the
# vertices that mirror couples, and a pair reads mirrored when the bake mirrors its weights. A
# pair off mirror by less than this distance reads mirrored; one off by more keeps its own weights there.
MIRROR_TOLERANCE = 1e-04
# Points per block of the ray tests: a block's arrays hold this many rows against every triangle.
_RAY_BLOCK = 256


def read_mesh(obj_name, world=True):
    """A mesh object's data for the checks: (the object, vertex positions (N, 3) float64 in world space,
    or in the object's own space when world is False, vertex part ids (N,) of its 'part' attribute,
    triangles (T, 3) of its polygons fanned in polygon order (fan_triangles), part names of its 'parts'
    property). The positions are read as Blender stores them, float32, and widened. Needs Blender."""
    import bpy
    ob = bpy.data.objects[obj_name]
    me = ob.data
    n, nl, nf = len(me.vertices), len(me.loops), len(me.polygons)
    co = np.empty(n * 3, np.float32)
    me.vertices.foreach_get('co', co)
    co = co.reshape(n, 3).astype(np.float64)
    if world:
        M = np.array(ob.matrix_world, np.float64)
        co = co @ M[:3, :3].T + M[:3, 3]
    vpart = np.empty(n, np.int32)
    me.attributes['part'].data.foreach_get('value', vpart)
    loop_vert = np.empty(nl, np.int32)
    me.loops.foreach_get('vertex_index', loop_vert)
    start, total = np.empty(nf, np.int32), np.empty(nf, np.int32)
    me.polygons.foreach_get('loop_start', start)
    me.polygons.foreach_get('loop_total', total)
    return ob, co, vpart, fan_triangles(start, total, loop_vert), list(ob['parts'])


def _ids(names, parts):
    parts = [parts] if isinstance(parts, str) else list(parts)
    missing = [p for p in parts if p not in names]
    if missing:
        raise KeyError('parts %s not on the object; it has %s' % (missing, names))
    return [names.index(p) for p in parts]


def fan_triangles(loop_start, loop_total, loop_vert):
    """(T, 3) vertex triangles of polygons given as loop ranges: polygon k is fanned from its first
    corner, in polygon order (a triangulated mesh comes back face for face)."""
    loop_start = np.asarray(loop_start, np.int64)
    loop_total = np.asarray(loop_total, np.int64)
    loop_vert = np.asarray(loop_vert, np.int64)
    n = np.maximum(loop_total - 2, 0)
    poly = np.repeat(np.arange(len(n)), n)
    j = np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n) + 1
    s = loop_start[poly]
    return np.stack([loop_vert[s], loop_vert[s + j], loop_vert[s + j + 1]], axis=1)


def face_parts(vpart, tris):
    """The part of each triangle: the part two or three of its vertices share, else its first vertex's."""
    p = np.asarray(vpart)[np.asarray(tris)]
    return np.where(p[:, 1] == p[:, 2], p[:, 1], p[:, 0])


def rasterize(tris, u0, v0, px, shape):
    """Boolean coverage (rows, cols) of 2D triangles: pixel (r, c) has its centre at
    (u0 + (c + 0.5) px, v0 + (r + 0.5) px), so row 0 is the lowest v. A pixel is covered when its
    centre lies in a triangle, edges included (cover, on the triangles in pixel units), so triangles
    sharing an edge leave no crack. Degenerate triangles cover nothing.
    tris: (T, 3, 2) in the same units as u0, v0 and px."""
    t = np.asarray(tris, np.float64).reshape(-1, 3, 2)
    return cover(np.stack([(t[..., 0] - u0) / px - 0.5, (t[..., 1] - v0) / px - 0.5], axis=-1), shape)


def cover(tris, shape):
    """(H, W) bools: the pixels whose centres (x, y), on whole numbers, lie in one of the triangles
    (T, 3, 2) of x along a row and y down the rows, edges included (a 1e-9 pixel tolerance), so
    triangles sharing an edge leave no crack; degenerate triangles cover nothing. The kit's rasterizer
    (rasterize gives it in other units), scanned a row at a time for all triangles together: a row
    crosses a triangle between its long side (top to bottom corner) and the short side on that row (top
    to middle corner above the middle one, middle to bottom below)."""
    H, W = shape
    t = np.asarray(tris, np.float64).reshape(-1, 3, 2)
    area = ((t[:, 1, 0] - t[:, 0, 0]) * (t[:, 2, 1] - t[:, 0, 1])
            - (t[:, 1, 1] - t[:, 0, 1]) * (t[:, 2, 0] - t[:, 0, 0]))
    t = t[np.abs(area) >= 1e-18]
    t = np.take_along_axis(t, np.argsort(t[:, :, 1], axis=1, kind='stable')[:, :, None], axis=1)
    (x0, y0), (x1, y1), (x2, y2) = (t[:, k].T for k in range(3))
    eps = 1e-9
    r0 = np.maximum(np.ceil(y0 - eps), 0).astype(np.int64)
    r1 = np.minimum(np.floor(y2 + eps), H - 1).astype(np.int64)
    n = np.maximum(r1 - r0 + 1, 0)
    total = int(n.sum())
    if not total:
        return np.zeros((H, W), bool)
    i = np.repeat(np.arange(len(n)), n)
    r = (r0[i] + np.arange(total) - np.repeat(np.cumsum(n) - n, n)).astype(np.float64)

    def along(xa, ya, xb, yb):
        dy = yb - ya
        f = np.clip((r - ya) / np.where(dy > 0, dy, 1.0), 0.0, 1.0)
        return xa + f * (xb - xa)

    x0, y0, x1, y1, x2, y2 = x0[i], y0[i], x1[i], y1[i], x2[i], y2[i]
    xl = along(x0, y0, x2, y2)
    xs = np.where(r < y1, along(x0, y0, x1, y1), along(x1, y1, x2, y2))
    c0 = np.maximum(np.ceil(np.minimum(xl, xs) - eps), 0).astype(np.int64)
    c1 = np.minimum(np.floor(np.maximum(xl, xs) + eps), W - 1).astype(np.int64)
    ok = c0 <= c1
    row = r[ok].astype(np.int64) * (W + 1)
    D = (np.bincount(row + c0[ok], minlength=H * (W + 1))
         - np.bincount(row + c1[ok] + 1, minlength=H * (W + 1))).reshape(H, W + 1)
    return np.cumsum(D, axis=1)[:, :W] > 0


def separation(limb_tris, body_tris, px=SEPARATION_PX, z_range=None):
    """Where two front silhouettes touch, row by row.

    limb_tris, body_tris: (T, 3, 2) triangles projected on the front plane as (x, z) in metres. Both
    are rasterised at px metres per pixel over their common bounds plus one pixel, on a grid whose
    lines lie at whole multiples of px from the model's axes, so a limb and its mirror twin are sampled
    at the same phase: a grid anchored at each call's own bounds can sample them at different phases and
    resolve a gap of a pixel or two on one side only. A row touches when a limb pixel overlaps or
    neighbours a body pixel, i.e. no background pixel separates them there: a gap reads as touching
    until it holds a whole background pixel, which takes one to two pixels of width. z_range: (z_lo,
    z_hi) to keep only the rows whose centres lie in it.

    Returns {'span': [z_lo, z_hi] of the touching rows or None, 'length': z_hi - z_lo, 'rows': the
    number of touching rows, 'runs': [[z_lo, z_hi], ...] the contiguous touching stretches, top
    first}; z values are row edges in metres."""
    lt = np.asarray(limb_tris, np.float64).reshape(-1, 3, 2)
    bt = np.asarray(body_tris, np.float64).reshape(-1, 3, 2)
    if not len(lt) or not len(bt):
        raise ValueError('no %s triangles' % ('limb' if not len(lt) else 'body'))
    allp = np.concatenate([lt, bt]).reshape(-1, 2)
    lo = np.floor(allp.min(axis=0) / px) - 1
    hi = np.ceil(allp.max(axis=0) / px) + 1
    u0, v0 = lo * px
    shape = (int(hi[1] - lo[1]), int(hi[0] - lo[0]))
    L = rasterize(lt, u0, v0, px, shape)
    B = rasterize(bt, u0, v0, px, shape)
    touch = (L & B).any(axis=1) | (L[:, :-1] & B[:, 1:]).any(axis=1) | (B[:, :-1] & L[:, 1:]).any(axis=1)
    if z_range is not None:
        zc = v0 + (np.arange(shape[0]) + 0.5) * px
        touch &= (zc >= z_range[0]) & (zc <= z_range[1])
    rows = np.flatnonzero(touch)
    runs = []
    for r in rows:
        if runs and runs[-1][1] == r - 1:
            runs[-1][1] = r
        else:
            runs.append([r, r])
    runs = [[round(float(v0 + a * px), 4), round(float(v0 + (b + 1) * px), 4)] for a, b in reversed(runs)]
    span = [min(r[0] for r in runs), max(r[1] for r in runs)] if runs else None
    return {'span': span, 'length': round(span[1] - span[0], 4) if span else 0.0, 'rows': int(len(rows)),
            'runs': runs}


def limb_separation(obj_name, limb_parts, body_parts, px=SEPARATION_PX, z_range=None):
    """Whether the front view shows background between a limb and the body, row by row (separation).

    obj_name: the mesh object; limb_parts: the parts of one limb (one side per call: a row counts as
    touching when any limb part touches the body); body_parts: the parts it must stand clear of;
    px: metres per pixel, the resolution the answer holds at (pass the drawing's to ask whether the
    drawing could show the gap); z_range: (z_lo, z_hi) metres, e.g. from the armpit down, since the
    limb's root always touches. The silhouettes are orthographic projections onto the XZ plane, every
    face filled. Returns separation's dict: a long touching span under the armpit is an arm drawn free
    of the body but built against it."""
    ob, co, vpart, tris, names = read_mesh(obj_name)
    fp = face_parts(vpart, tris)
    uv = co[:, [0, 2]]
    lt = tris[np.isin(fp, _ids(names, limb_parts))]
    bt = tris[np.isin(fp, _ids(names, body_parts))]
    return separation(uv[lt], uv[bt], px, z_range)


def join_loops(edges, vpart, tagged, names):
    """The tagged hole loops of a mesh, keyed by the part that grows out of them.

    edges: (E, 2) vertex pairs; vpart: vertex part ids; tagged: per-vertex flags (the join_loop
    layer); names: part names by id. A loop is the tagged vertices next to a vertex of one child part,
    a part that no tagged vertex belongs to (so neighbouring hole parts are not mistaken for
    children); it needs three vertices or more. Tagged vertices next to no child (a hole not filled
    yet) form loops by connectivity, keyed 'loop0', 'loop1', ... in order of their lowest vertex; two
    unfilled holes that share vertices stay one loop. Returns {key: sorted vertex ids}, children in
    part-id order first."""
    E = np.asarray(edges, np.int64).reshape(-1, 2)
    vp = np.asarray(vpart).tolist()
    tag = (np.asarray(tagged) != 0).tolist()
    own = {p for p, t in zip(vp, tag) if t}
    child = {}
    for a, b in E.tolist():
        for x, y in ((a, b), (b, a)):
            if tag[x] and not tag[y] and vp[y] not in own:
                child.setdefault(vp[y], set()).add(x)
    loops = {names[p]: sorted(v) for p, v in sorted(child.items()) if len(v) >= 3}
    used = set().union(*loops.values()) if loops else set()
    rest = [i for i, t in enumerate(tag) if t and i not in used]
    adj = {i: [] for i in rest}
    for a, b in E.tolist():
        if a in adj and b in adj:
            adj[a].append(b)
            adj[b].append(a)
    seen = set()
    k = 0
    for i in rest:
        if i in seen:
            continue
        comp, stack = [], [i]
        seen.add(i)
        while stack:
            v = stack.pop()
            comp.append(v)
            for w in adj[v]:
                if w not in seen:
                    seen.add(w)
                    stack.append(w)
        loops['loop%d' % k] = sorted(comp)
        k += 1
    return loops


def loop_stats(points):
    """Size of one hole loop from its vertex positions (any order): {'verts', 'centroid', 'top',
    'bottom', 'height' (z extent), 'perimeter'} in metres. The perimeter runs round the vertices in
    angular order about the centroid in the loop's best-fit plane, which suits the convex-ish holes
    of welded joins and ignores the edges triangulation adds across them."""
    P = np.asarray(points, np.float64).reshape(-1, 3)
    c = P.mean(axis=0)
    Q = P - c
    _, vecs = np.linalg.eigh(Q.T @ Q)
    ang = np.arctan2(Q @ vecs[:, 1], Q @ vecs[:, 2])
    ring = P[np.argsort(ang, kind='stable')]
    per = float(np.linalg.norm(ring - np.roll(ring, -1, axis=0), axis=1).sum()) if len(P) > 1 else 0.0
    return {'verts': int(len(P)), 'centroid': [round(float(x), 4) for x in c],
            'top': round(float(P[:, 2].max()), 4), 'bottom': round(float(P[:, 2].min()), 4),
            'height': round(float(P[:, 2].max() - P[:, 2].min()), 4), 'perimeter': round(per, 4)}


def armhole_report(obj_name, layer='join_loop'):
    """Every tagged hole loop of a mesh object (join_loops): {key: loop_stats} in world space, keyed by
    the part grown out of the hole ('loop<k>' for holes not filled yet). obj_name: the mesh object;
    layer: the int vertex attribute that tags the hole vertices (lpk.forms.joins). Compare the sides
    with each other and with the reference: a hole much taller than the arm is thick is a sleeve
    fused down the side."""
    co, _, _, loops = _hole_loops(obj_name, layer)
    return {key: loop_stats(co[ids]) for key, ids in loops.items()}


def _hole_loops(obj_name, layer):
    """(world-space vertex positions, vertex part ids, part names, join_loops of the mesh)."""
    import bpy
    ob = bpy.data.objects[obj_name]
    me = ob.data
    if layer not in me.attributes:
        raise KeyError('mesh %s has no vertex layer %r' % (me.name, layer))
    _, co, vpart, _, names = read_mesh(obj_name)
    tag = np.empty(len(me.vertices), np.int32)
    me.attributes[layer].data.foreach_get('value', tag)
    edges = np.empty(len(me.edges) * 2, np.int32)
    me.edges.foreach_get('vertices', edges)
    return co, vpart, names, join_loops(edges.reshape(-1, 2), vpart, tag, names)


def part_vertices(obj_name, parts):
    """World-space positions (N, 3) of the vertices that carry the named part or parts, in vertex order."""
    _, co, vpart, _, names = read_mesh(obj_name)
    return co[np.isin(vpart, _ids(names, parts))]


# -- shells -------------------------------------------------------------------------------------------

def ray_hits(origins, dirs, tris):
    """Where rays meet triangles: (N, T) ray parameters t, the hit lying at origin + t * dir (metres
    along a unit dir), NaN where ray n misses triangle t. A ray is a whole line here, so t is negative
    behind its origin. A hit on a triangle's edge or corner counts (a 1e-9 barycentric tolerance), so a
    ray through the edge two triangles share meets both; a triangle the ray runs parallel to, or a
    degenerate one, is missed. origins, dirs: (N, 3); tris: (T, 3, 3) corner positions."""
    O = np.asarray(origins, np.float64).reshape(-1, 3)
    D = np.asarray(dirs, np.float64).reshape(-1, 3)
    T = np.asarray(tris, np.float64).reshape(-1, 3, 3)
    out = np.full((len(O), len(T)), np.nan)
    if not len(O) or not len(T):
        return out
    A = T[:, 0]
    e1, e2 = T[:, 1] - A, T[:, 2] - A
    for s in range(0, len(O), _RAY_BLOCK):
        o, d = O[s:s + _RAY_BLOCK, None, :], D[s:s + _RAY_BLOCK, None, :]
        p = np.cross(d, e2[None])
        det = (e1[None] * p).sum(-1)
        ok = np.abs(det) > 1e-15
        inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
        q = o - A[None]
        u = (q * p).sum(-1) * inv
        qe = np.cross(q, e1[None])
        v = (d * qe).sum(-1) * inv
        t = (e2[None] * qe).sum(-1) * inv
        hit = ok & (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9)
        out[s:s + _RAY_BLOCK] = np.where(hit, t, np.nan)
    return out


def clearance(points, tris, centre=None, normals=None, inner=None):
    """Where each point stands against a shell of triangles, measured along one ray per point.

    points: (N, 3); tris: (T, 3, 3) the shell's triangles. One of centre and normals gives the rays:
    centre (3,), a ray from it through each point (a cap or a hood over what it covers); normals
    (N, 3), a ray along each point's outward normal (a plate or a collar lying on a surface). Along a
    centre ray, a point is under the shell when the shell lies beyond it, and outside when the only
    shell between it and the centre lies short of it. Along a normal ray, a point is under the shell
    when the shell lies ahead of it with the point on the triangle's inner side, and outside when the
    shell lies behind it with the point on the triangle's outer side (corners in counter-clockwise
    order seen from outside, as the builders make them) and no triangle of `inner`, the covered surface
    (N_i, 3, 3), lies between them: a shell seen behind the point through the covered part's far wall
    belongs to another side.

    Returns {'gap': (N,) metres along the ray: the clearance to the nearest shell surface ahead when
    the point is under the shell (0 or more), minus how far the point stands out past the nearest
    shell surface behind it when it is outside, NaN when no ray meets the shell or the point sits on
    the centre; 'tri': (N,) the index of the shell triangle the gap runs to, -1 with a NaN gap}.
    Raises ValueError unless exactly one of centre and normals is given."""
    P = np.asarray(points, np.float64).reshape(-1, 3)
    T = np.asarray(tris, np.float64).reshape(-1, 3, 3)
    if (centre is None) == (normals is None):
        raise ValueError('clearance needs one of centre and normals')
    gap = np.full(len(P), np.nan)
    tri = np.full(len(P), -1, np.int64)
    if not len(P) or not len(T):
        return {'gap': gap, 'tri': tri}
    if centre is not None:
        c = np.asarray(centre, np.float64).reshape(3)
        d = P - c
        r = np.linalg.norm(d, axis=1)
        live = r > 1e-12
        d[live] /= r[live, None]
        t = ray_hits(np.broadcast_to(c, P.shape), d, T)
        t[~live] = np.nan
        ahead = np.where(t >= r[:, None], t - r[:, None], np.nan)
        behind = np.where((t > 0) & (t < r[:, None]), t - r[:, None], np.nan)
    else:
        n = np.asarray(normals, np.float64).reshape(-1, 3)
        length = np.linalg.norm(n, axis=1)
        live = length > 1e-12
        n = np.where(live[:, None], n / np.where(live, length, 1.0)[:, None], 0.0)
        t = ray_hits(P, n, T)
        t[~live] = np.nan
        N = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
        outer = ((P[:, None, :] - T[None, :, 0]) * N[None]).sum(-1) > 0
        ahead = np.where((t >= 0) & ~outer, t, np.nan)
        behind = np.where((t < 0) & outer, t, np.nan)
        if inner is not None and len(np.asarray(inner)):
            ti = ray_hits(P, n, inner)
            ti = np.where(ti < -1e-9, ti, np.nan)
            for k in np.flatnonzero(np.isfinite(behind).any(axis=1)):
                cross = ti[k][np.isfinite(ti[k])]
                if len(cross):
                    behind[k, behind[k] < cross.max()] = np.nan
    has_ahead = np.isfinite(ahead).any(axis=1)
    has_behind = np.isfinite(behind).any(axis=1)
    k = np.flatnonzero(has_ahead)
    if len(k):
        j = np.nanargmin(ahead[k], axis=1)
        gap[k], tri[k] = ahead[k, j], j
    k = np.flatnonzero(~has_ahead & has_behind)
    if len(k):
        j = np.nanargmax(behind[k], axis=1)
        gap[k], tri[k] = behind[k, j], j
    return {'gap': gap, 'tri': tri}


def open_edge_triangles(tris):
    """(T,) whether each triangle of a surface touches its open edge: a corner on an edge that only one
    of the triangles uses. tris: (T, 3) vertex ids."""
    t = np.asarray(tris, np.int64).reshape(-1, 3)
    if not len(t):
        return np.zeros(0, bool)
    e = np.sort(np.concatenate([t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]]), axis=1)
    keys, counts = np.unique(e, axis=0, return_counts=True)
    return np.isin(t, np.unique(keys[counts == 1])).any(axis=1)


def _direction(d):
    """(azimuth, elevation) in degrees of direction d: the azimuth from the front (-Y) toward the
    character's left (+X), the elevation above the horizontal."""
    d = np.asarray(d, np.float64)
    r = float(np.linalg.norm(d))
    if r < 1e-12:
        return 0.0, 0.0
    return (round(math.degrees(math.atan2(d[0], -d[1])), 1),
            round(math.degrees(math.asin(max(-1.0, min(1.0, d[2] / r)))), 1))


def _per_shell(value, shell):
    """A shell_clearance option given once for every shell, or as {shell: value}."""
    return value.get(shell) if isinstance(value, dict) else value


def shell_clearance(obj_name, shells, centre=None, rays=None):
    """Whether each shell part clears the parts it covers: per covered vertex, a ray
    (clearance) against the shell's triangles says whether the vertex lies under the shell and how far,
    or outside it, poking through.

    obj_name: the mesh object; shells: {shell part: covered part or [covered parts]}; centre: the point
    the 'centre' rays start from, in the object's own space (the build's metres), one for every shell
    or {shell: point}; None takes the centre of the bounding box of the shell and its covered parts.
    A shell cast from a centre (lpk.forms.hair.hair_cap's center) is best checked from that point: from
    another one the rays meet the cap's tucked edge at other angles and list other vertices there.
    rays: one of SHELL_RAYS for every shell or {shell: mode}; None takes 'centre'. Covered vertices that
    are corners of the shell's own triangles (a welded rim) belong to the shell and are not checked.
    Raises ValueError for a mode outside SHELL_RAYS or a centre that is not three numbers.

    Returns {'height': the body's height in metres, the z extent of its vertices; 'shells': {shell:
    {'covers': [covered parts], 'missing': [the named parts the object does not have], 'rays': the
    mode, 'centre': [x, y, z] the rays' centre and the origin of every azimuth and elevation (None
    while a part is missing), 'triangles': the shell's triangles, 'parts': {covered part: {'vertices':
    covered vertices checked, 'under': those whose ray meets the shell, 'outside': the vertices
    standing out past the shell by more than POSITION_NOISE, farthest first, 'inside': the others whose
    ray meets the shell, closest first}}}}}. Each vertex entry is {'vertex': its id, 'distance': metres
    outside the shell or under it, 'azimuth', 'elevation': degrees of its direction from the centre,
    the azimuth from the front (-Y) toward the character's left (+X), 'edge': whether its ray meets a
    shell triangle that touches the shell's open edge, where a cap tucked into the part ends}."""
    ob, co, vpart, tris, names = read_mesh(obj_name, world=False)
    me = ob.data
    nrm = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get('normal', nrm)
    nrm = nrm.reshape(-1, 3).astype(np.float64)
    fp = face_parts(vpart, tris)
    out = {'height': round(float(co[:, 2].max() - co[:, 2].min()), 6) if len(co) else 0.0, 'shells': {}}
    for shell, covers in shells.items():
        covers = [covers] if isinstance(covers, str) else list(covers)
        mode = _per_shell(rays, shell) or 'centre'
        if mode not in SHELL_RAYS:
            raise ValueError('shell_clearance rays=%r for %r: one of %s' % (mode, shell, ', '.join(SHELL_RAYS)))
        missing = [p for p in [shell] + covers if p not in names]
        entry = {'covers': covers, 'missing': missing, 'rays': mode, 'centre': None, 'triangles': 0, 'parts': {}}
        out['shells'][shell] = entry
        if missing:
            continue
        sid = names.index(shell)
        st = tris[fp == sid]
        entry['triangles'] = int(len(st))
        cids = [names.index(p) for p in covers]
        c = _per_shell(centre, shell)
        if c is None:
            sel = co[np.isin(vpart, [sid] + cids)]
            c = (sel.min(axis=0) + sel.max(axis=0)) / 2
        c = np.asarray(c, np.float64)
        if c.shape != (3,):
            raise ValueError('shell_clearance centre for %r: three numbers (x, y, z), not %r' % (shell, c.tolist()))
        entry['centre'] = [round(float(x), 6) for x in c]
        edge = open_edge_triangles(st)
        on_shell = np.zeros(len(co), bool)
        on_shell[st.reshape(-1)] = True
        for part, pid in zip(covers, cids):
            ids = np.flatnonzero((vpart == pid) & ~on_shell)
            if mode == 'centre':
                r = clearance(co[ids], co[st], centre=c)
            else:
                r = clearance(co[ids], co[st], normals=nrm[ids], inner=co[tris[np.isin(fp, cids)]])
            under, outside, inside = 0, [], []
            for i, g, k in zip(ids.tolist(), r['gap'].tolist(), r['tri'].tolist()):
                if not math.isfinite(g):
                    continue
                under += 1
                az, el = _direction(co[i] - c)
                poke = g < -POSITION_NOISE
                e = {'vertex': i, 'distance': round(-g if poke else max(g, 0.0), 6), 'azimuth': az,
                     'elevation': el, 'edge': bool(edge[k])}
                (outside if poke else inside).append(e)
            outside.sort(key=lambda e: (-e['distance'], e['vertex']))
            inside.sort(key=lambda e: (e['distance'], e['vertex']))
            entry['parts'][part] = {'vertices': int(len(ids)), 'under': under, 'outside': outside, 'inside': inside}
    return out


# -- mirror -------------------------------------------------------------------------------------------

def mirror_twins(co, tol=MIRROR_TOLERANCE):
    """(N,) the twin of each vertex: the vertex nearest its mirror image across x = 0, (-x, y, z), when
    that one lies within `tol` metres, else -1; a vertex within `tol` of the midline is its own twin.
    Off the midline this is the rule of the smooth bake's mirror (lpk.stages.rig._mirror), applied to
    both sides; of two candidates at one distance the lower id wins. co: (N, 3) positions in the
    object's own space, where the midline is x = 0."""
    P = np.asarray(co, np.float64).reshape(-1, 3)
    n = len(P)
    twin = np.full(n, -1, np.int64)
    if not n:
        return twin
    Q = P * np.array([-1.0, 1.0, 1.0])
    cp, cq = np.floor(P / tol).astype(np.int64), np.floor(Q / tol).astype(np.int64)
    lo = np.minimum(cp.min(axis=0), cq.min(axis=0)) - 1
    span = np.maximum(cp.max(axis=0), cq.max(axis=0)) - lo + 2

    def key(c):
        c = c - lo
        return (c[:, 0] * span[1] + c[:, 1]) * span[2] + c[:, 2]
    kp = key(cp)
    order = np.argsort(kp, kind='stable')
    sk = kp[order]
    qs, ps = [], []
    # A point within tol of a mirror image lies in the image's grid cell or in one of its 26 neighbours.
    for off in itertools.product((-1, 0, 1), repeat=3):
        k = key(cq + np.array(off))
        left, right = np.searchsorted(sk, k, 'left'), np.searchsorted(sk, k, 'right')
        cnt = right - left
        if not cnt.any():
            continue
        qs.append(np.repeat(np.arange(n), cnt))
        ps.append(order[np.repeat(left, cnt) + np.arange(cnt.sum()) - np.repeat(np.cumsum(cnt) - cnt, cnt)])
    if qs:
        q, p = np.concatenate(qs), np.concatenate(ps)
        dist = np.linalg.norm(Q[q] - P[p], axis=1)
        keep = dist <= tol
        q, p, dist = q[keep], p[keep], dist[keep]
        best = np.lexsort((p, dist, q))
        q, p = q[best], p[best]
        first = np.ones(len(q), bool)
        first[1:] = q[1:] != q[:-1]
        twin[q[first]] = p[first]
    mid = np.abs(P[:, 0]) <= tol
    twin[mid] = np.flatnonzero(mid)
    return twin


def mirror_offsets(co, ids):
    """(len(ids),) metres from the mirror image of each listed vertex to the nearest vertex of the
    mesh: how far off mirror a vertex without a twin stands. co: (N, 3)."""
    P = np.asarray(co, np.float64).reshape(-1, 3)
    ids = np.asarray(ids, np.int64).reshape(-1)
    out = np.zeros(len(ids))
    Q = P[ids] * np.array([-1.0, 1.0, 1.0])
    for s in range(0, len(ids), _RAY_BLOCK):
        out[s:s + _RAY_BLOCK] = np.linalg.norm(Q[s:s + _RAY_BLOCK, None, :] - P[None], axis=2).min(axis=1)
    return out


def mirror_parts(co, vpart, names, tol=MIRROR_TOLERANCE):
    """The mirror reading of every part (mirror_twins). co, vpart: (N, 3) positions in the object's own
    space and (N,) part ids; names: part names by id.

    Returns {'pairs': [[part, twin part], ...] the pairs found, in part order: two parts whose vertices
    with a twin mostly mirror into each other, or a part mostly mirroring into itself; 'unpaired': [the
    parts in no found pair]; 'parts': {part: {'vertices': its vertices, 'twins': {part: its vertices
    whose twin carries that part}, 'twin_verts': {part: [the ids of those vertices]}, 'unmatched':
    [[vertex id, mirror_offsets' metres], ...] the vertices without a twin}}}."""
    vp = np.asarray(vpart, np.int64)
    twin = mirror_twins(co, tol)
    parts, main = {}, {}
    for pid, name in enumerate(names):
        ids = np.flatnonzero(vp == pid)
        if not len(ids):
            continue
        matched = ids[twin[ids] >= 0]
        by = {}
        for i, q in zip(matched.tolist(), vp[twin[matched]].tolist()):
            by.setdefault(names[q], []).append(i)
        twins = {nm: len(by[nm]) for nm in names if nm in by}
        main[name] = max(twins, key=lambda nm: (twins[nm], -names.index(nm))) if twins else None
        lost = ids[twin[ids] < 0]
        unmatched = [[i, round(d, 6)] for i, d in zip(lost.tolist(), mirror_offsets(co, lost).tolist())]
        parts[name] = {'vertices': int(len(ids)), 'twins': twins,
                       'twin_verts': {nm: by[nm] for nm in names if nm in by}, 'unmatched': unmatched}
    pairs, paired = [], set()
    for name in parts:
        other = main[name]
        if name in paired or other is None or (other != name and main.get(other) != name):
            continue
        pairs.append([name, other])
        paired.update((name, other))
    return {'pairs': pairs, 'unpaired': [nm for nm in parts if nm not in paired], 'parts': parts}


def mirror_report(obj_name):
    """Whether the parts of a mesh object mirror across the midline, x = 0 in the object's own space,
    read from the vertices' positions by a twin search of its own (mirror_parts), never from the part
    names. A pair mirrors when every vertex of its parts has a twin in the pair; the faces are not
    compared, so two sides triangulated differently over mirrored vertices mirror. obj_name: the mesh
    object.

    Returns mirror_parts' {'pairs', 'unpaired', 'parts'} plus 'tolerance': MIRROR_TOLERANCE, the twin
    distance in metres."""
    _, co, vpart, _, names = read_mesh(obj_name, world=False)
    out = mirror_parts(co, vpart, names)
    out['tolerance'] = MIRROR_TOLERANCE
    return out
