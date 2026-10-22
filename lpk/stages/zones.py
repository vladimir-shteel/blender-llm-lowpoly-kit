"""Zones: the layers that say what each piece of a body is, read and changed by part, and the frozen mesh
that carries them in the frozen build mode (ARCHITECTURE.md "Build modes").

A body carries three zone layers: the part of each vertex (int point attribute 'part', an index into the
object's 'parts' list, 0 reserved), the palette colour of each face (int face attribute 'pal', an index
into its 'palette' list) and the welded joins' hole loops (int point attribute 'join_loop', 1 on a loop
vertex); the object also holds the painted marks (lpk.stages.texture.MARKS). Blender interpolates integer
attributes through its topology operators (a subdivided edge between two parts takes a value of neither, or
of one by chance), so after a topology edit the layers are taken again from a reference by the nearest
surface (transfer), never trusted as they stand.

The frozen mesh '<NAME>_Frozen' is a mesh datablock with a fake user: the triangulated geometry without
colour attributes or vertex groups, the three zone layers, and the custom properties 'parts',
'palette' and, when the body had marks, MARKS. store writes it, body_from_frozen copies it into the body.
It holds no UVs, except under a frozen texture (ARCHITECTURE.md "Build modes"): then it carries the atlas
UV layer lpk.stages.texture.UV_LAYER (store_uv writes it, drop_uv removes it), which body_from_frozen's
copy brings back.

The build stamp is three properties of the body object, the topology key (topology_key), the position
digest (position_digest) and the UV digest (uv_digest) of the mesh the kit last wrote (stamp); edited
compares the mesh with them.

In the frozen mode the colour sources, built on the parametric body, are carried onto the frozen one by
the nearest surface of the same part (conform_sources).

Every reading here is in the object's own space, the space a build places geometry in. The digests, the
zone choice from nearest-surface hits and the summary's arithmetic are numpy and run on the host; the
readers and writers import Blender inside their functions."""
import hashlib

import numpy as np

from lpk.stages import checks, imaging

# The object properties of the build stamp.
STAMP_TOPOLOGY = 'lpk_topology'
STAMP_POSITIONS = 'lpk_positions'
STAMP_UV = 'lpk_uv'
# Metres the position digest rounds to: a float32 position read back is the same number, so one written
# and read again digests the same; a hand move is far above it.
POSITION_STEP = 1e-6
# Metres from the reference surface beyond which freeze counts a vertex as far: the geometry an edit made
# off the surface (an extrusion, a new spike), whose part is the nearest surface's guess; a vertex a
# subdivision or a dissolve left on the surface reads float32 rounding, far below it.
FAR_TOLERANCE = 0.002
# Metres within which a vertex keeps the hole-loop tag of a reference vertex: a loop vertex the edit left
# where it was stays within float32 rounding of it; a vertex moved further, or a new one between loop
# vertices, is not a loop vertex the weld made, and the join smoothing would read it as one.
JOIN_TOLERANCE = 1e-4
SELECTIONS = ('faces', 'verts')
# The named pivots of transform (pivot_point).
PIVOTS = ('centre', 'base')
# The smallest cosine between a face's normal before and after a decimation collapse moves one of its
# corners: a collapse that turns a face further folds the surface over itself and is not made.
COLLAPSE_COS = 0.5
# Decimation rounds at most: each round makes every collapse whose neighbourhood no earlier one of the
# round touched, so a part needs a few rounds; one that stops shrinking ends sooner.
COLLAPSE_ROUNDS = 64
# UV units within which two corners hold the same UV: float32 stores a UV near 1 to about 6e-8, so a corner
# written and read again, or two faces of one island meeting at a vertex, match far within it.
UV_MATCH = 1e-6
# Texels squared under which a face's UV area reads as none in the UV check ('zero'): its corners lie on one
# point or one line, as on the faces an extrusion or a fill makes without UVs, and it bakes no texel of its
# own. Float32 rounding of a real face's UVs stays far below it on any atlas size.
ZERO_UV_TEXELS = 1e-4
# Texels by which two faces' UVs must interpenetrate, along every direction that could part them, before
# the UV check reads an overlap: islands packed apart, or meeting edge to edge, read zero or less; deeper,
# the two faces share texel centres and the bake writes one face's colour over the other's.
OVERLAP_TEXELS = 0.5
# The factor by which a face's texels per metre may differ from the median of the faces round it in its
# island before the UV check reads it as far from theirs ('density'): a face four times denser or sparser
# holds sixteen times, or a sixteenth, the texel area its island gives its size, as an edit that
# stretched or squashed its UVs leaves it. An island holds one atlas group of one part, so the densities a
# model sets apart (groups, boost, the face island) are never compared; an unwrap that squashes faces
# inside an island by as much (a tight fold, a sliver) reads here too, before any edit.
DENSITY_RATIO = 4.0
# Texels per side of the grid cells the overlap search buckets triangles into: it only bounds the pairs
# compared, never which overlap.
OVERLAP_CELL = 16
# The smallest cosine between a face's normal and that of the first face of its repair chart (uv_charts):
# a chart is projected flat along that normal, so each face keeps at least this share of its area in UV
# and the texels per metre within a chart stay within 1 / sqrt(REPAIR_CHART_COS) of each other.
REPAIR_CHART_COS = 0.7


# -- pure parts ------------------------------------------------------------------------------------------

def topology_key(n_verts, loop_total, loop_vert):
    """The topology key of a mesh: the SHA-256 hex of its vertex count, the corner count of each polygon
    and each polygon's vertex indices, in mesh order. Unlike lpk.core.edits.topology (one part, faces
    sorted, so a part keeps its key when another changes), it reads the whole mesh as it is stored: any
    added, removed or reconnected element, and any reordering, changes it; a vertex move does not.
    loop_total: (F,) corners per polygon; loop_vert: (L,) the vertex of each corner, polygon after
    polygon."""
    h = hashlib.sha256()
    h.update(np.int64(n_verts).tobytes())
    h.update(np.asarray(loop_total, np.int64).tobytes())
    h.update(np.asarray(loop_vert, np.int64).tobytes())
    return h.hexdigest()


def position_digest(co):
    """The SHA-256 hex of vertex positions `co` ((N, 3) metres, mesh order) rounded to POSITION_STEP."""
    q = np.rint(np.asarray(co, np.float64).reshape(-1, 3) / POSITION_STEP).astype(np.int64)
    return hashlib.sha256(q.tobytes()).hexdigest()


def uv_digest(uv):
    """The UV digest of the build stamp: the SHA-256 hex of the UVs as float32 (u, v) pairs in loop order,
    the values Blender stores, so UVs written and read again digest the same and any edit of one corner
    changes it. uv: (L, 2) or flat."""
    return hashlib.sha256(np.ascontiguousarray(np.asarray(uv, np.float32).ravel()).tobytes()).hexdigest()


def polygons(loop_start, loop_total, loop_vert):
    """[[vertex ids] per polygon] from the loop ranges of a mesh."""
    lv = np.asarray(loop_vert, np.int64)
    return [lv[s:s + t].tolist() for s, t in zip(np.asarray(loop_start).tolist(), np.asarray(loop_total).tolist())]


def polygon_parts(polys, vpart):
    """(F,) the part of each polygon: the part most of its vertices carry, the first of them breaking a
    tie (lpk.stages.checks' rule, on polygons of any size). polys: polygons(); vpart: (N,) part ids."""
    vp = np.asarray(vpart, np.int64)
    out = np.zeros(len(polys), np.int64)
    for k, poly in enumerate(polys):
        ids = vp[poly].tolist()
        counts = {}
        for i in ids:
            counts[i] = counts.get(i, 0) + 1
        best = max(counts.values())
        out[k] = next(i for i in ids if counts[i] == best)
    return out


def nearest_corner_parts(hit_face, hit_point, ref_co, ref_polys, ref_part):
    """(N,) the part each point takes from its nearest reference face: the part of that face's corner
    nearest the point's nearest-surface location, the earlier corner on a tie. A point on a reference
    vertex takes that vertex's part, whichever of the faces round it the search returned; a point inside a
    face takes the part of the corner it lies closest to, so a face spanning two parts (a weld's bridge)
    splits between them along the middle. hit_face: (N,) reference polygon ids; hit_point: (N, 3) the
    locations on them (m); ref_co: (R, 3); ref_polys: polygons() of the reference; ref_part: (R,)."""
    rc = np.asarray(ref_co, np.float64).reshape(-1, 3)
    rp = np.asarray(ref_part, np.int64)
    hp = np.asarray(hit_point, np.float64).reshape(-1, 3)
    out = np.zeros(len(hp), np.int64)
    for k, (f, p) in enumerate(zip(np.asarray(hit_face, np.int64).tolist(), hp)):
        corners = ref_polys[f]
        d = np.linalg.norm(rc[corners] - p, axis=1)
        out[k] = rp[corners[int(np.argmin(d))]]
    return out


def join_tags(co, ref_co, ref_tag, tol=JOIN_TOLERANCE):
    """(N,) 1 for each point within `tol` metres of a reference vertex tagged 1, else 0. co: (N, 3);
    ref_co: (R, 3); ref_tag: (R,) the reference's join_loop values."""
    P = np.asarray(co, np.float64).reshape(-1, 3)
    T = np.asarray(ref_co, np.float64).reshape(-1, 3)[np.asarray(ref_tag, np.int64) == 1]
    out = np.zeros(len(P), np.int64)
    if not len(T):
        return out
    for s in range(0, len(P), 256):
        d = np.linalg.norm(P[s:s + 256, None, :] - T[None], axis=2).min(axis=1)
        out[s:s + 256] = d <= tol
    return out


def name_counts(ids, names):
    """{name: how many of `ids` carry it} in the order of `names`; an id outside names counts under ''."""
    counts = {}
    for i in np.asarray(ids, np.int64).tolist():
        nm = names[i] if 0 <= i < len(names) else ''
        counts[nm] = counts.get(nm, 0) + 1
    order = {nm: k for k, nm in enumerate(names)}
    return {nm: counts[nm] for nm in sorted(counts, key=lambda nm: order.get(nm, -1))}


def changed_counts(old, old_names, new, new_names):
    """{new name: elements whose name under `new` differs from their name under `old`}, names compared,
    not indices (the two lists may order them differently); an id outside its list reads ''. old, new: (K,)
    ids; old_names, new_names: the names by id. None for `old` (the layer was missing) counts every
    element."""
    new = np.asarray(new, np.int64)
    nn = [new_names[i] if 0 <= i < len(new_names) else '' for i in new.tolist()]
    if old is None:
        on = [None] * len(nn)
    else:
        on = [old_names[i] if 0 <= i < len(old_names) else '' for i in np.asarray(old, np.int64).tolist()]
    out = {}
    for a, b in zip(on, nn):
        if a != b:
            out[b] = out.get(b, 0) + 1
    order = {nm: k for k, nm in enumerate(new_names)}
    return {nm: out[nm] for nm in sorted(out, key=lambda nm: order.get(nm, -1))}


def far_counts(dist, vpart, names, tol=FAR_TOLERANCE):
    """({part: vertices farther than `tol` metres from the reference surface}, {part: the farthest of
    them in cm, rounded to 0.01}) over the parts that have such vertices, in part order. dist: (N,)
    nearest-surface distances (m); vpart: (N,) the parts the vertices took; names: part names by id."""
    d = np.asarray(dist, np.float64)
    vp = np.asarray(vpart, np.int64)
    far = d > tol
    counts, worst = {}, {}
    for pid, nm in enumerate(names):
        sel = far & (vp == pid)
        if sel.any():
            counts[nm] = int(sel.sum())
            worst[nm] = round(float(d[sel].max()) * 100, 2)
    return counts, worst


def borders(polys, face_part, edge_verts, co):
    """{(part a, part b): [shared edges, their length in m]} with a < b: the edges two faces of different
    parts share (face part: polygon_parts). polys: polygons(); edge_verts: (E, 2) vertex ids of the mesh's
    edges; co: (N, 3)."""
    ev = np.asarray(edge_verts, np.int64).reshape(-1, 2)
    index = {(min(a, b), max(a, b)): e for e, (a, b) in enumerate(ev.tolist())}
    faces_of = {}
    for f, poly in enumerate(polys):
        for k in range(len(poly)):
            a, b = poly[k], poly[(k + 1) % len(poly)]
            faces_of.setdefault(index[(min(a, b), max(a, b))], []).append(f)
    C = np.asarray(co, np.float64).reshape(-1, 3)
    out = {}
    for e in sorted(faces_of):
        fs = faces_of[e]
        if len(fs) != 2 or face_part[fs[0]] == face_part[fs[1]]:
            continue
        key = tuple(sorted((int(face_part[fs[0]]), int(face_part[fs[1]]))))
        a, b = ev[e]
        entry = out.setdefault(key, [0, 0.0])
        entry[0] += 1
        entry[1] += float(np.linalg.norm(C[a] - C[b]))
    return out


def part_table(co, vpart, polys, pal, edge_verts, names, palette_size):
    """The per-part numbers of summary that need no reference: {part: {'faces': polygons of the part
    (polygon_parts), 'tris': the triangles they fan into, 'verts': vertices, 'centre': [x, y, z] the centre
    of its vertices' bounding box and 'size': [x, y, z] its extent (m, rounded to 0.1 mm), 'neighbours':
    {part: the edges its faces share with that part's faces}, 'border_m': {part: those edges' length in
    m, rounded to 1 mm}, 'mirror': the part its vertices mostly mirror into across x = 0
    (lpk.stages.checks.mirror_parts' pair; itself for a part on the midline; None when unpaired),
    'mirror_offset': the largest distance in cm, rounded to 0.01, from the mirror image of one of its
    vertices to the nearest vertex (lpk.stages.checks.mirror_offsets), 'uncoloured': its faces whose
    'pal' is outside the palette's palette_size names}} for every part with vertices, in part order, and
    '' for the vertices whose id is 0 or outside `names`."""
    vp = np.asarray(vpart, np.int64)
    C = np.asarray(co, np.float64).reshape(-1, 3)
    valid = (vp > 0) & (vp < len(names))
    vp_named = np.where(valid, vp, 0)
    fp = polygon_parts(polys, vp_named)
    sizes = np.array([len(p) for p in polys], np.int64)
    pal = np.asarray(pal, np.int64)
    border = borders(polys, fp, edge_verts, C)
    mirror = checks.mirror_parts(C, vp_named, names)
    twin = {}
    for a, b in mirror['pairs']:
        twin[a], twin[b] = b, a
    offsets = checks.mirror_offsets(C, np.arange(len(C))) if len(C) else np.zeros(0)
    out = {}
    for pid, nm in enumerate(names):
        ids = np.flatnonzero(vp_named == pid)
        if not len(ids):
            continue
        lo, hi = C[ids].min(axis=0), C[ids].max(axis=0)
        faces = fp == pid
        neighbours, lengths = {}, {}
        for (a, b), (count, length) in sorted(border.items()):
            if pid in (a, b):
                other = names[b if a == pid else a]
                neighbours[other] = count
                lengths[other] = round(length, 3)
        out[nm] = {'faces': int(faces.sum()), 'tris': int(np.maximum(sizes[faces] - 2, 0).sum()),
                   'verts': int(len(ids)), 'centre': [round(float(x), 4) for x in (lo + hi) / 2],
                   'size': [round(float(x), 4) for x in hi - lo], 'neighbours': neighbours, 'border_m': lengths,
                   'mirror': twin.get(nm) if pid else None,
                   'mirror_offset': round(float(offsets[ids].max()) * 100, 2),
                   'uncoloured': int(((pal[faces] < 0) | (pal[faces] >= palette_size)).sum())}
    return out


def deviation(dist):
    """{'mean_cm', 'max_cm'} of nearest-surface distances `dist` (m), rounded to 0.01 cm; None when empty."""
    d = np.asarray(dist, np.float64)
    if not len(d):
        return None
    return {'mean_cm': round(float(d.mean()) * 100, 2), 'max_cm': round(float(d.max()) * 100, 2)}


def linear_to_srgb(c):
    """An sRGB colour (3 channels, 0 to 1) of a linear one: the inverse of lpk.core.builder.srgb_to_linear."""
    return tuple(12.92 * x if x <= 0.0031308 else 1.055 * x ** (1 / 2.4) - 0.055
                 for x in (max(0.0, float(v)) for v in c[:3]))


def nearest_colour(srgb, palette):
    """The index in `palette` ({name: sRGB}, in its order) of the colour nearest `srgb` by RGB distance,
    the earlier one on a tie."""
    cols = np.asarray([tuple(v)[:3] for v in palette.values()], np.float64)
    return int(np.argmin(np.linalg.norm(cols - np.asarray(srgb[:3], np.float64), axis=1)))


def strongest_group(weights, allowed):
    """The group a vertex takes among `allowed` group ids: the one of highest weight, the lowest id on a
    tie; None when it has none of them. weights: [(group id, weight)]."""
    best = None
    for g, w in sorted(weights):
        if g in allowed and w > 0 and (best is None or w > best[1]):
            best = (g, w)
    return None if best is None else best[0]


def adjacency(n_verts, edge_verts):
    """[[neighbour ids, ascending] per vertex] of a mesh with `n_verts` vertices and the edges `edge_verts`
    ((E, 2) vertex ids)."""
    nb = [set() for _ in range(n_verts)]
    for a, b in np.asarray(edge_verts, np.int64).reshape(-1, 2).tolist():
        if a != b:
            nb[a].add(b)
            nb[b].add(a)
    return [sorted(s) for s in nb]


def ring_distances(n_verts, edge_verts, seeds, limit):
    """(N,) the edge rings from each vertex to the nearest of `seeds`: 0 on a seed, k for a vertex k edges
    away over the mesh's edges, -1 for one farther than `limit` rings or not connected to any seed. A
    breadth-first search from the seeds in ascending index order, each ring's neighbours visited in index
    order, so the same mesh gives the same rings. seeds: vertex ids; limit: rings searched (int >= 0)."""
    nb = adjacency(n_verts, edge_verts)
    dist = np.full(n_verts, -1, np.int64)
    ring = sorted(set(int(i) for i in seeds))
    dist[ring] = 0
    for k in range(1, int(limit) + 1):
        nxt = []
        for v in ring:
            for w in nb[v]:
                if dist[w] < 0:
                    dist[w] = k
                    nxt.append(w)
        if not nxt:
            break
        ring = sorted(nxt)
    return dist


def falloff_weights(rings, falloff):
    """(N,) the share of a transform each vertex takes from its ring distance `rings` (ring_distances): 1 at
    ring 0, 1 - k / (falloff + 1) at ring k up to `falloff`, 0 beyond it and at -1. falloff 0: only ring 0
    moves."""
    r = np.asarray(rings, np.int64)
    w = 1.0 - r.astype(np.float64) / (int(falloff) + 1)
    return np.where((r >= 0) & (r <= int(falloff)), w, 0.0)


def rotation_matrix(degrees):
    """The (3, 3) rotation of Euler angles `degrees` (x, y, z) in Blender's 'XYZ' order: about X first, then
    Y, then Z, each about the fixed object axes (Rz @ Ry @ Rx)."""
    ax, ay, az = np.radians(np.asarray(degrees, np.float64).reshape(3))
    cx, sx, cy, sy, cz, sz = np.cos(ax), np.sin(ax), np.cos(ay), np.sin(ay), np.cos(az), np.sin(az)
    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return rz @ ry @ rx


def pivot_point(co, pivot):
    """The pivot of a part's transform from its vertex positions `co` ((K, 3) m): 'centre' the centre of
    their bounding box (part_table's 'centre'), 'base' that centre at their lowest z, or an (x, y, z) point
    in metres. Raises ValueError for anything else."""
    C = np.asarray(co, np.float64).reshape(-1, 3)
    if isinstance(pivot, str):
        if pivot not in PIVOTS:
            raise ValueError('pivot %r: use %s or an (x, y, z) point in metres' % (pivot, ', '.join(PIVOTS)))
        lo, hi = C.min(axis=0), C.max(axis=0)
        mid = (lo + hi) / 2
        return mid if pivot == 'centre' else np.array([mid[0], mid[1], lo[2]])
    p = np.asarray(pivot, np.float64)
    if p.shape != (3,):
        raise ValueError('pivot %r: use %s or an (x, y, z) point in metres' % (pivot, ', '.join(PIVOTS)))
    return p


def transformed(co, weights, translate, rotate, scale, pivot):
    """(N, 3) the positions `co` ((N, 3) m) moved by a weighted transform: each point p goes to
    p + w (T(p) - p), T(p) = pivot + R (s * (p - pivot)) + translate, R rotation_matrix(rotate) (degrees),
    s the scale (one factor or (x, y, z) factors along the object axes), pivot an (x, y, z) point (m).
    weights: (N,) 0 to 1 (falloff_weights). A point of weight between 0 and 1 moves along the straight
    line to its full place, so a band of such points stretches between the moved and the still ones."""
    C = np.asarray(co, np.float64).reshape(-1, 3)
    s = np.broadcast_to(np.asarray(scale, np.float64), (3,))
    p0 = np.asarray(pivot, np.float64).reshape(3)
    full = (rotation_matrix(rotate) @ ((C - p0) * s).T).T + p0 + np.asarray(translate, np.float64).reshape(3)
    return C + np.asarray(weights, np.float64).reshape(-1, 1) * (full - C)


def welded_parts(edge_verts, vpart, pid):
    """The ids of the parts other than `pid` that share an edge with it, ascending: a part with none is a
    separate shell (its vertices and faces touch no other part's). edge_verts: (E, 2); vpart: (N,)."""
    ev = np.asarray(edge_verts, np.int64).reshape(-1, 2)
    vp = np.asarray(vpart, np.int64)
    a, b = vp[ev[:, 0]], vp[ev[:, 1]]
    other = np.concatenate([b[(a == pid) & (b != pid)], a[(b == pid) & (a != pid)]])
    return sorted(set(other.tolist()))


def part_faces(polys, vpart, pid):
    """(F,) bool: the polygons all of whose vertices carry the part `pid`, the faces a zone operation may
    change. polys: polygons(); vpart: (N,)."""
    vp = np.asarray(vpart, np.int64)
    return np.array([bool((vp[p] == pid).all()) for p in polys], bool)


def pinned_vertices(polys, vpart, pid):
    """(N,) bool: the vertices of the part `pid` a zone operation keeps where they are: those on a polygon
    that is not all the part's (the border with another part, a weld's seam) and those on an edge with
    other than two of the part's faces (an open rim of the part, a non-manifold edge). Moving or removing a
    border vertex would open or shift the seam; an open rim would shrink."""
    vp = np.asarray(vpart, np.int64)
    pin = np.zeros(len(vp), bool)
    inside = part_faces(polys, vp, pid)
    count = {}
    for poly, ok in zip(polys, inside.tolist()):
        if not ok:
            pin[[i for i in poly if vp[i] == pid]] = True
            continue
        for k in range(len(poly)):
            e = (min(poly[k], poly[(k + 1) % len(poly)]), max(poly[k], poly[(k + 1) % len(poly)]))
            count[e] = count.get(e, 0) + 1
    for (a, b), c in count.items():
        if c != 2:
            pin[[a, b]] = True
    return pin


def smoothed(co, edge_verts, movable, iterations, factor):
    """(N, 3) the positions `co` after `iterations` Laplacian steps on the vertices `movable` ((N,) bool):
    each step moves every such vertex by `factor` (0 to 1) of the way to the mean of its edge neighbours,
    all of them from the positions of the step before (one simultaneous update, so the result does not
    depend on the vertex order). The others stay. A closed convex part shrinks a little with every step."""
    C = np.asarray(co, np.float64).reshape(-1, 3).copy()
    nb = adjacency(len(C), edge_verts)
    ids = [i for i in np.flatnonzero(np.asarray(movable, bool)).tolist() if nb[i]]
    for _ in range(int(iterations)):
        mean = np.array([C[nb[i]].mean(axis=0) for i in ids]).reshape(-1, 3)
        C[ids] = C[ids] + float(factor) * (mean - C[ids])
    return C


def collapse_cost(v_co, u_co, normals):
    """The error of moving a vertex from `v_co` onto its neighbour at `u_co` (m) in a half-edge collapse:
    the sum of squared distances from u to the planes of the vertex's faces (`normals`, (K, 3) unit
    normals of those planes, each through v)."""
    d = np.asarray(normals, np.float64).reshape(-1, 3) @ (np.asarray(u_co, np.float64) - np.asarray(v_co, np.float64))
    return float((d * d).sum())


def collapse_order(candidates, neighbours, wanted):
    """The half-edge collapses of one decimation round: candidates sorted by (cost, vertex, target) and taken
    greedily while no vertex of a taken one's neighbourhood is touched again, so every collapse of the round
    sees the mesh as it stood. candidates: [(cost, v, u)]; neighbours: {vertex: its neighbour ids}; wanted:
    the most to take. Returns [(v, u)] in the order taken."""
    used, out = set(), []
    for _, v, u in sorted(candidates):
        if len(out) >= wanted:
            break
        ring = {v, u} | set(neighbours[v]) | set(neighbours[u])
        if ring & used:
            continue
        used |= ring
        out.append((v, u))
    return out


def max_displacement_cm(before, after):
    """The largest distance in cm, rounded to 0.01, between positions `before` and `after` ((K, 3) m, the
    same vertices); 0.0 for none."""
    a = np.asarray(before, np.float64).reshape(-1, 3)
    b = np.asarray(after, np.float64).reshape(-1, 3)
    return round(float(np.linalg.norm(b - a, axis=1).max()) * 100, 2) if len(a) else 0.0


def _newell(a):
    """Newell's vector of the polygon with corners `a` ((K, 3)): twice its area along its normal."""
    b = np.roll(a, -1, axis=0)
    return np.array([((a[:, 1] - b[:, 1]) * (a[:, 2] + b[:, 2])).sum(),
                     ((a[:, 2] - b[:, 2]) * (a[:, 0] + b[:, 0])).sum(),
                     ((a[:, 0] - b[:, 0]) * (a[:, 1] + b[:, 1])).sum()])


def polygon_normals(co, polys):
    """(F, 3) the unit normal of each polygon by Newell's method (corners counter-clockwise seen from the
    side it points to); (0, 0, 0) for a polygon of no area. co: (N, 3) m; polys: polygons()."""
    C = np.asarray(co, np.float64).reshape(-1, 3)
    out = np.zeros((len(polys), 3))
    for k, p in enumerate(polys):
        n = _newell(C[p])
        length = np.linalg.norm(n)
        out[k] = n / length if length > 0 else 0.0
    return out


def vertex_normals(co, polys):
    """(N, 3) the unit normal of each vertex: the sum of the normals of its polygons weighted by their
    areas (Newell's vector is twice the area along the normal), normalised; (0, 0, 0) on a vertex of no
    polygon or whose polygons cancel. co: (N, 3) m; polys: polygons()."""
    C = np.asarray(co, np.float64).reshape(-1, 3)
    acc = np.zeros_like(C)
    for p in polys:
        acc[p] += _newell(C[p])
    length = np.linalg.norm(acc, axis=1, keepdims=True)
    return np.divide(acc, length, out=np.zeros_like(acc), where=length > 0)


def point_normals(co, polys, vnormals, faces, points):
    """(K, 3) the unit surface normal at each point on a mesh: the vertex normals `vnormals` of its
    triangle `faces[k]` blended by the point's barycentric weights (clamped to the triangle), so the
    normal runs on without a jump across an edge and two meshes alike in a region give the same normals
    there, whichever of two faces meeting at an edge a nearest-surface search returns. A polygon with more
    than three corners, and a blend that cancels, take the polygon's own normal (polygon_normals). co: (N,
    3) m; polys: polygons(); vnormals: vertex_normals(co, polys); faces: (K,) polygon ids; points: (K, 3)
    m, on those polygons."""
    C = np.asarray(co, np.float64).reshape(-1, 3)
    V = np.asarray(vnormals, np.float64).reshape(-1, 3)
    X = np.asarray(points, np.float64).reshape(-1, 3)
    out = np.zeros((len(X), 3))
    for k, (f, x) in enumerate(zip(np.asarray(faces, np.int64).tolist(), X)):
        poly = polys[f]
        n = np.zeros(3)
        if len(poly) == 3:
            a, b, c = C[poly]
            e0, e1, e2 = b - a, c - a, x - a
            d00, d01, d11 = e0 @ e0, e0 @ e1, e1 @ e1
            d20, d21 = e2 @ e0, e2 @ e1
            den = d00 * d11 - d01 * d01
            if den > 0:
                v = (d11 * d20 - d01 * d21) / den
                w = (d00 * d21 - d01 * d20) / den
                bary = np.clip([1.0 - v - w, v, w], 0.0, None)
                n = bary @ V[poly] / max(bary.sum(), 1e-12)
        length = np.linalg.norm(n)
        out[k] = n / length if length > 1e-9 else polygon_normals(C, [poly])[0]
    return out


def conformed(points, p_loc, p_normal, q_loc, q_normal):
    """The points of a colour source carried from one surface onto another: (new (K, 3) m, offsets (K,) m).
    Each point s stands off its nearest point p on the first surface (normal p_normal there) by the offset
    h = (s - p) . p_normal and a remainder r = s - p - h p_normal along the surface; it goes to q + h
    q_normal + r, q being the place on the second surface that corresponds to p (normal q_normal), so a
    decal keeps its lift over a surface that moved, turned or grew under it. Where the two surfaces agree
    (q = p, the same normal) the point stays where it is. points, p_loc, q_loc: (K, 3) m; p_normal,
    q_normal: (K, 3) unit normals."""
    S = np.asarray(points, np.float64).reshape(-1, 3)
    p, q = np.asarray(p_loc, np.float64).reshape(-1, 3), np.asarray(q_loc, np.float64).reshape(-1, 3)
    n_p, n_q = np.asarray(p_normal, np.float64).reshape(-1, 3), np.asarray(q_normal, np.float64).reshape(-1, 3)
    h = ((S - p) * n_p).sum(axis=1)
    return S + (q - p) + h[:, None] * (n_q - n_p), h


def conform_report(before, after, offsets, cage, ray, unmatched=0, unmasked=None):
    """The report of one colour source conformed onto the frozen body (conform_sources): {'vertices',
    'moved': vertices that moved by more than POSITION_STEP, 'max_shift_cm': the farthest one moved (cm,
    rounded to 0.01), 'offset_cm': [lowest, highest] offset of the vertices over the parametric body (cm,
    rounded to 0.01; None without vertices), 'outside_reach': vertices over the source's mask whose offset
    lies outside the bake's reach, above `cage` or below cage - ray (lpk.stages.texture.reach_band's band,
    within POSITION_NOISE of it counted inside): they lay outside it on the parametric body already and do
    not bake wherever they go, 'unmasked': vertices over a part outside the mask, which the bake's reach
    leaves out (lpk.stages.texture.source_reach's rule), 'unmatched': vertices left where they were, their
    part missing on the frozen body}. before, after: (K, 3) m, the vertices; offsets: (K,) m; cage, ray:
    the source's bake reach (m); unmatched: a count; unmasked: (K,) bool, True for a vertex whose nearest
    parametric polygon lies outside the mask, or None for none."""
    a = np.asarray(before, np.float64).reshape(-1, 3)
    b = np.asarray(after, np.float64).reshape(-1, 3)
    h = np.asarray(offsets, np.float64)
    shift = np.linalg.norm(b - a, axis=1)
    noise = checks.POSITION_NOISE
    off = np.zeros(len(h), bool) if unmasked is None else np.asarray(unmasked, bool)
    outside = ((h > cage + noise) | (h < cage - ray - noise)) & ~off
    return {'vertices': int(len(a)), 'moved': int((shift > POSITION_STEP).sum()),
            'max_shift_cm': round(float(shift.max()) * 100, 2) if len(a) else 0.0,
            'offset_cm': [round(float(h.min()) * 100, 2), round(float(h.max()) * 100, 2)] if len(h) else None,
            'outside_reach': int(outside.sum()), 'unmasked': int(off.sum()), 'unmatched': int(unmatched)}


def operation_report(operation, part, before, after, displacement_cm, **extra):
    """The report of a zone operation: {'operation', 'part', 'vertices': [before, after], 'faces': [before,
    after] (the body's), 'max_displacement_cm', and the operation's own keys `extra`}. before, after:
    (vertices, faces)."""
    out = {'operation': operation, 'part': part, 'vertices': [int(before[0]), int(after[0])],
           'faces': [int(before[1]), int(after[1])], 'max_displacement_cm': float(displacement_cm)}
    out.update(extra)
    return out


# -- UVs on the atlas (pure) -----------------------------------------------------------------------------

def corner_faces(loop_start, loop_total):
    """(L,) the polygon of each corner, and (L,) the corner after it in its polygon, for corners listed
    polygon after polygon from loop_start."""
    starts, totals = np.asarray(loop_start, np.int64), np.asarray(loop_total, np.int64)
    n = int((starts + totals).max()) if len(totals) else 0
    face = np.zeros(n, np.int64)
    nxt = np.zeros(n, np.int64)
    for f, (s, t) in enumerate(zip(starts.tolist(), totals.tolist())):
        face[s:s + t] = f
        nxt[s:s + t] = np.roll(np.arange(s, s + t), -1)
    return face, nxt


def edge_corners(loop_start, loop_total, loop_vert):
    """The polygons round each edge, read from the corners: [(lower vertex, higher vertex, [(polygon,
    its corner at the lower vertex, its corner at the higher vertex), ...])], the edges ascending by their
    vertices, the polygons of each in polygon order. An edge is a pair of vertices that follow each other
    round a polygon."""
    face, nxt = corner_faces(loop_start, loop_total)
    lv = np.asarray(loop_vert, np.int64)
    a, b = lv[:len(face)], lv[nxt]
    lo, hi = np.minimum(a, b), np.maximum(a, b)
    keep = lo != hi
    corners = np.arange(len(face))
    la = np.where(a == lo, corners, nxt)[keep]
    lb = np.where(a == lo, nxt, corners)[keep]
    lo, hi, fs = lo[keep], hi[keep], face[keep]
    order = np.lexsort((fs, hi, lo))
    out = []
    prev = None
    for k in order.tolist():
        key = (int(lo[k]), int(hi[k]))
        if key != prev:
            out.append((key[0], key[1], []))
            prev = key
        out[-1][2].append((int(fs[k]), int(la[k]), int(lb[k])))
    return out


def face_neighbours(loop_start, loop_total, loop_vert):
    """[[polygon ids, ascending] per polygon]: the polygons that share an edge with it."""
    nb = [set() for _ in range(len(np.asarray(loop_start)))]
    for _, _, group in edge_corners(loop_start, loop_total, loop_vert):
        ids = sorted({f for f, _, _ in group})
        for f in ids:
            nb[f].update(g for g in ids if g != f)
    return [sorted(x) for x in nb]


def uv_islands(loop_start, loop_total, loop_vert, uv, tol=UV_MATCH):
    """(F,) the UV island of each polygon: polygons join where an edge has exactly two of them and they
    meet in UV, within `tol` UV units, at both its ends. Islands are numbered 0, 1, ... in the order of
    their first polygon. uv: (L, 2) in corner order."""
    U = np.asarray(uv, np.float64).reshape(-1, 2)
    n = len(np.asarray(loop_start))
    par = list(range(n))

    def find(i):
        while par[i] != i:
            par[i] = par[par[i]]
            i = par[i]
        return i
    for _, _, group in edge_corners(loop_start, loop_total, loop_vert):
        if len(group) != 2 or group[0][0] == group[1][0]:
            continue
        (f, a1, b1), (g, a2, b2) = group
        if np.linalg.norm(U[a1] - U[a2]) < tol and np.linalg.norm(U[b1] - U[b2]) < tol:
            x, y = find(f), find(g)
            if x != y:
                par[max(x, y)] = min(x, y)
    ids, out = {}, np.zeros(n, np.int64)
    for f in range(n):
        out[f] = ids.setdefault(find(f), len(ids))
    return out


def face_uv_areas(co, loop_start, loop_total, loop_vert, uv, size):
    """The polygons on the atlas: (tris (T, 3, 2): each polygon's fan of triangles in texels (u times the
    atlas width, v times its height), tri_face (T,): the polygon of each, uv_texels (F,): each polygon's UV
    area in texels squared (its fan triangles' areas, each counted positive), area (F,): its surface area
    in m2 (Newell)). co: (N, 3) m; uv: (L, 2); size: (width, height) texels."""
    C = np.asarray(co, np.float64).reshape(-1, 3)
    U = np.asarray(uv, np.float64).reshape(-1, 2) * np.asarray(size, np.float64)
    lv = np.asarray(loop_vert, np.int64)
    tris, tri_face = [], []
    area = np.zeros(len(np.asarray(loop_start)))
    for f, (s, t) in enumerate(zip(np.asarray(loop_start).tolist(), np.asarray(loop_total).tolist())):
        area[f] = np.linalg.norm(_newell(C[lv[s:s + t]])) / 2 if t >= 3 else 0.0
        for k in range(1, t - 1):
            tris.append((s, s + k, s + k + 1))
            tri_face.append(f)
    tris = U[np.asarray(tris, np.int64).reshape(-1, 3)]
    tri_face = np.asarray(tri_face, np.int64)
    e1, e2 = tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0]
    ta = np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]) / 2
    uv_texels = np.bincount(tri_face, weights=ta, minlength=len(area)) if len(ta) else np.zeros(len(area))
    return tris, tri_face, uv_texels, area


def triangle_depths(A, B):
    """(P,) how far each pair of 2-D triangles interpenetrates: the least overlap of their projections over
    the six edge normals of the two (the separating axis test), in the triangles' units; zero or less
    where they are apart or touch. A, B: (P, 3, 2). An edge of no length gives no axis."""
    A, B = np.asarray(A, np.float64).reshape(-1, 3, 2), np.asarray(B, np.float64).reshape(-1, 3, 2)
    edges = np.concatenate([np.roll(A, -1, axis=1) - A, np.roll(B, -1, axis=1) - B], axis=1)
    axes = np.stack([-edges[..., 1], edges[..., 0]], axis=-1)
    length = np.linalg.norm(axes, axis=-1, keepdims=True)
    axes = np.divide(axes, length, out=np.zeros_like(axes), where=length > 0)
    pa, pb = np.einsum('pkd,pjd->pkj', A, axes), np.einsum('pkd,pjd->pkj', B, axes)
    depth = np.minimum(pa.max(axis=1), pb.max(axis=1)) - np.maximum(pa.min(axis=1), pb.min(axis=1))
    depth = np.where(length[..., 0] > 0, depth, np.inf)
    return depth.min(axis=1) if len(depth) else np.zeros(0)


def _overlaps(tris, tri_face, valid, island, island_part, island_size, size):
    """(F,) bool: the valid polygons whose triangles overlap a triangle of another island of another part
    deeper than OVERLAP_TEXELS, when their own island is no larger (uv_faults)."""
    W, H = size
    cells = {}
    order = [t for t in range(len(tri_face)) if valid[tri_face[t]]]
    for t in order:
        lo = np.clip(np.floor(tris[t].min(axis=0) / OVERLAP_CELL), 0, [W // OVERLAP_CELL, H // OVERLAP_CELL])
        hi = np.clip(np.floor(tris[t].max(axis=0) / OVERLAP_CELL), 0, [W // OVERLAP_CELL, H // OVERLAP_CELL])
        for cx in range(int(lo[0]), int(hi[0]) + 1):
            for cy in range(int(lo[1]), int(hi[1]) + 1):
                cells.setdefault((cx, cy), []).append(t)
    pairs = set()
    for key in sorted(cells):
        ts = cells[key]
        for i, a in enumerate(ts):
            ia = island[tri_face[a]]
            for b in ts[i + 1:]:
                ib = island[tri_face[b]]
                if ia != ib and island_part[ia] != island_part[ib]:
                    pairs.add((a, b))
    out = np.zeros(len(valid), bool)
    if not pairs:
        return out
    P = np.array(sorted(pairs), np.int64)
    deep = triangle_depths(tris[P[:, 0]], tris[P[:, 1]]) > OVERLAP_TEXELS
    for a, b in P[deep].tolist():
        fa, fb = tri_face[a], tri_face[b]
        sa, sb = island_size[island[fa]], island_size[island[fb]]
        if sa <= sb:
            out[fa] = True
        if sb <= sa:
            out[fb] = True
    return out


def uv_faults(co, loop_start, loop_total, loop_vert, uv, face_part, size, skip=(), min_area=0.0):
    """The UV check of a mesh on its atlas, face by face: which polygons' UVs are broken and why.

    co: (N, 3) m; loop_start, loop_total, loop_vert: the mesh's corners; uv: (L, 2) its atlas UVs;
    face_part: the part name of each polygon; size: (width, height) of the atlas in texels; skip: part
    names left out (the `own` parts, which lie outside the atlas); min_area: m2 under which a polygon is
    left out as degenerate (it bakes nothing). The other polygons are checked:
      zero     its UV area is under ZERO_UV_TEXELS texels squared;
      outside  a corner lies outside the atlas, [0, 1] in u or v, by more than UV_MATCH;
      overlap  one of its triangles interpenetrates, deeper than OVERLAP_TEXELS, a triangle of a polygon
               of another UV island (uv_islands) whose part is another (an island's part is the part most
               of its polygons carry, its first polygon's on a tie), and its own island has no more
               polygons than that one: of two overlapping islands the smaller is read as lying on the
               other, and both when they are of one size; polygons with no UV area are left out;
      density  its texels per metre (the square root of its UV area in texels over its surface area)
               differ by more than DENSITY_RATIO, either way, from the median of the other polygons of its
               island and part with a UV area (the median of every polygon of its part when its island
               holds no other; none in a part of one polygon). The median is robust to a minority of
               broken polygons; an island most of whose polygons an edit squashed reads the others.
    Returns {'checked', 'zero', 'outside', 'overlap', 'density': (F,) bool, 'broken': (F,) any of the four,
    'texels_per_m': (F,) NaN where there is no UV area or the polygon is left out, 'ratio': (F,) its
    density over that median, NaN where there is none, 'island': (F,) uv_islands', 'tris',
    'tri_face': face_uv_areas', 'skipped': {'own', 'degenerate': polygons left out}}."""
    tris, tri_face, uvt, area = face_uv_areas(co, loop_start, loop_total, loop_vert, uv, size)
    F = len(area)
    skip = set(skip)
    own = np.array([p in skip for p in face_part], bool).reshape(F)
    checked = ~own & (area >= min_area)
    zero = checked & (uvt < ZERO_UV_TEXELS)
    U = np.asarray(uv, np.float64).reshape(-1, 2)
    face, _ = corner_faces(loop_start, loop_total)
    off = ((U < -UV_MATCH) | (U > 1 + UV_MATCH)).any(axis=1)[:len(face)]
    outside = np.zeros(F, bool)
    np.logical_or.at(outside, face, off)
    outside &= checked
    valid = checked & ~zero
    dens = np.full(F, np.nan)
    dens[valid] = np.sqrt(uvt[valid] / np.maximum(area[valid], 1e-300))
    island = uv_islands(loop_start, loop_total, loop_vert, uv)
    groups, by_part = {}, {}
    for f in np.flatnonzero(valid).tolist():
        groups.setdefault((int(island[f]), face_part[f]), []).append(f)
        by_part.setdefault(face_part[f], []).append(f)
    ratio = np.full(F, np.nan)
    for f in np.flatnonzero(valid).tolist():
        ref = [g for g in groups[(int(island[f]), face_part[f])] if g != f] or \
              [g for g in by_part[face_part[f]] if g != f]
        if ref:
            ratio[f] = dens[f] / float(np.median(dens[ref]))
    density = valid & ~np.isnan(ratio) & ((ratio > DENSITY_RATIO) | (ratio < 1.0 / DENSITY_RATIO))
    n_islands = int(island.max()) + 1 if F else 0
    members = [[] for _ in range(n_islands)]
    for f, i in enumerate(island.tolist()):
        members[i].append(f)
    island_part, island_size = [], []
    for fs in members:
        counts = {}
        for f in fs:
            counts[face_part[f]] = counts.get(face_part[f], 0) + 1
        best = max(counts.values())
        island_part.append(next(face_part[f] for f in fs if counts[face_part[f]] == best))
        island_size.append(len(fs))
    overlap = _overlaps(tris, tri_face, valid, island, island_part, island_size, size)
    return {'checked': checked, 'zero': zero, 'outside': outside, 'overlap': overlap, 'density': density,
            'broken': zero | outside | overlap | density, 'texels_per_m': dens, 'ratio': ratio, 'island': island,
            'tris': tris, 'tri_face': tri_face,
            'skipped': {'own': int(own.sum()), 'degenerate': int((~own & ~checked).sum())}}


def uv_report(faults, face_part, size):
    """The UV check's report from uv_faults' `faults`: {'size': [width, height] texels, 'faces': polygons
    checked, 'broken': polygons with any fault, 'texels_per_m': the median texels per metre of the checked
    polygons with a UV area (None without any), 'skipped': uv_faults' counts, 'parts': {part: {'faces': its
    checked polygons, 'broken': its polygons with any fault, 'zero', 'outside', 'overlap', 'density': its
    polygons with that fault, 'ratio': the density ratio of each 'density' polygon, rounded to 0.01}} for the
    parts with a broken polygon, by name}. Polygon ids are the mesh's, ascending. face_part: the part name
    of each polygon; size: (width, height)."""
    dens = faults['texels_per_m'][~np.isnan(faults['texels_per_m'])]
    parts = {}
    for name in sorted({face_part[f] for f in np.flatnonzero(faults['broken']).tolist()}):
        mine = np.array([p == name for p in face_part], bool)
        entry = {'faces': int((mine & faults['checked']).sum()),
                 'broken': np.flatnonzero(mine & faults['broken']).tolist()}
        for key in ('zero', 'outside', 'overlap', 'density'):
            entry[key] = np.flatnonzero(mine & faults[key]).tolist()
        entry['ratio'] = [round(float(faults['ratio'][f]), 2) for f in entry['density']]
        parts[name] = entry
    return {'size': [int(size[0]), int(size[1])], 'faces': int(faults['checked'].sum()),
            'broken': int(faults['broken'].sum()),
            'texels_per_m': round(float(np.median(dens)), 1) if len(dens) else None,
            'skipped': dict(faults['skipped']), 'parts': parts}


def part_densities(faults, face_part, faces):
    """{part: texels per metre} the repair lays the polygons `faces` out at: the median texels per metre of
    the part's checked polygons with a UV area outside `faces`, else of every such polygon of the mesh.
    Raises ValueError when no polygon outside `faces` has a UV area."""
    dens = faults['texels_per_m']
    out_of = np.ones(len(dens), bool)
    out_of[list(faces)] = False
    intact = out_of & ~np.isnan(dens)
    if not intact.any():
        raise ValueError('the UV repair needs a texel density: no face outside the broken ones has a UV area')
    every = float(np.median(dens[intact]))
    out = {}
    for name in sorted({face_part[f] for f in faces}):
        mine = intact & np.array([p == name for p in face_part], bool)
        out[name] = float(np.median(dens[mine])) if mine.any() else every
    return out


def uv_charts(faces, normals, neighbours, face_part, cos=REPAIR_CHART_COS):
    """The repair's charts: the polygons `faces` grown into pieces, each from its lowest polygon not taken
    yet, over shared edges (neighbours: face_neighbours'), in ascending order breadth first, taking a
    neighbour of `faces` of the same part whose normal has a cosine of at least `cos` with the first
    polygon's. normals: (F, 3) unit normals (polygon_normals). Returns [[polygon ids, ascending], ...] in
    the order of their first polygon."""
    todo = set(int(f) for f in faces)
    taken = set()
    out = []
    N = np.asarray(normals, np.float64).reshape(-1, 3)
    for f in sorted(todo):
        if f in taken:
            continue
        taken.add(f)
        chart, queue, k = [f], [f], 0
        while k < len(queue):
            g = queue[k]
            k += 1
            for h in neighbours[g]:
                if h in todo and h not in taken and face_part[h] == face_part[f] and float(N[h] @ N[f]) >= cos:
                    taken.add(h)
                    chart.append(h)
                    queue.append(h)
        out.append(sorted(chart))
    return out


def chart_flat(chart, co, polys, normal):
    """{polygon: (K, 2) its corners in metres} of a chart projected flat along `normal` (the unit normal of
    its first polygon): the first axis along the first polygon's first edge, the second the normal crossed
    with it, so a polygon facing the normal keeps its corners' turn; shifted so the smallest coordinates
    are 0."""
    C = np.asarray(co, np.float64).reshape(-1, 3)
    n = np.asarray(normal, np.float64)
    p0 = polys[chart[0]]
    e1 = C[p0[1]] - C[p0[0]]
    e1 = e1 - (e1 @ n) * n
    if np.linalg.norm(e1) == 0:
        e1 = np.cross(n, [1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.cross(n, [0.0, 1.0, 0.0])
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(n, e1)
    flat = {f: np.stack([C[polys[f]] @ e1, C[polys[f]] @ e2], axis=1) for f in chart}
    lo = np.min([q.min(axis=0) for q in flat.values()], axis=0)
    return {f: q - lo for f, q in flat.items()}


def uv_repair_layout(co, loop_start, loop_total, loop_vert, faces, face_part, densities, occupied, size, margin,
                     cos=REPAIR_CHART_COS):
    """New UVs for the polygons `faces` as new islands in free atlas space; no other polygon's UVs change.

    The polygons are grown into charts (uv_charts), each projected flat (chart_flat) at its part's texels
    per metre `densities` ({part: texels per metre}, part_densities). Each chart takes a cell of whole
    texels: its extent rounded up plus one, and `margin` texels on every side for the bake margin round it;
    the cells are placed, the largest first (then by first polygon), at the lowest, then leftmost, free
    place of `occupied` ((H, W) bool, True where a texel is taken: the other islands and their bake
    margin), each taking its cell before the next is placed (lpk.stages.imaging.place_rects); a chart lies
    half a texel inside its cell's margin. co: (N, 3) m; face_part: the part name of each polygon; size:
    (width, height) texels; margin: texels.

    Returns {'uv': {polygon: (K, 2) its new corner UVs, for the placed charts}, 'charts': [{'part',
    'faces', 'size': [width, height] in texels, rounded to 0.1, 'texels_per_m', 'cell': [column, row, width,
    height] or None when no free place holds it}], in chart order, 'cells': (H, W) bool, the placed cells,
    'placed': whether every chart found a place}."""
    polys = polygons(loop_start, loop_total, loop_vert)
    normals = polygon_normals(co, polys)
    charts = uv_charts(faces, normals, face_neighbours(loop_start, loop_total, loop_vert), face_part, cos)
    W, H = int(size[0]), int(size[1])
    laid = []
    for chart in charts:
        tpm = float(densities[face_part[chart[0]]])
        flat = {f: q * tpm for f, q in chart_flat(chart, co, polys, normals[chart[0]]).items()}
        extent = np.max([q.max(axis=0) for q in flat.values()], axis=0)
        laid.append((chart, tpm, flat, extent))
    order = sorted(range(len(laid)), key=lambda k: (-float(laid[k][3][0] * laid[k][3][1]), laid[k][0][0]))
    cells = [(int(np.ceil(laid[k][3][0])) + 1 + 2 * margin, int(np.ceil(laid[k][3][1])) + 1 + 2 * margin)
             for k in order]
    spots, taken = imaging.place_rects(cells, occupied)
    uv, report = {}, [None] * len(laid)
    for k, spot, cell in zip(order, spots, cells):
        chart, tpm, flat, extent = laid[k]
        report[k] = {'part': face_part[chart[0]], 'faces': list(chart),
                     'size': [round(float(x), 1) for x in extent], 'texels_per_m': round(tpm, 1),
                     'cell': None if spot is None else [int(spot[0]), int(spot[1]), int(cell[0]), int(cell[1])]}
        if spot is None:
            continue
        origin = np.array([spot[0] + margin + 0.5, spot[1] + margin + 0.5])
        for f, q in flat.items():
            uv[f] = (q + origin) / np.array([W, H], np.float64)
    return {'uv': uv, 'charts': report, 'cells': taken, 'placed': all(s is not None for s in spots)}


# -- Blender readers and writers -------------------------------------------------------------------------

def read(me):
    """A mesh's arrays: {'co': (N, 3) float64 object-space positions (float32 widened), 'loop_start',
    'loop_total', 'loop_vert', 'edges': (E, 2), 'polys': polygons(), 'part': (N,) or None, 'pal': (F,)
    or None, 'join_loop': (N,) or None (an int attribute of that name on its domain, else None)}."""
    from lpk.forms import joins
    n, nl, nf, ne = len(me.vertices), len(me.loops), len(me.polygons), len(me.edges)
    co = np.empty(n * 3, np.float32)
    me.vertices.foreach_get('co', co)
    lv = np.empty(nl, np.int32)
    me.loops.foreach_get('vertex_index', lv)
    ls, lt = np.empty(nf, np.int32), np.empty(nf, np.int32)
    me.polygons.foreach_get('loop_start', ls)
    me.polygons.foreach_get('loop_total', lt)
    ev = np.empty(ne * 2, np.int32)
    me.edges.foreach_get('vertices', ev)
    out = {'co': co.reshape(n, 3).astype(np.float64), 'loop_start': ls, 'loop_total': lt, 'loop_vert': lv,
           'edges': ev.reshape(ne, 2), 'polys': polygons(ls, lt, lv)}
    for name, domain, size in (('part', 'POINT', n), ('pal', 'FACE', nf), (joins.LAYER, 'POINT', n)):
        a = me.attributes.get(name)
        if a is None or a.domain != domain or a.data_type != 'INT':
            out[name] = None
            continue
        v = np.empty(size, np.int32)
        a.data.foreach_get('value', v)
        out[name] = v.astype(np.int64)
    return out


def object_mode(ob):
    """Leave Edit Mode on the object `ob` so its mesh holds the edit (Blender keeps an Edit Mode edit in
    the edit mesh until then, and writes the edit mesh back over the data on leaving). Returns the mode it
    was in. Raises RuntimeError naming the object when Blender refuses the switch (no window to run the
    operator in): leave Edit Mode by hand, then call again."""
    import bpy
    prev = ob.mode
    if prev == 'OBJECT':
        return prev
    try:
        bpy.context.view_layer.objects.active = ob
        with bpy.context.temp_override(active_object=ob, object=ob):
            bpy.ops.object.mode_set(mode='OBJECT')
    except RuntimeError as e:
        raise RuntimeError('%s is in %s mode and Blender refused to leave it (%s): switch to Object Mode, '
                           'then call again' % (ob.name, prev, e))
    return prev


def restore_mode(ob, mode):
    """Put the object `ob` back into `mode` (object_mode's return value), for the human to go on editing."""
    import bpy
    if mode != 'OBJECT' and ob.mode != mode:
        bpy.context.view_layer.objects.active = ob
        with bpy.context.temp_override(active_object=ob, object=ob):
            bpy.ops.object.mode_set(mode=mode)


def read_uv(me, layer):
    """The UV layer `layer` of the mesh `me` as float32 (L, 2) in loop order, None without it."""
    if layer not in me.uv_layers:
        return None
    uv = np.empty(len(me.loops) * 2, np.float32)
    me.uv_layers[layer].uv.foreach_get('vector', uv)
    return uv.reshape(-1, 2)


def stamp(obj_name):
    """Write the build stamp on the object `obj_name`: STAMP_TOPOLOGY and STAMP_POSITIONS of its mesh as
    it stands (after object_mode), and STAMP_UV of its atlas UV layer (lpk.stages.texture.UV_LAYER), removed
    without one. Returns {'topology', 'positions', 'uv': the UV digest or None}."""
    import bpy
    from lpk.stages import texture
    ob = bpy.data.objects[obj_name]
    object_mode(ob)
    A = read(ob.data)
    key = topology_key(len(A['co']), A['loop_total'], A['loop_vert'])
    digest = position_digest(A['co'])
    ob[STAMP_TOPOLOGY], ob[STAMP_POSITIONS] = key, digest
    uv = read_uv(ob.data, texture.UV_LAYER)
    if uv is None:
        if STAMP_UV in ob:
            del ob[STAMP_UV]
        return {'topology': key, 'positions': digest, 'uv': None}
    ob[STAMP_UV] = uv_digest(uv)
    return {'topology': key, 'positions': digest, 'uv': ob[STAMP_UV]}


def unstamp_uv(obj_name):
    """Remove the UV digest from the build stamp of the object `obj_name`: the unwrap and the pack of a
    procedural texture rewrite the UVs, which are then the kit's and not a hand edit to keep. Returns
    whether a digest was there."""
    import bpy
    ob = bpy.data.objects[obj_name]
    if STAMP_UV not in ob:
        return False
    del ob[STAMP_UV]
    return True


def edited(obj_name, uvs=False):
    """How the object `obj_name`'s mesh differs from its build stamp (after object_mode): None when it
    matches, 'unstamped' when it carries no stamp, 'topology' when its topology key differs, 'positions'
    when only the vertex positions do, and with uvs=True 'uv' when only its atlas UVs differ from a stamped
    UV digest (a stamp without one, or a mesh without the layer, reads no UV change). uvs: True under a
    frozen texture, where nothing of the kit changes the UVs after the build; with a procedural texture the
    unwrap changes them, and the digest is not read."""
    import bpy
    from lpk.stages import texture
    ob = bpy.data.objects[obj_name]
    object_mode(ob)
    if STAMP_TOPOLOGY not in ob or STAMP_POSITIONS not in ob:
        return 'unstamped'
    A = read(ob.data)
    if topology_key(len(A['co']), A['loop_total'], A['loop_vert']) != ob[STAMP_TOPOLOGY]:
        return 'topology'
    if position_digest(A['co']) != ob[STAMP_POSITIONS]:
        return 'positions'
    if uvs and STAMP_UV in ob:
        uv = read_uv(ob.data, texture.UV_LAYER)
        if uv is not None and uv_digest(uv) != ob[STAMP_UV]:
            return 'uv'
    return None


def _set_int(me, name, domain, values):
    a = me.attributes.get(name)
    if a is not None and (a.domain != domain or a.data_type != 'INT'):
        me.attributes.remove(a)
        a = None
    if a is None:
        a = me.attributes.new(name, 'INT', domain)
    a.data.foreach_set('value', np.asarray(values, np.int32))


def write_zones(me, part, pal, join_loop=None):
    """Write the zone layers on the mesh `me`: 'part' (POINT), 'pal' (FACE) and, when given, 'join_loop'
    (POINT), int attributes made or replaced. part: (N,); pal: (F,); join_loop: (N,) or None."""
    from lpk.forms import joins
    _set_int(me, 'part', 'POINT', part)
    _set_int(me, 'pal', 'FACE', pal)
    if join_loop is not None:
        _set_int(me, joins.LAYER, 'POINT', join_loop)


def triangulate(me):
    """Triangulate the polygons of the mesh `me` with more than three corners in place, as
    lpk.core.builder.finish does (lpk.core.edits.triangulate): each triangle keeps its polygon's face
    attributes and corner data. Returns the number of polygons split."""
    import bmesh
    from lpk.core import edits
    if not any(p.loop_total > 3 for p in me.polygons):
        return 0
    bm = bmesh.new()
    bm.from_mesh(me)
    split = sum(1 for f in bm.faces if len(f.verts) > 3)
    edits.triangulate(bm, bm.faces[:])
    bm.to_mesh(me)
    bm.free()
    me.update()
    return split


def _strip(bm, uv=None):
    """Remove from a bmesh every data layer but the zone layers and the UV layer `uv` (None: none), and its
    seams, selection, hiding and material slots: the frozen mesh's geometry."""
    from lpk.forms import joins
    keep = {('verts', 'int', 'part'), ('verts', 'int', joins.LAYER), ('faces', 'int', 'pal')}
    if uv is not None:
        keep.add(('loops', 'uv', uv))
    for domain in ('verts', 'edges', 'faces', 'loops'):
        layers = getattr(bm, domain).layers
        for kind in [k for k in dir(layers) if not k.startswith('_')]:
            coll = getattr(layers, kind)
            if not hasattr(coll, 'remove'):
                continue
            for name in list(coll.keys()):
                if (domain, kind, name) not in keep:
                    coll.remove(coll[name])
    for e in bm.edges:
        e.seam = False
    for seq in (bm.verts, bm.edges, bm.faces):
        for x in seq:
            x.select = False
            x.hide = False
    for f in bm.faces:
        f.material_index = 0


def store(bm, frozen_name, parts, palette, marks=None, uv=None):
    """The frozen mesh `frozen_name` (replacing a mesh of that name) from the bmesh `bm`, stripped of
    every layer but the zone layers and the UV layer `uv` (None: no UVs; the frozen texture's layer
    otherwise), and of seams, selection and material slots, with a fake user so a saved .blend keeps it,
    and the custom properties 'parts', 'palette' and, when `marks` (MARKS' JSON text) is given,
    lpk.stages.texture.MARKS. The bmesh is changed and not freed. Raises ValueError when `uv` is given and
    the bmesh has no such layer. Returns the mesh."""
    import bpy
    from lpk.stages import texture
    if uv is not None and uv not in bm.loops.layers.uv.keys():
        raise ValueError('the mesh to freeze has no UV layer %s for the frozen texture' % uv)
    _strip(bm, uv)
    old = bpy.data.meshes.get(frozen_name)
    if old is not None:
        bpy.data.meshes.remove(old)
    me = bpy.data.meshes.new(frozen_name)
    bm.to_mesh(me)
    me.use_fake_user = True
    me['parts'] = list(parts)
    me['palette'] = list(palette)
    if marks:
        me[texture.MARKS] = marks
    return me


def reference_object(frozen_name, obj_name):
    """An object `obj_name` over a copy of the frozen mesh `frozen_name`, linked to no collection, with the
    mesh's 'parts', 'palette' and marks as its properties: a reference the zone tools read by object name,
    which outlives a store that replaces the frozen mesh. Remove the object and its mesh after use. Raises
    ValueError when the frozen mesh is missing."""
    import bpy
    from lpk.stages import texture
    me = bpy.data.meshes.get(frozen_name)
    if me is None:
        raise ValueError('no frozen mesh %s in the open .blend: run freeze or adopt first' % frozen_name)
    old = bpy.data.objects.get(obj_name)
    if old is not None:
        bpy.data.objects.remove(old, do_unlink=True)
    ob = bpy.data.objects.new(obj_name, me.copy())
    ob.data.use_fake_user = False
    for key in ('parts', 'palette', texture.MARKS):
        if key in me:
            ob[key] = me[key]
    return ob


def _bvh(co, polys):
    from mathutils.bvhtree import BVHTree
    return BVHTree.FromPolygons([tuple(p) for p in np.asarray(co, np.float64).tolist()], polys, all_triangles=False)


def _nearest(tree, points):
    """(face ids, locations, distances) of the nearest surface point of `tree` to each point."""
    faces, locs, dists = [], [], []
    for p in np.asarray(points, np.float64).reshape(-1, 3).tolist():
        loc, _, idx, dist = tree.find_nearest(p)
        faces.append(idx)
        locs.append(tuple(loc))
        dists.append(dist)
    return np.asarray(faces, np.int64), np.asarray(locs, np.float64).reshape(-1, 3), np.asarray(dists, np.float64)


def transfer(A, R):
    """The zone layers of the mesh arrays `A` (read) taken from the reference arrays `R` by the nearest
    surface: each vertex the part of the nearest corner of its nearest reference face
    (nearest_corner_parts), each face the 'pal' of the reference face nearest its centre (the mean of its
    vertices), each vertex 'join_loop' 1 within JOIN_TOLERANCE of a tagged reference vertex (join_tags).
    The nearest face is BVHTree.find_nearest's over the reference's polygons, the same for the same
    meshes. Returns {'part': (N,), 'pal': (F,), 'join_loop': (N,) or None when R has no such layer,
    'dist': (N,) metres from each vertex to the reference surface}."""
    if R['part'] is None or R['pal'] is None:
        raise ValueError('the reference has no part or pal layer to take the zones from')
    tree = _bvh(R['co'], R['polys'])
    faces, locs, dist = _nearest(tree, A['co'])
    part = nearest_corner_parts(faces, locs, R['co'], R['polys'], R['part'])
    centres = np.array([A['co'][p].mean(axis=0) for p in A['polys']]).reshape(-1, 3)
    cfaces = _nearest(tree, centres)[0]
    pal = R['pal'][cfaces] if len(cfaces) else np.zeros(0, np.int64)
    join = None if R['join_loop'] is None else join_tags(A['co'], R['co'], R['join_loop'])
    return {'part': part, 'pal': pal, 'join_loop': join, 'dist': dist}


def freeze(obj_name, frozen_name, reference=None, uv=None):
    """Store the body `obj_name` as it stands as the frozen mesh `frozen_name` (store) with its zone
    layers. The body is first put in Object Mode (object_mode) and triangulated in place (triangulate),
    so the frozen mesh is made of triangles as a built body is. reference: None when the body's topology
    is the one the kit wrote (its build stamp matches): its own layers, which no topology operator has
    interpolated, are kept as they are; else the name of an object holding the zones the edit started
    from (the frozen mesh before it, or a fresh parametric build): the layers are taken from it by the
    nearest surface (transfer) and written back on the body, with its 'parts', 'palette' and marks. The
    body keeps its UVs and other layers; the frozen mesh has none but the UV layer `uv` when given (the
    frozen texture's, lpk.stages.texture.UV_LAYER: the body's UVs as they stand, through whatever the edit
    did to them).

    Returns {'vertices', 'faces': the body's after triangulating, 'triangulated': polygons split,
    'topology_changed': whether a reference was used, 'parts': {part: vertices}, 'far': {part: vertices
    farther than FAR_TOLERANCE from the reference surface}, 'far_max_cm': {part: the farthest of them}
    (both empty without a reference), 'changed': {'part': {part: vertices whose part name differs from the
    one the layer held before the call, which a topology operator may have interpolated}, 'pal': {palette
    name: faces alike}}, 'join_loop': {'reference': tagged reference vertices, 'tagged': tagged body
    vertices}}. Raises ValueError when the body (without a reference) or the reference lacks the 'part'
    or 'pal' layer or the 'parts' and 'palette' properties, and when the body lacks the UV layer `uv`."""
    import bmesh
    import bpy
    from lpk.stages import texture
    ob = bpy.data.objects[obj_name]
    object_mode(ob)
    if uv is not None and uv not in ob.data.uv_layers:
        raise ValueError('%s has no UV layer %s to store with the frozen texture' % (obj_name, uv))
    split = triangulate(ob.data)
    A = read(ob.data)
    src = ob if reference is None else bpy.data.objects[reference]
    for key in ('parts', 'palette'):
        if key not in src:
            raise ValueError('%s has no %r property: its zones cannot be read' % (src.name, key))
    old_parts, old_palette = list(ob.get('parts', [])), list(ob.get('palette', []))
    parts, palette = list(src['parts']), list(src['palette'])
    marks = src.get(texture.MARKS)
    if reference is None:
        if A['part'] is None or A['pal'] is None:
            raise ValueError('%s has no part or pal layer: freeze it against a reference' % obj_name)
        z = {'part': A['part'], 'pal': A['pal'], 'join_loop': A['join_loop'], 'dist': np.zeros(len(A['co']))}
        ref_tagged = None if A['join_loop'] is None else int(A['join_loop'].sum())
    else:
        R = read(src.data)
        z = transfer(A, R)
        ref_tagged = None if R['join_loop'] is None else int(R['join_loop'].sum())
    changed = {'part': changed_counts(A['part'], old_parts, z['part'], parts),
               'pal': changed_counts(A['pal'], old_palette, z['pal'], palette)}
    write_zones(ob.data, z['part'], z['pal'], z['join_loop'])
    ob['parts'], ob['palette'] = parts, palette
    if marks:
        ob[texture.MARKS] = marks
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    store(bm, frozen_name, parts, palette, marks, uv)
    bm.free()
    far, worst = far_counts(z['dist'], z['part'], parts) if reference is not None else ({}, {})
    return {'vertices': len(A['co']), 'faces': len(A['polys']), 'triangulated': split,
            'topology_changed': reference is not None, 'parts': name_counts(z['part'], parts), 'far': far,
            'far_max_cm': worst, 'changed': changed,
            'join_loop': {'reference': ref_tagged, 'tagged': None if z['join_loop'] is None
                          else int(np.asarray(z['join_loop']).sum())}}


def store_uv(obj_name, frozen_name, layer):
    """The UV layer `layer` of the body `obj_name` (after object_mode), as it stands, written onto the
    frozen mesh `frozen_name` under the same name, loop by loop, replacing the layer there: the frozen
    texture's UVs, which body_from_frozen's copy brings back. The body must be the frozen mesh's topology
    (a frozen build, or the body freeze just stored). Returns {'layer', 'loops', 'uv': the UV digest}.
    Raises ValueError when the frozen mesh or the body's layer is missing, and when the body's topology
    differs from the frozen mesh's (store the mesh edit with freeze first)."""
    import bpy
    ob = bpy.data.objects[obj_name]
    object_mode(ob)
    me = bpy.data.meshes.get(frozen_name)
    if me is None:
        raise ValueError('no frozen mesh %s in the open .blend: run freeze or adopt first' % frozen_name)
    uv = read_uv(ob.data, layer)
    if uv is None:
        raise ValueError('%s has no UV layer %s: run unwrap, pack and bake first' % (obj_name, layer))
    A, R = read(ob.data), read(me)
    if (topology_key(len(A['co']), A['loop_total'], A['loop_vert'])
            != topology_key(len(R['co']), R['loop_total'], R['loop_vert'])):
        raise ValueError('the body %s is not the topology of the frozen mesh %s: run freeze to store the mesh '
                         'edit first' % (obj_name, frozen_name))
    if layer in me.uv_layers:
        me.uv_layers.remove(me.uv_layers[layer])
    me.uv_layers.new(name=layer)
    me.uv_layers[layer].uv.foreach_set('vector', uv.ravel())
    me.update()
    return {'layer': layer, 'loops': int(len(uv)), 'uv': uv_digest(uv)}


def drop_uv(frozen_name, layer):
    """Remove the UV layer `layer` from the frozen mesh `frozen_name`. Returns the layer's name when it
    was there, else None (also without the frozen mesh)."""
    import bpy
    me = bpy.data.meshes.get(frozen_name)
    if me is None or layer not in me.uv_layers:
        return None
    me.uv_layers.remove(me.uv_layers[layer])
    return layer


def base_image(material):
    """The image an Image Texture node feeds straight into the Base Color of a material's Principled BSDF,
    else None (no node tree, no such link, or a link through other nodes)."""
    tree = getattr(material, 'node_tree', None) if material is not None else None
    if tree is None:
        return None
    for node in tree.nodes:
        if node.type == 'BSDF_PRINCIPLED':
            socket = node.inputs.get('Base Color')
            if socket is None or not socket.is_linked:
                return None
            src = socket.links[0].from_node
            return src.image if src.type == 'TEX_IMAGE' else None
    return None


def image_srgb(img):
    """The image's pixels as float64 (H, W, 3) sRGB in Blender's order (row 0 at the bottom): a byte
    image's levels as they are, a float image's linear values converted (linear_to_srgb) unless its colour
    space is sRGB already."""
    w, h = img.size
    px = np.empty(w * h * img.channels, np.float32)
    img.pixels.foreach_get(px)
    px = px.reshape(h, w, img.channels).astype(np.float64)
    rgb = px[..., :3] if img.channels >= 3 else np.repeat(px[..., :1], 3, axis=2)
    if img.is_float and img.colorspace_settings.name != 'sRGB':
        lin = np.clip(rgb, 0.0, 1.0)
        rgb = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * lin ** (1 / 2.4) - 0.055)
    return rgb


def _material_colour(material):
    """A material's flat base colour as sRGB: the Principled BSDF's Base Color when nothing is linked into
    it, else (no node tree) its viewport colour; None when the base colour comes from a texture or the
    material has none."""
    if material is None:
        return None
    tree = getattr(material, 'node_tree', None)
    if tree is not None:
        for node in tree.nodes:
            if node.type == 'BSDF_PRINCIPLED':
                socket = node.inputs.get('Base Color')
                if socket is None or socket.is_linked:
                    return None
                return linear_to_srgb(tuple(socket.default_value))
        return None
    return linear_to_srgb(tuple(material.diffuse_color))


def _face_colours(me):
    """[sRGB or None] per polygon: the mean of the 'Col' colour attribute (else the active one) over
    its corners or vertices; all None without a colour attribute."""
    col = me.color_attributes.get('Col') or me.color_attributes.active_color
    if col is None:
        return [None] * len(me.polygons)
    out = []
    for p in me.polygons:
        ids = p.loop_indices if col.domain == 'CORNER' else p.vertices
        c = np.mean([tuple(col.data[i].color)[:3] for i in ids], axis=0)
        out.append(linear_to_srgb(c))
    return out


def adopt(obj_name, frozen_name, part_names, palette, blocks=None, texture=None):
    """The frozen mesh `frozen_name` (store) made from another mesh object `obj_name`, an existing
    model: its mesh data (modifiers not applied) in world space (the object's transform applied),
    triangulated as finish does, with zone layers decided here:
      part   a vertex in vertex groups named like one of `part_names` takes the one of highest weight
             (strongest_group); else, when one of its faces' materials is named like a part, the part of
             the first such face in face order; else the part of the nearest block of `blocks`
             (lpk.stages.blocks.make over `palette`, the part of the block face nearest the vertex);
      pal    a face whose material has a flat base colour (_material_colour) takes the palette colour
             nearest it (nearest_colour, RGB distance in sRGB); else, when the mesh is textured (below),
             one whose material shows the image takes the colour nearest the image's texel under the
             centre of its triangle's UVs (lpk.stages.imaging.texels_at); else one with a colour
             attribute ('Col', else the active one) the colour nearest its mean; else the first palette
             colour;
      join_loop  0 on every vertex: an adopted mesh has no welded hole loops, so the join smoothing
             (lpk.stages.rig.join_zones) finds no loop vertices.
    part_names: the part names a group or material may carry, in the order 'parts' lists them; palette:
    {name: sRGB}, whose order is 'palette'; blocks: the model's blocks(P) list, or None. The object is
    not changed.

    texture: the name of the frozen texture's image ('<NAME>_AtlasFrozen'), or None to leave textures
    alone. With it, a mesh with a UV map (its active render layer) whose materials show one image on their
    Base Color (base_image; every material that shows one shows the same) is textured: the frozen mesh
    keeps that UV map as lpk.stages.texture.UV_LAYER and the image is stored as `texture`
    (lpk.stages.texture.store_image), the frozen texture of the adopted model. Several images, or none,
    store no texture; one image over part of the faces stores it, and the faces of materials without it
    keep their UVs but no texels of their own.

    Returns {'object': obj_name, 'vertices', 'faces', 'parts': {part: vertices}, 'zones': {'vertex_group',
    'material', 'blocks': vertices whose part each source decided}, 'decided': {part: {source: its
    vertices}}, 'pal': {'material', 'texture', 'colour', 'first': faces each source decided}, 'join_loop': 0,
    'texture': None when no texture is stored, else {'image': the adopted image's name, 'uv_layer': the
    adopted UV map's name, 'textured_faces': faces whose material shows the image, 'stored':
    store_image's report}}. Raises ValueError when obj_name is not a mesh object, and when vertices need
    the blocks and `blocks` is None or empty."""
    import bmesh
    import bpy
    from lpk.core import edits
    from lpk.forms import joins
    from lpk.stages import imaging
    from lpk.stages import texture as texture_mod
    src = bpy.data.objects.get(obj_name)
    if src is None or src.type != 'MESH':
        raise ValueError('adopt: %r is no mesh object in the scene' % obj_name)
    names = list(dict.fromkeys(part_names))
    me = src.data
    groups = {g.index: g.name for g in src.vertex_groups if g.name in names}
    v_group = [strongest_group([(g.group, g.weight) for g in v.groups], groups) for v in me.vertices]
    mats = [m.name if m is not None else None for m in me.materials]
    f_part = [mats[p.material_index] if p.material_index < len(mats) and mats[p.material_index] in names else None
              for p in me.polygons]
    mat_colour = [_material_colour(m) for m in me.materials]
    mat_image = [base_image(m) for m in me.materials]
    images = list(dict.fromkeys(i for i in mat_image if i is not None))
    uv_name = None
    if texture is not None and len(images) == 1 and len(me.uv_layers):
        uv_name = next((u.name for u in me.uv_layers if u.active_render), me.uv_layers.active.name)
    image = images[0] if uv_name is not None else None
    f_colour = _face_colours(me)
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.transform(src.matrix_world)
    # Per-face data before triangulating, kept on the faces through it in an int layer.
    order = bm.faces.layers.int.new('_lpk_face')
    for f in bm.faces:
        f[order] = f.index
    edits.triangulate(bm, bm.faces[:])
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    used = ['']
    vpart = np.zeros(len(bm.verts), np.int64)
    source = {'vertex_group': 0, 'material': 0, 'blocks': 0}
    how_of = [None] * len(bm.verts)
    pending = []
    for v in bm.verts:
        name = groups.get(v_group[v.index])
        how = 'vertex_group'
        if name is None:
            hits = sorted(f[order] for f in v.link_faces if f_part[f[order]] is not None)
            name, how = (f_part[hits[0]], 'material') if hits else (None, None)
        if name is None:
            pending.append(v.index)
            continue
        vpart[v.index] = names.index(name) + 1
        source[how] += 1
        how_of[v.index] = how
    if pending:
        if not blocks:
            raise ValueError('adopt: %d vertices of %s are in no vertex group and on no material named like a '
                             'part, and the model gives no blocks(P) to place them by' % (len(pending), obj_name))
        from mathutils.bvhtree import BVHTree
        from lpk.stages import blocks as blocks_mod
        bb = blocks_mod.make(blocks, palette)
        tree = BVHTree.FromBMesh(bb.bm)
        bb.bm.faces.ensure_lookup_table()
        for i in pending:
            _, _, idx, _ = tree.find_nearest(bm.verts[i].co)
            name = bb.parts[bb.bm.faces[idx].verts[0][bb.vpart]]
            if name not in names:
                names.append(name)
            vpart[i] = names.index(name) + 1
            source['blocks'] += 1
            how_of[i] = 'blocks'
        bb.bm.free()
    present = sorted(set(vpart.tolist()))
    used += [names[i - 1] for i in present]
    remap = {old: new for new, old in enumerate([0] + present)}
    vpart = np.array([remap[i] for i in vpart.tolist()], np.int64)
    keys = list(palette)
    pal = np.zeros(len(bm.faces), np.int64)
    how_pal = {'material': 0, 'texture': 0, 'colour': 0, 'first': 0}
    sampled = {}
    if image is not None:
        uvl = bm.loops.layers.uv[uv_name]
        slot = [me.polygons[f[order]].material_index for f in bm.faces]
        shown = [f for f, i in zip(bm.faces, slot) if i < len(mat_image) and mat_image[i] == image]
        centres = np.array([np.mean([tuple(l[uvl].uv) for l in f.loops], axis=0) for f in shown]).reshape(-1, 2)
        texels = imaging.texels_at(image_srgb(image), centres) if len(shown) else np.zeros((0, 3))
        sampled = {f.index: tuple(t) for f, t in zip(shown, texels.tolist())}
    for f in bm.faces:
        k = f[order]
        c = mat_colour[me.polygons[k].material_index] if me.polygons[k].material_index < len(mat_colour) else None
        how = 'material'
        if c is None and f.index in sampled:
            c, how = sampled[f.index], 'texture'
        if c is None:
            c, how = f_colour[k], 'colour'
        if c is None:
            pal[f.index], how = 0, 'first'
        else:
            pal[f.index] = nearest_colour(c, palette)
        how_pal[how] += 1
    bm.faces.layers.int.remove(order)
    for seq, name, values in ((bm.verts, 'part', vpart), (bm.faces, 'pal', pal),
                              (bm.verts, joins.LAYER, np.zeros(len(bm.verts), np.int64))):
        layer = seq.layers.int.get(name)
        if layer is None:
            layer = seq.layers.int.new(name)
        for x, val in zip(seq, values.tolist()):
            x[layer] = val
    decided = {}
    for pid, how in zip(vpart.tolist(), how_of):
        entry = decided.setdefault(used[pid], {})
        entry[how] = entry.get(how, 0) + 1
    n_verts, n_faces = len(bm.verts), len(bm.faces)
    frozen = store(bm, frozen_name, used, keys, uv=uv_name)
    bm.free()
    textured = None
    if image is not None:
        frozen.uv_layers[uv_name].name = texture_mod.UV_LAYER
        textured = {'image': image.name, 'uv_layer': uv_name, 'textured_faces': len(sampled),
                    'stored': texture_mod.store_image(image.name, texture)}
    return {'object': obj_name, 'vertices': n_verts, 'faces': n_faces, 'parts': name_counts(vpart, used),
            'zones': source, 'decided': {nm: decided[nm] for nm in used if nm in decided}, 'pal': how_pal,
            'join_loop': 0, 'texture': textured}


def body_from_frozen(frozen_name, obj_name, collection, colours):
    """The body object `obj_name` made from the frozen mesh `frozen_name`: a copy of the mesh (the frozen
    mesh stays as it is), replacing the object and linked into `collection` as
    lpk.core.builder.finish does (replace_object), its 'Col' corner colours from its 'pal' layer over
    `colours` ({name: sRGB}, paint_corners), its 'parts', 'palette' and marks from the mesh's properties.
    Returns (the object, lpk.core.builder.body_report's report). Raises ValueError when the frozen mesh is
    missing, and what paint_corners raises for a palette name `colours` lacks, before the scene changes."""
    import bpy
    from lpk.core import builder
    from lpk.stages import texture
    frozen = bpy.data.meshes.get(frozen_name)
    if frozen is None:
        raise ValueError('no frozen mesh %s in the open .blend: run freeze or adopt first' % frozen_name)
    parts, palette = list(frozen['parts']), list(frozen['palette'])
    missing = [k for k in palette if colours.get(k) is None]
    if missing:
        raise ValueError('the frozen mesh %s uses palette names %s that the model\'s PALETTE lacks'
                         % (frozen_name, ', '.join(missing)))
    me = frozen.copy()
    me.use_fake_user = False
    for key in list(me.keys()):
        del me[key]
    ob = builder.replace_object(obj_name, me, collection)
    builder.paint_corners(me, palette, colours)
    ob['parts'], ob['palette'] = parts, palette
    if texture.MARKS in frozen:
        ob[texture.MARKS] = frozen[texture.MARKS]
    return ob, builder.body_report(ob, parts, builder.degenerate_polygons(me, parts))


def conform_sources(reference, obj_name, sources):
    """Carry each colour source from the parametric body onto the frozen one, so a painted layer follows a
    part reshaped in the frozen mesh. reference: the object of the parametric body the sources were built
    on (a fresh build of build_mesh(P), with 'parts'); obj_name: the frozen body (with 'parts'); sources:
    [{'object': the source's object name, 'mask': its parts or None for every part, 'cage', 'ray': its
    bake reach in metres}], each object built on the reference. All three are read in their own space.

    Every vertex of a source, and every point of the painted marks it carries (lpk.stages.texture.MARKS),
    in vertex order: its nearest point p on the reference's polygons of the mask's parts (every polygon
    without a mask; a polygon's part by polygon_parts) and that polygon's part; then q, the nearest point to
    p on the frozen body's polygons of the same part (by name); the vertex moves by conformed, with the
    normals at p and q blended from the vertex normals (point_normals). A polygon's part is the part of its
    first corner, the rule the bake masks by (lpk.stages.texture). Where the frozen part is the parametric
    one, nothing moves: a point whose move stays within POSITION_STEP, the float rounding of the two
    searches, is left exactly where it was. The correspondence is the nearest point: a part moved further than about
    its own thickness, or turned far, maps a point to the wrong side of it; a part the frozen body lacks
    leaves its points where they are. A vertex whose nearest parametric polygon of any part lies outside
    the mask hangs over a part the source does not paint: it is carried by the mask's polygons all the
    same and counted apart ('unmasked'), as lpk.stages.texture.source_reach leaves it out. The mapping
    reads positions only: a source cast at a sharp crease
    keeps its offset along the blended normal, not along either face's.

    Returns {source object: conform_report's report}, in the order of `sources`. Raises ValueError when the
    reference or the body lacks the 'part' layer."""
    import json
    import bpy
    from lpk.stages import texture
    ref, body = bpy.data.objects[reference], bpy.data.objects[obj_name]
    R, B = read(ref.data), read(body.data)
    if R['part'] is None or B['part'] is None:
        raise ValueError('conform_sources: %s or %s has no part layer' % (reference, obj_name))
    rnames, bnames = list(ref['parts']), list(body['parts'])
    rfp = np.array([R['part'][p[0]] for p in R['polys']], np.int64)
    bfp = np.array([B['part'][p[0]] for p in B['polys']], np.int64)
    rvn, bvn = vertex_normals(R['co'], R['polys']), vertex_normals(B['co'], B['polys'])
    trees = {}

    def tree(side, parts):
        key = (side, parts)
        if key not in trees:
            A, fp, names = (R, rfp, rnames) if side == 'ref' else (B, bfp, bnames)
            idx = [f for f, k in enumerate(fp.tolist()) if parts is None or names[k] in parts]
            trees[key] = (_bvh(A['co'], [A['polys'][f] for f in idx]) if idx else None, np.asarray(idx, np.int64))
        return trees[key]

    out = {}
    for spec in sources:
        ob = bpy.data.objects[spec['object']]
        object_mode(ob)
        me = ob.data
        co = read(me)['co']
        marks = texture.marks_of(ob)
        points = np.concatenate([co] + [np.asarray(m['points'], np.float64).reshape(-1, 3) for m in marks])
        mask = None if spec.get('mask') is None else tuple(spec['mask'])
        rtree, ridx = tree('ref', mask)
        new, offsets = points.copy(), np.zeros(len(points))
        unmatched = np.ones(len(points), bool)
        unmasked = None
        if rtree is not None and len(points):
            hit, p_loc, _ = _nearest(rtree, points)
            faces = ridx[hit]
            p_n = point_normals(R['co'], R['polys'], rvn, faces, p_loc)
            q_loc, q_n = p_loc.copy(), p_n.copy()
            part = [rnames[k] for k in rfp[faces].tolist()]
            for nm in dict.fromkeys(part):
                ids = np.array([i for i, x in enumerate(part) if x == nm], np.int64)
                btree, bidx = tree('body', (nm,))
                if btree is None:
                    continue
                bhit, q_loc[ids], _ = _nearest(btree, p_loc[ids])
                q_n[ids] = point_normals(B['co'], B['polys'], bvn, bidx[bhit], q_loc[ids])
                unmatched[ids] = False
            new, offsets = conformed(points, p_loc, p_n, q_loc, q_n)
            new[unmatched] = points[unmatched]
            still = np.linalg.norm(new - points, axis=1) <= POSITION_STEP
            new[still] = points[still]
            if mask is not None:
                every, every_idx = tree('ref', None)
                over = rfp[every_idx[_nearest(every, points[:len(co)])[0]]]
                unmasked = np.array([rnames[k] not in mask for k in over.tolist()], bool)
        n = len(co)
        _write_co(me, new[:n])
        if marks:
            k = n
            for m in marks:
                m['points'] = [[float(x) for x in row] for row in new[k:k + len(m['points'])]]
                k += len(m['points'])
            ob[texture.MARKS] = json.dumps(marks)
        out[ob.name] = conform_report(co, new[:n], offsets[:n], float(spec['cage']), float(spec['ray']),
                                      int(unmatched[:n].sum()), unmasked)
    return out


def summary(obj_name, reference=None):
    """The body `obj_name` by part: part_table's {part: {'faces', 'tris', 'verts', 'centre', 'size',
    'neighbours', 'border_m', 'mirror', 'mirror_offset', 'uncoloured'}} plus 'deviation': {'mean_cm',
    'max_cm'} of the distances from the part's vertices to the faces of the same part (by name) of the
    object `reference` (polygon_parts' face rule), None when the reference lacks the part or no
    reference is given. Both objects are read in their own space, after object_mode."""
    import bpy
    ob = bpy.data.objects[obj_name]
    object_mode(ob)
    A = read(ob.data)
    names = list(ob['parts'])
    if A['part'] is None or A['pal'] is None:
        raise ValueError('%s has no part or pal layer' % obj_name)
    table = part_table(A['co'], A['part'], A['polys'], A['pal'], A['edges'], names, len(ob.get('palette', [])))
    ref = None
    if reference is not None:
        rob = bpy.data.objects[reference]
        R = read(rob.data)
        rnames = list(rob['parts'])
        rfp = polygon_parts(R['polys'], R['part'])
        ref = (R, rnames, rfp)
    for pid, nm in enumerate(names):
        if nm not in table:
            continue
        table[nm]['deviation'] = None
        if ref is None or not nm or nm not in ref[1]:
            continue
        R, rnames, rfp = ref
        polys = [p for p, f in zip(R['polys'], rfp.tolist()) if f == rnames.index(nm)]
        if not polys:
            continue
        tree = _bvh(R['co'], polys)
        table[nm]['deviation'] = deviation(_nearest(tree, A['co'][A['part'] == pid])[2])
    if '' in table:
        table['']['deviation'] = None
    return table


def _selected(me, selection):
    if selection not in SELECTIONS:
        raise ValueError('selection %r: use %s' % (selection, ', '.join(SELECTIONS)))
    if selection == 'faces':
        return sorted({i for p in me.polygons if p.select for i in p.vertices})
    return [v.index for v in me.vertices if v.select]


def assign(obj_name, part, selection='faces'):
    """Give the part `part` to the selected vertices of the mesh object `obj_name`: those of its selected
    faces (selection 'faces') or its selected vertices ('verts'), as the mesh's select flags hold them.
    The human selects in Edit Mode; the call leaves Edit Mode first (object_mode), so the flags hold the
    selection, and returns the object to the mode it was in. A part name 'parts' lacks is added at its
    end. In the frozen mode freeze stores the change; a parametric build replaces it.

    Returns {'part', 'verts': vertices assigned, 'from': {part: of them, the part they carried}}. Raises
    ValueError for an unknown selection, for the reserved '' and when nothing is selected."""
    import bpy
    if not isinstance(part, str) or not part:
        raise ValueError('assign: a part needs a non-empty name (got %r)' % (part,))
    ob = bpy.data.objects[obj_name]
    prev = object_mode(ob)
    me = ob.data
    ids = _selected(me, selection)
    if not ids:
        restore_mode(ob, prev)
        raise ValueError('assign: nothing of %s is selected (%s): select in Edit Mode first' % (obj_name, selection))
    parts = list(ob.get('parts', ['']))
    if part not in parts:
        parts.append(part)
        ob['parts'] = parts
    A = read(me)
    vp = A['part'] if A['part'] is not None else np.zeros(len(A['co']), np.int64)
    before = name_counts(vp[ids], parts)
    vp = vp.copy()
    vp[ids] = parts.index(part)
    _set_int(me, 'part', 'POINT', vp)
    me.update()
    restore_mode(ob, prev)
    return {'part': part, 'verts': len(ids), 'from': before}


def paint(obj_name, colour, selection='faces', colours=None):
    """Give the palette colour `colour` to the selected faces of the mesh object `obj_name`: its selected
    faces (selection 'faces') or the faces all of whose vertices are selected ('verts'), read as assign
    reads them. A name 'palette' lacks is added at its end. colours: {name: sRGB}, the model's PALETTE:
    the 'Col' corner colours are painted again from it (lpk.core.builder.paint_corners), so the 'color'
    shade shows the change; None leaves them. In the frozen mode freeze stores the change.

    Returns {'colour', 'faces': faces painted, 'from': {colour: of them, the colour they carried}}. Raises
    ValueError for an unknown selection and when no face is selected."""
    import bpy
    from lpk.core import builder
    ob = bpy.data.objects[obj_name]
    prev = object_mode(ob)
    me = ob.data
    if selection not in SELECTIONS:
        restore_mode(ob, prev)
        raise ValueError('selection %r: use %s' % (selection, ', '.join(SELECTIONS)))
    if selection == 'faces':
        faces = [p.index for p in me.polygons if p.select]
    else:
        faces = [p.index for p in me.polygons if all(me.vertices[i].select for i in p.vertices)]
    if not faces:
        restore_mode(ob, prev)
        raise ValueError('paint: no face of %s is selected (%s): select in Edit Mode first' % (obj_name, selection))
    palette = list(ob.get('palette', []))
    if colour not in palette:
        palette.append(colour)
        ob['palette'] = palette
    A = read(me)
    pal = A['pal'] if A['pal'] is not None else np.zeros(len(A['polys']), np.int64)
    before = name_counts(pal[faces], palette)
    pal = pal.copy()
    pal[faces] = palette.index(colour)
    _set_int(me, 'pal', 'FACE', pal)
    if colours is not None:
        builder.paint_corners(me, palette, colours)
    me.update()
    restore_mode(ob, prev)
    return {'colour': colour, 'faces': len(faces), 'from': before}


def select(obj_name, part):
    """Select the part `part` of the mesh object `obj_name` for the human to edit: its vertices, the edges
    between two of them and the faces all of whose vertices carry it; everything else deselected. Written
    in Object Mode (object_mode); the object returns to the mode it was in, so Edit Mode shows the
    selection at once. Returns {'part', 'verts', 'faces'}. Raises ValueError for a part 'parts' lacks."""
    import bpy
    ob = bpy.data.objects[obj_name]
    parts = list(ob.get('parts', []))
    if part not in parts or not part:
        raise ValueError('select: %s has no part %r; it has %s' % (obj_name, part, ', '.join(p for p in parts if p)))
    prev = object_mode(ob)
    me = ob.data
    A = read(me)
    on = (A['part'] == parts.index(part)) if A['part'] is not None else np.zeros(len(A['co']), bool)
    me.vertices.foreach_set('select', on.tolist())
    ev = A['edges']
    me.edges.foreach_set('select', (on[ev[:, 0]] & on[ev[:, 1]]).tolist() if len(ev) else [])
    faces = np.array([bool(on[p].all()) for p in A['polys']], bool)
    me.polygons.foreach_set('select', faces.tolist())
    me.update()
    restore_mode(ob, prev)
    return {'part': part, 'verts': int(on.sum()), 'faces': int(faces.sum())}



# -- operations on a part ----------------------------------------------------------------------------------

def part_index(ob, part, operation):
    """The index of the part `part` in the object `ob`'s 'parts' list, which some vertex carries. Raises
    ValueError naming `operation` and the parts the object has when it lacks the part."""
    parts = list(ob.get('parts', []))
    a = ob.data.attributes.get('part')
    present = set()
    if a is not None:
        v = np.empty(len(ob.data.vertices), np.int32)
        a.data.foreach_get('value', v)
        present = set(v.tolist())
    if not part or part not in parts or parts.index(part) not in present:
        raise ValueError('%s: %s has no part %r; it has %s'
                         % (operation, ob.name, part, ', '.join(p for k, p in enumerate(parts) if p and k in present)))
    return parts.index(part)


def _counts(me):
    return len(me.vertices), len(me.polygons)


def _write_co(me, co):
    me.vertices.foreach_set('co', np.asarray(co, np.float32).reshape(-1))
    me.update()


def transform(obj_name, part, translate=(0.0, 0.0, 0.0), rotate=(0.0, 0.0, 0.0), scale=1.0, pivot='centre',
              falloff=2):
    """Move, turn and scale the part `part` of the mesh object `obj_name` (transformed, in the object's own
    space): translate (x, y, z) m; rotate (x, y, z) degrees in the 'XYZ' order (rotation_matrix); scale one
    factor or (x, y, z) factors, each above 0; pivot 'centre', 'base' or an (x, y, z) point in metres
    (pivot_point over the part's vertices). The vertices of other parts within `falloff` edge rings of the
    part (ring_distances) follow by falloff_weights, so a welded seam stays closed: the band of those rings
    stretches (or crowds) to take up the move, and a large move over a small falloff shears its faces. A
    separate shell moves alone whatever the falloff; falloff 0 moves only the part, which opens no seam but
    stretches the faces that cross it. The topology does not change.

    Returns operation_report's report with 'pivot': [x, y, z] (m, rounded to 0.1 mm), 'falloff' and
    'neighbours_moved': {part: its vertices that moved}. Raises ValueError for a part the body lacks, a
    falloff that is not an int >= 0 and a scale factor <= 0."""
    import bpy
    if isinstance(falloff, bool) or not isinstance(falloff, int) or falloff < 0:
        raise ValueError('transform: falloff %r: use an int >= 0 (edge rings)' % (falloff,))
    s = np.broadcast_to(np.asarray(scale, np.float64), (3,))
    if not (s > 0).all():
        raise ValueError('transform: scale %r: every factor must be above 0' % (scale,))
    ob = bpy.data.objects[obj_name]
    prev = object_mode(ob)
    pid = part_index(ob, part, 'transform')
    me = ob.data
    before = _counts(me)
    A = read(me)
    seeds = np.flatnonzero(A['part'] == pid)
    rings = ring_distances(len(A['co']), A['edges'], seeds, falloff)
    w = falloff_weights(rings, falloff)
    p0 = pivot_point(A['co'][seeds], pivot)
    _write_co(me, transformed(A['co'], w, translate, rotate, s, p0))
    after = read(me)['co']
    names = list(ob['parts'])
    moved = (np.linalg.norm(after - A['co'], axis=1) > 0) & (A['part'] != pid)
    restore_mode(ob, prev)
    return operation_report('transform', part, before, _counts(me), max_displacement_cm(A['co'], after),
                            pivot=[round(float(x), 4) for x in p0], falloff=falloff,
                            neighbours_moved=name_counts(A['part'][moved], names) if moved.any() else {})


def replace(obj_name, part, source_name, colours=None):
    """Replace the part `part` of the mesh object `obj_name` by the same part of the object `source_name`
    (a fresh parametric build, lpk.core.builder.finish's object with 'parts' and 'palette'): the body's
    vertices of the part and their faces are removed, the source's vertices of the part (in source order)
    and its faces are added at the end of the body's, each new vertex with the body's id of the part and
    join_loop 0, each face with its source colour by name (a palette name the body lacks is added at the
    end of its 'palette') and smooth flag. Only a separate shell can be replaced: a welded part's seam
    vertices belong to its neighbour's faces too, and the new part would not meet them. colours: {name:
    sRGB}, the model's PALETTE: the 'Col' corner colours are painted again from it; None leaves them (the
    new faces then carry none). The body's other layers (UVs, vertex groups) are left as they are on the
    kept geometry and empty on the new; the painted marks are positions and are not changed.

    Returns operation_report's report with 'part_vertices' and 'part_faces': [before, after], and
    'max_displacement_cm': the farthest a new vertex lies from the old part's surface. Raises ValueError
    for a part the body lacks, a part welded to others in the body or in the source (naming them), and a
    part the source lacks."""
    import bmesh
    import bpy
    from lpk.core import builder
    from lpk.forms import joins
    ob = bpy.data.objects[obj_name]
    prev = object_mode(ob)
    pid = part_index(ob, part, 'replace')
    names = list(ob['parts'])
    me = ob.data
    before = _counts(me)
    A = read(me)
    welded = welded_parts(A['edges'], A['part'], pid)
    if welded:
        restore_mode(ob, prev)
        raise ValueError('replace: %s is welded to %s (it shares vertices with them): only a separate shell is '
                         'replaced; move a welded part with transform' % (part, ', '.join(names[i] for i in welded)))
    src = bpy.data.objects[source_name]
    S = read(src.data)
    snames, spalette = list(src['parts']), list(src['palette'])
    if part not in snames or not (S['part'] == snames.index(part)).any():
        restore_mode(ob, prev)
        raise ValueError('replace: the parametric build makes no part %r' % part)
    spid = snames.index(part)
    sw = welded_parts(S['edges'], S['part'], spid)
    if sw:
        restore_mode(ob, prev)
        raise ValueError('replace: the parametric build welds %s to %s: only a separate shell is replaced'
                         % (part, ', '.join(snames[i] for i in sw)))
    old_ids = np.flatnonzero(A['part'] == pid)
    old_polys = [p for p, ok in zip(A['polys'], part_faces(A['polys'], A['part'], pid).tolist()) if ok]
    sids = np.flatnonzero(S['part'] == spid)
    local = {int(i): k for k, i in enumerate(sids.tolist())}
    palette = list(ob['palette'])
    for nm in spalette:
        if nm not in palette:
            palette.append(nm)
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[bm.verts[i] for i in old_ids.tolist()], context='VERTS')
    # Written and read again before adding: bmesh reuses the slots of deleted elements, which would put
    # the new vertices and faces among the kept ones in an order of its own.
    bm.to_mesh(me)
    bm.free()
    bm = bmesh.new()
    bm.from_mesh(me)
    lpart, lpal = bm.verts.layers.int['part'], bm.faces.layers.int['pal']
    ljoin = bm.verts.layers.int.get(joins.LAYER)
    new = []
    for i in sids.tolist():
        v = bm.verts.new(tuple(S['co'][i]))
        v[lpart] = pid
        if ljoin is not None:
            v[ljoin] = 0
        new.append(v)
    shade = [p.use_smooth for p in src.data.polygons]
    for f, poly in enumerate(S['polys']):
        if S['part'][poly[0]] != spid:
            continue
        face = bm.faces.new([new[local[i]] for i in poly])
        face[lpal] = palette.index(spalette[int(S['pal'][f])])
        face.smooth = shade[f]
    bm.to_mesh(me)
    bm.free()
    me.update()
    ob['palette'] = palette
    triangulate(me)
    if colours is not None:
        builder.paint_corners(me, palette, colours)
    after = read(me)
    tree = _bvh(A['co'], old_polys)
    far = _nearest(tree, S['co'][sids])[2]
    restore_mode(ob, prev)
    return operation_report('replace', part, before, _counts(me), round(float(far.max()) * 100, 2),
                            part_vertices=[len(old_ids), int((after['part'] == pid).sum())],
                            part_faces=[len(old_polys), int(part_faces(after['polys'], after['part'], pid).sum())])


def _ids_layer(bm):
    """A temporary int vertex layer holding each vertex's index before an operation (removed by the
    caller), so the vertices that survive it are matched by identity."""
    layer = bm.verts.layers.int.new('_lpk_id')
    for v in bm.verts:
        v[layer] = v.index
    return layer


def _survivors(bm, layer):
    """[(old index, new index)] of the vertices of `bm` that carried an old index in `layer` (_ids_layer),
    with the layer removed."""
    bm.verts.index_update()
    out = [(v[layer], v.index) for v in bm.verts if v[layer] >= 0]
    bm.verts.layers.int.remove(layer)
    return out


def decimate(obj_name, part, ratio):
    """Reduce the faces of the part `part` of the mesh object `obj_name` to about `ratio` (above 0, up to 1)
    of them by half-edge collapses: a vertex of the part, not pinned (pinned_vertices: the border with
    another part, an open rim), is merged into a neighbour of the part, so no vertex moves and the vertices
    that stay keep their places; every collapse removes two triangles. A round takes the cheapest collapses
    (collapse_cost, the squared distances of the target from the vertex's face planes, so flat places go
    first) whose neighbourhoods do not overlap (collapse_order); a collapse is made only when the edge's two
    faces are its only shared neighbours (the link condition, which keeps the surface manifold), when the
    vertices opposite the edge keep three edges or more, and when no face it moves turns by more than
    COLLAPSE_COS or loses its area (lpk.core.builder.DEGENERATE_M2). The part keeps more faces than asked
    when the pinned vertices and these conditions leave no collapse, after COLLAPSE_ROUNDS rounds at most.
    The result is made of triangles.

    Returns operation_report's report with 'part_faces': [before, after] (polygon_parts' faces of the
    part), 'target_faces', 'pinned' (vertices) and 'removed_max_cm': the farthest a removed vertex lies
    from the part's faces after (the shape the decimation lost). Raises ValueError for a part the body
    lacks and a ratio outside (0, 1]."""
    import bmesh
    import bpy
    from lpk.core import builder
    if isinstance(ratio, bool) or not isinstance(ratio, (int, float)) or not 0 < ratio <= 1:
        raise ValueError('decimate: ratio %r: use a share of the faces above 0 and up to 1' % (ratio,))
    ob = bpy.data.objects[obj_name]
    prev = object_mode(ob)
    pid = part_index(ob, part, 'decimate')
    me = ob.data
    triangulate(me)
    before = _counts(me)
    A = read(me)
    faces0 = int((polygon_parts(A['polys'], A['part']) == pid).sum())
    target = int(round(ratio * faces0))
    remaining = (faces0 - target + 1) // 2
    bm = bmesh.new()
    bm.from_mesh(me)
    ids = _ids_layer(bm)
    lpart = bm.verts.layers.int['part']
    pinned_count = int(pinned_vertices(A['polys'], A['part'], pid).sum())
    for _ in range(COLLAPSE_ROUNDS):
        if remaining <= 0:
            break
        bm.verts.index_update()
        bm.verts.ensure_lookup_table()
        bm.normal_update()
        vp = np.array([v[lpart] for v in bm.verts], np.int64)
        polys = [[v.index for v in f.verts] for f in bm.faces]
        pin = pinned_vertices(polys, vp, pid)
        nb = {v.index: sorted(e.other_vert(v).index for e in v.link_edges) for v in bm.verts}
        candidates = []
        for v in bm.verts:
            if vp[v.index] != pid or pin[v.index]:
                continue
            normals = [tuple(f.normal) for f in v.link_faces]
            for e in sorted(v.link_edges, key=lambda e: e.other_vert(v).index):
                u = e.other_vert(v)
                if len(e.link_faces) != 2:
                    continue
                opposite = {w.index for f in e.link_faces for w in f.verts} - {u.index, v.index}
                if set(nb[v.index]) & set(nb[u.index]) != opposite or any(len(nb[w]) < 4 for w in opposite):
                    continue
                if not _collapse_keeps_faces(v, u, builder.DEGENERATE_M2):
                    continue
                candidates.append((collapse_cost(tuple(v.co), tuple(u.co), normals), v.index, u.index))
        picks = collapse_order(candidates, nb, remaining)
        if not picks:
            break
        bmesh.ops.weld_verts(bm, targetmap={bm.verts[v]: bm.verts[u] for v, u in picks})
        remaining -= len(picks)
    kept = _survivors(bm, ids)
    bm.to_mesh(me)
    bm.free()
    me.update()
    triangulate(me)
    after = read(me)
    old = np.array([o for o, _ in kept], np.int64)
    new = np.array([n for _, n in kept], np.int64)
    removed = np.setdiff1d(np.flatnonzero(A['part'] == pid), old)
    fp = polygon_parts(after['polys'], after['part'])
    polys = [p for p, f in zip(after['polys'], fp.tolist()) if f == pid]
    lost = _nearest(_bvh(after['co'], polys), A['co'][removed])[2] if len(removed) and polys else np.zeros(0)
    restore_mode(ob, prev)
    return operation_report('decimate', part, before, _counts(me), max_displacement_cm(A['co'][old], after['co'][new]),
                            part_faces=[faces0, int((fp == pid).sum())], target_faces=target, pinned=pinned_count,
                            removed_max_cm=round(float(lost.max()) * 100, 2) if len(lost) else 0.0)


def _collapse_keeps_faces(v, u, min_area):
    """Whether moving the bmesh vertex `v` onto `u` leaves every face of v that does not hold u with an area
    of at least `min_area` (m2) and its normal within COLLAPSE_COS of the one it had."""
    from mathutils import geometry
    for f in v.link_faces:
        if u in f.verts:
            continue
        pts = [u.co if w == v else w.co for w in f.verts]
        n = geometry.normal(pts)
        if geometry.area_tri(*pts[:3]) < min_area or n.length == 0 or n.dot(f.normal) < COLLAPSE_COS:
            return False
    return True


def subdivide(obj_name, part, cuts=1):
    """Subdivide the part `part` of the mesh object `obj_name`: each edge between two of the part's faces
    (part_faces) is cut `cuts` times (bmesh subdivide_edges, flat: no vertex moves, the new ones lie on the
    old edges), and the faces cut are triangulated as lpk.core.builder.finish does. The edges on the border
    with another part and on an open rim are not cut, so the faces beyond the seam keep their topology and
    the border vertices stay (pinned_vertices): the faces along the border split into fewer, longer
    triangles than the inner ones. New vertices take the part and join_loop 0; new faces keep the colour of
    the face they came from.

    Returns operation_report's report with 'part_faces': [before, after], 'cut_edges' and 'pinned'.
    Raises ValueError for a part the body lacks and cuts that are not an int >= 1."""
    import bmesh
    import bpy
    from lpk.forms import joins
    if isinstance(cuts, bool) or not isinstance(cuts, int) or cuts < 1:
        raise ValueError('subdivide: cuts %r: use an int >= 1' % (cuts,))
    ob = bpy.data.objects[obj_name]
    prev = object_mode(ob)
    pid = part_index(ob, part, 'subdivide')
    me = ob.data
    triangulate(me)
    before = _counts(me)
    A = read(me)
    inside = part_faces(A['polys'], A['part'], pid)
    bm = bmesh.new()
    bm.from_mesh(me)
    ids = _ids_layer(bm)
    bm.faces.ensure_lookup_table()
    edges = [e for e in bm.edges if len(e.link_faces) == 2 and all(inside[f.index] for f in e.link_faces)]
    if edges:
        bmesh.ops.subdivide_edges(bm, edges=edges, cuts=cuts, use_grid_fill=True, use_single_edge=True,
                                  smooth=0.0)
    lpart, ljoin = bm.verts.layers.int['part'], bm.verts.layers.int.get(joins.LAYER)
    n0 = len(A['co'])
    # subdivide_edges appends its vertices after the old ones and interpolates their layers, ids included.
    bm.verts.index_update()
    for v in bm.verts:
        if v.index >= n0:
            v[ids] = -1
            v[lpart] = pid
            if ljoin is not None:
                v[ljoin] = 0
    kept = _survivors(bm, ids)
    bm.to_mesh(me)
    bm.free()
    me.update()
    triangulate(me)
    after = read(me)
    old = np.array([o for o, _ in kept], np.int64)
    new = np.array([n for _, n in kept], np.int64)
    restore_mode(ob, prev)
    return operation_report('subdivide', part, before, _counts(me), max_displacement_cm(A['co'][old], after['co'][new]),
                            part_faces=[int(inside.sum()), int(part_faces(after['polys'], after['part'], pid).sum())],
                            cut_edges=len(edges), pinned=int(pinned_vertices(A['polys'], A['part'], pid).sum()))


def smooth(obj_name, part, iterations=1, factor=0.5):
    """Smooth the part `part` of the mesh object `obj_name` (smoothed): its vertices that are not pinned
    (pinned_vertices: the border with another part, an open rim) move `iterations` times by `factor` (above
    0, up to 1) of the way to the mean of their neighbours. The topology does not change; a rounded part
    shrinks a little toward its pinned border with every step.

    Returns operation_report's report with 'pinned', 'iterations' and 'factor'. Raises ValueError for a
    part the body lacks, iterations that are not an int >= 1 and a factor outside (0, 1]."""
    import bpy
    if isinstance(iterations, bool) or not isinstance(iterations, int) or iterations < 1:
        raise ValueError('smooth: iterations %r: use an int >= 1' % (iterations,))
    if isinstance(factor, bool) or not isinstance(factor, (int, float)) or not 0 < factor <= 1:
        raise ValueError('smooth: factor %r: use a number above 0 and up to 1' % (factor,))
    ob = bpy.data.objects[obj_name]
    prev = object_mode(ob)
    pid = part_index(ob, part, 'smooth')
    me = ob.data
    before = _counts(me)
    A = read(me)
    pin = pinned_vertices(A['polys'], A['part'], pid)
    movable = (A['part'] == pid) & ~pin
    _write_co(me, smoothed(A['co'], A['edges'], movable, iterations, factor))
    after = read(me)['co']
    restore_mode(ob, prev)
    return operation_report('smooth', part, before, _counts(me), max_displacement_cm(A['co'], after),
                            pinned=int((pin & (A['part'] == pid)).sum()), iterations=iterations, factor=float(factor))
