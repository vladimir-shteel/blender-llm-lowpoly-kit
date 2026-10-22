"""Rigging tools: an armature from a skeleton template and the model's joint positions (build_rig), and its
skin (skin): part-restricted distance weights, replaced by a weights backend's (voxel heat diffuse, or
Blender's bone heat solved on the mesh or on a watertight voxel proxy of it; weights() picks the backend,
WEIGHTS binds the backends), with Corrective Smooth baked into the join zones (smooth_zones). The numpy
helpers of the proxy transfer run on the host as well."""
import bpy, bmesh, math, os, platform, random, subprocess
import addon_utils
import numpy as np
from mathutils import Vector, kdtree
from mathutils.bvhtree import BVHTree
from mathutils.geometry import intersect_point_line

from lpk import skeletons
from lpk.stages import pose

FALLOFF = 4          # inverse-distance power; higher = harder joints
# Bones per vertex the weight functions keep when the caller names no limit.
MAX_INFLUENCES = 3
# A distance weight under this share of its vertex's total is dropped and the rest renormalised: it
# barely moves the vertex but takes one of the influences the export allows.
MIN_WEIGHT = 0.03
PROXY_MAX_CELLS = 512   # voxels along the proxy's longest side; finer grids make the heat solve too slow
# Seconds the vhd binary may run before vhd_weights gives up on it: a hung binary raises, and
# weights(backend='auto') goes on to the next backend, instead of blocking Blender.
VHD_TIMEOUT = 240


def _seg_dist(p, h, t):
    _, f = intersect_point_line(p, h, t)
    f = min(max(f, 0.0), 1.0)
    return (p - (h + (t - h) * f)).length


def _armature(ob, rig_name, bones, rolls):
    """A new armature object `rig_name` in the body `ob`'s collection, in place of any object of that name,
    carrying the body's world transform: bones {name: (head, tail, parent or None, connected)} in the body's
    own space, in that order, each bone's Z axis aligned to rolls[name]. Needs a window (edit mode)."""
    coll = ob.users_collection[0]
    bpy.context.view_layer.update()
    world = ob.matrix_world.copy()
    old = bpy.data.objects.get(rig_name)
    if old:
        bpy.data.objects.remove(old, do_unlink=True)
        bpy.context.view_layer.update()  # a removed object stays as None in view_layer.objects until an update
    for a in [a for a in bpy.data.armatures if a.name == rig_name and a.users == 0]:
        bpy.data.armatures.remove(a)

    arm = bpy.data.armatures.new(rig_name)
    rig = bpy.data.objects.new(rig_name, arm)
    coll.objects.link(rig)
    arm.display_type = 'STICK'
    rig.show_in_front = True
    rig.matrix_world = world
    vl = bpy.context.view_layer
    for o in vl.objects:
        o.select_set(False)
    rig.select_set(True); vl.objects.active = rig
    from lpk.stages import view
    with bpy.context.temp_override(**view.window_context(), active_object=rig, object=rig, selected_objects=[rig]):
        bpy.ops.object.mode_set(mode='EDIT')
        eb = arm.edit_bones
        for name, (h, t, p, c) in bones.items():
            b = eb.new(name); b.head = h; b.tail = t
        for name, (h, t, p, c) in bones.items():
            b = eb[name]
            if p:
                b.parent = eb[p]; b.use_connect = c
            b.align_roll(rolls[name])
        bpy.ops.object.mode_set(mode='OBJECT')
    return rig


def _write_distance_weights(ob, segs, allowed, fixed, influences):
    """Replace the body `ob`'s vertex groups by one group per bone of segs ({name: (head, tail)} in the
    mesh's own space, in that order) holding part-restricted inverse-distance weights: a vertex of a part
    in `fixed` takes its fixed weights, any other the `influences` strongest of allowed[part], none under
    MIN_WEIGHT, renormalised; a weight of 0 (a fixed share of 0) is no assignment. Returns the most bones
    weighting one vertex."""
    me = ob.data
    parts = list(ob['parts'])
    for vg in list(ob.vertex_groups):
        ob.vertex_groups.remove(vg)
    groups = {n: ob.vertex_groups.new(name=n) for n in segs}
    pa = me.attributes['part'].data
    max_inf = 0
    for v in me.vertices:
        part = parts[pa[v.index].value]
        if part in fixed:
            ws = fixed[part]
        else:
            raw = {n: 1.0 / (_seg_dist(v.co, *segs[n]) + 0.01) ** FALLOFF for n in allowed[part]}
            top = sorted(raw.items(), key=lambda kv: -kv[1])[:influences]
            tot = sum(w for _, w in top)
            ws = {n: w / tot for n, w in top if w / tot > MIN_WEIGHT}
            tot = sum(ws.values()); ws = {n: w / tot for n, w in ws.items()}
        ws = {n: w for n, w in ws.items() if w > 0}
        max_inf = max(max_inf, len(ws))
        for n, w in ws.items():
            groups[n].add([v.index], w, 'REPLACE')
    return max_inf


def _bind(ob, rig):
    """Parent the body `ob` to `rig` with one Armature modifier on it and an identity local transform (the
    rig carries the body's world transform)."""
    for m in [m for m in ob.modifiers if m.type == 'ARMATURE']:
        ob.modifiers.remove(m)
    ob.modifiers.new('Armature', 'ARMATURE').object = rig
    ob.parent = rig
    ob.matrix_parent_inverse.identity()
    ob.matrix_basis.identity()


def _weights(ob):
    gn = {g.index: g.name for g in ob.vertex_groups}
    return [{gn[g.group]: g.weight for g in v.groups if g.weight > 0} for v in ob.data.vertices]


def _set_weights(ob, ws):
    """Replace the body's weights by ws ([{bone: weight}] per vertex): every vertex leaves every group, then
    takes its positive weights, a group made for a bone that has none; a weight of 0 is no assignment."""
    for vg in ob.vertex_groups:
        vg.remove(list(range(len(ob.data.vertices))))
    for i, w in enumerate(ws):
        for n, x in w.items():
            if x > 0:
                (ob.vertex_groups.get(n) or ob.vertex_groups.new(name=n)).add([i], x, 'REPLACE')


def drop_zero_weights(obj_name):
    """Remove every vertex-group assignment of the mesh object `obj_name` whose weight is not positive, group
    by group in group order, each group's vertices in vertex order. Blender keeps an assignment of weight 0 as
    a membership, and an exporter that counts memberships (the glTF exporter's influence count) counts it as
    an influence, past the limit the positive weights keep. Changes no positive weight. Returns the number of
    assignments removed."""
    ob = bpy.data.objects[obj_name]
    zero = {}
    for v in ob.data.vertices:
        for g in v.groups:
            if not g.weight > 0:
                zero.setdefault(g.group, []).append(v.index)
    for group in sorted(zero):
        ob.vertex_groups[group].remove(zero[group])
    return sum(len(ids) for ids in zero.values())


def _limit(w, influences=MAX_INFLUENCES):
    """The export limits of the weights: the `influences` strongest, none under MIN_WEIGHT, normalised."""
    top = sorted(((n, x) for n, x in w.items() if x > 0), key=lambda kv: -kv[1])[:influences]
    tot = sum(x for _, x in top)
    if tot <= 0:
        return None
    w = {n: x / tot for n, x in top if x / tot > MIN_WEIGHT}
    tot = sum(w.values())
    return {n: x / tot for n, x in w.items()}


def _vhd_rel(system, machine):
    """The add-on's binary under its bin/ folder for platform.system() and platform.machine(), as the
    add-on picks it: Windows/{x64,arm64,x86}/vhd.exe, Linux/{x64,arm64}/vhd, Darwin/vhd (one universal
    build). Returns a tuple of path parts, or None for a platform the add-on has no build for."""
    m = machine.lower()
    arch = 'x64' if m.endswith(('amd64', 'x86_64')) else 'arm64' if m.endswith(('arm64', 'aarch64')) else None
    if system == 'Windows':
        return ('Windows', arch or 'x86', 'vhd.exe')
    if system == 'Linux':
        return ('Linux', arch, 'vhd') if arch else None
    if system == 'Darwin':
        return ('Darwin', 'vhd')
    return None


def vhd_exe():
    """Path of the Voxel Heat Diffuse Skinning add-on's (Mesh Online) binary for this platform, or None
    when the add-on is missing or disabled or has no binary for this platform."""
    for m in addon_utils.modules():
        if m.__name__.endswith('voxel_skinning') and addon_utils.check(m.__name__)[1]:
            rel = _vhd_rel(platform.system(), platform.machine())
            exe = os.path.join(os.path.dirname(m.__file__), 'bin', *rel) if rel else None
            return exe if exe and os.path.isfile(exe) else None
    return None


def vhd_weights(obj_name, rig_name, allowed, fixed=None, resolution=128, loops=5, samples=64, falloff=0.8,
                influences=MAX_INFLUENCES):
    """Voxel heat diffuse weights in place of the distance weights on the body (distance_weights first).
    Heat spreads through the voxelised volume, so it does not jump the armpit, the crotch or the
    slit between fingers the way distance does, and intersecting shells (the mitten in the wrist)
    do not matter. The add-on's operator is modal; this writes its file format and runs its binary
    synchronously. Then distance_weights' rules: the part's allowed bones, fixed parts, the export limits
    (`influences` as for distance_weights); a vertex with no weight on its allowed bones keeps its distance
    weights. The binary runs under a timeout of 240 s, far beyond one bridge call: when it hangs (a
    broken install), the call loses its response while the binary runs on.
    Returns {'weights': 'vhd', 'distance_kept': vertices that kept distance weights,
    'distance_kept_parts': {part: count}, 'distance_kept_verts': {part: [those vertices' indices]},
    'max_influences': the most bones weighting one vertex}."""
    fixed = fixed or {}
    ob, rig = bpy.data.objects[obj_name], bpy.data.objects[rig_name]
    work = os.path.join(bpy.app.tempdir, 'vhd')
    os.makedirs(work, exist_ok=True)
    mw, rw = ob.matrix_world, rig.matrix_world
    with open(os.path.join(work, 'mesh.txt'), 'w', encoding='utf-8') as f:
        for v in ob.data.vertices:
            p = mw @ v.co
            f.write('v,%r,%r,%r\n' % (p.x, p.y, p.z))
        for p in ob.data.polygons:
            f.write('f,' + ','.join(str(i) for i in p.vertices) + '\n')
    with open(os.path.join(work, 'bone.txt'), 'w', encoding='utf-8') as f:
        for b in rig.data.bones:
            if b.use_deform:
                h, t = rw @ b.head_local, rw @ b.tail_local
                f.write('b,%s,%r,%r,%r,%r,%r,%r\n' % (b.name, h.x, h.y, h.z, t.x, t.y, t.z))
    out = os.path.join(work, 'weight.txt')
    if os.path.exists(out):
        os.remove(out)
    exe = vhd_exe()
    if exe is None:
        raise RuntimeError('vhd_weights needs the Voxel Heat Diffuse Skinning add-on installed and enabled, with '
                           'its binary for this platform (%s %s)' % (platform.system(), platform.machine()))
    # Arguments: voxel grid, diffuse loops, sample rays, max influences, falloff, detect solidify, half cores.
    r = subprocess.run([exe, 'mesh.txt', 'bone.txt', 'weight.txt', str(resolution), str(loops), str(samples),
                        '8', str(falloff), 'n', 'n'], cwd=work, capture_output=True, timeout=VHD_TIMEOUT)
    if not os.path.exists(out):
        raise RuntimeError('vhd failed: ' + r.stdout.decode(errors='replace')[-600:])
    raw, names = [dict() for _ in ob.data.vertices], []
    with open(out, encoding='utf-8') as f:
        for line in f:
            tk = line.strip().split(',')
            if tk[0] == 'b':
                names.append(tk[1])
            elif tk[0] == 'w':
                raw[int(tk[1])][names[int(tk[2])]] = float(tk[3])
    parts = list(ob['parts']); pa = ob.data.attributes['part'].data
    ws, kept = _weights(ob), {}
    for i, w in enumerate(raw):
        part = parts[pa[i].value]
        if part in fixed:
            ws[i] = dict(fixed[part]); continue
        w = _limit({n: x for n, x in w.items() if n in allowed[part]}, influences)
        if w:
            ws[i] = w
        else:
            kept.setdefault(part, []).append(i)
    _set_weights(ob, ws)
    return {'weights': 'vhd', **_kept_report(kept), 'max_influences': max(len(w) for w in ws)}


def _kept_report(kept):
    """The report keys of the vertices a backend left on their distance weights, from {part: [vertex
    indices]}: {'distance_kept': their count, 'distance_kept_parts': {part: count}, 'distance_kept_verts':
    {part: [indices]}}, parts in name order."""
    kept = dict(sorted(kept.items()))
    return {'distance_kept': sum(len(v) for v in kept.values()),
            'distance_kept_parts': {p: len(v) for p, v in kept.items()}, 'distance_kept_verts': kept}


def heat_weights(obj_name, rig_name, allowed, fixed=None, influences=MAX_INFLUENCES):
    """Blender's automatic bone heat weights (Parent > With Automatic Weights) in place of the distance
    weights on the body (distance_weights first), then vhd_weights' rules: a vertex keeps only its part's
    allowed bones, fixed parts take their fixed weights, the export limits apply (`influences` as for
    distance_weights), and a vertex left with no weight keeps its distance weights.
    Bone heat starts at the bones each vertex sees in a straight line and diffuses over the mesh
    surface, so an island none of whose vertices sees a bone gets no heat, and the solver can fail
    outright ('Bone Heat Weighting: failed to find solution for one or more bones', a warning that only
    reaches the info log). Both show as vertices without any heat weight, which the report counts per
    part. The weights are cleared before the solve because a failed solve leaves the
    groups of the bones it did not reach as they were, which would hide the failure.
    The operator parents the mesh itself: the mesh is unparented first (world transform kept) so it is
    parented the usual way, and afterwards the parent, the parent inverse, the local transform, the
    modifier stack, visibility, selection and the active object are put back as they were; on
    an error the distance weights are put back too.
    Needs both objects in Object mode.
    Returns {'weights': 'heat', 'no_heat': vertices of non-fixed parts without any heat weight,
    'no_heat_parts': {part: count}, 'distance_kept': vertices that kept distance weights,
    'distance_kept_parts': {part: count}, 'distance_kept_verts': {part: [those vertices' indices]},
    'max_influences': n}."""
    fixed = fixed or {}
    ob, rig = bpy.data.objects[obj_name], bpy.data.objects[rig_name]
    from lpk.stages import view
    window = view.window_context()
    for o in (ob, rig):
        if o.mode != 'OBJECT':
            raise RuntimeError('heat_weights needs Object mode; %s is in %s mode' % (o.name, o.mode))
    vl = bpy.context.view_layer
    selected = {o.name for o in vl.objects if o.select_get()}
    active = vl.objects.active
    hidden = {o: o.hide_get() for o in (ob, rig)}
    parent, parent_type, parent_bone = ob.parent, ob.parent_type, ob.parent_bone
    parent_inv, basis = ob.matrix_parent_inverse.copy(), ob.matrix_basis.copy()
    modifiers = {m.name for m in ob.modifiers}
    targets = {m.name: m.object for m in ob.modifiers if m.type == 'ARMATURE'}
    ws0, heat = _weights(ob), None
    try:
        every = list(range(len(ob.data.vertices)))
        for vg in ob.vertex_groups:
            vg.remove(every)
        vl.update()
        mw = ob.matrix_world.copy()
        ob.parent = None
        ob.matrix_world = mw
        for o in vl.objects:
            o.select_set(False)
        for o in (ob, rig):
            o.hide_set(False)
            o.select_set(True)
        vl.objects.active = rig
        with bpy.context.temp_override(**window, active_object=rig, object=rig,
                                       selected_objects=[ob, rig], selected_editable_objects=[ob, rig]):
            res = bpy.ops.object.parent_set(type='ARMATURE_AUTO')
        if 'FINISHED' not in res:
            raise RuntimeError('bone heat parenting did not finish: %s' % sorted(res))
        heat = _weights(ob)
    finally:
        ob.parent = parent
        ob.parent_type = parent_type
        ob.parent_bone = parent_bone
        ob.matrix_parent_inverse = parent_inv
        ob.matrix_basis = basis
        for m in [m for m in ob.modifiers if m.name not in modifiers]:
            ob.modifiers.remove(m)
        for n, target in targets.items():
            m = ob.modifiers.get(n)
            if m is not None:
                m.object = target
        for o in vl.objects:
            o.select_set(o.name in selected)
        for o, h in hidden.items():
            o.hide_set(h)
        vl.objects.active = active
        if heat is None:
            _set_weights(ob, ws0)
        vl.update()
    parts = list(ob['parts']); pa = ob.data.attributes['part'].data
    ws, kept, no_heat, by_part = list(ws0), {}, 0, {}
    for i, w in enumerate(heat):
        part = parts[pa[i].value]
        if part in fixed:
            ws[i] = dict(fixed[part]); continue
        if not w:
            no_heat += 1
            by_part[part] = by_part.get(part, 0) + 1
        w = _limit({n: x for n, x in w.items() if n in allowed[part]}, influences)
        if w:
            ws[i] = w
        else:
            kept.setdefault(part, []).append(i)
    _set_weights(ob, ws)
    return {'weights': 'heat', 'no_heat': no_heat, 'no_heat_parts': dict(sorted(by_part.items())),
            **_kept_report(kept), 'max_influences': max((len(w) for w in ws), default=0)}


def _unit(x):
    """Rows of x scaled to unit length; zero rows stay zero."""
    n = np.linalg.norm(x, axis=-1, keepdims=True)
    return np.divide(x, n, out=np.zeros_like(x), where=n > 0)


def _islands(n, edges):
    """Connected components of n vertices joined by edges ((e, 2) vertex index pairs). Returns an (n,)
    int64 array: per vertex the smallest vertex index of its component, so the labels do not depend on
    the edge order."""
    parent = list(range(n))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for a, b in np.asarray(edges, dtype=np.int64).reshape(-1, 2).tolist():
        ra, rb = root(a), root(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    return np.array([root(i) for i in range(n)], dtype=np.int64)


def _vertex_normals(verts, tris):
    """Vertex normals as Blender's bone heat computes them: the normalised sum of the unit normals of the
    triangles around a vertex (not weighted by area or angle). verts: (n, 3); tris: (t, 3) vertex indices.
    Returns (n, 3); a vertex in no triangle gets (0, 0, 0)."""
    v = np.asarray(verts, dtype=np.float64).reshape(-1, 3)
    t = np.asarray(tris, dtype=np.int64).reshape(-1, 3)
    fn = _unit(np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]]))
    vn = np.zeros_like(v)
    for k in range(3):
        np.add.at(vn, t[:, k], fn)
    return _unit(vn)


def _heat_closest(p, normals, heads, tails, eps=1e-4):
    """The bones Blender's bone heat counts as closest to each vertex, and every bone's closest point.
    Bone heat measures a vertex's distance to a bone as the distance to the bone segment divided by
    0.5 * (cos + 1.001), cos being the cosine between the vertex normal and the direction from the bone to
    the vertex, so a bone on the side the normal faces (outside the surface) counts as far; the closest
    bones are those within a relative eps of the vertex's smallest measure. A vertex only takes heat from a
    closest bone it sees.
    p, normals: (n, 3) vertex positions and unit normals; heads, tails: (m, 3) bone ends; one space, metres.
    Returns ((n, m) bool: closest, (n, m, 3): the point of each bone closest to each vertex)."""
    p = np.asarray(p, dtype=np.float64).reshape(-1, 3)
    nrm = np.asarray(normals, dtype=np.float64).reshape(-1, 3)
    h = np.asarray(heads, dtype=np.float64).reshape(-1, 3)
    d = np.asarray(tails, dtype=np.float64).reshape(-1, 3) - h
    dd = (d * d).sum(axis=1)
    f = ((p[:, None, :] - h[None]) * d[None]).sum(axis=2) / np.where(dd > 0, dd, 1.0)
    f = np.where(dd > 0, np.clip(f, 0.0, 1.0), 0.0)
    ends = h[None] + f[..., None] * d[None]
    r = p[:, None, :] - ends
    dist = np.linalg.norm(r, axis=2)
    cos = (r * nrm[:, None, :]).sum(axis=2) / np.where(dist > 0, dist, 1.0)
    measure = dist / (0.5 * (cos + 1.001))
    return measure <= measure.min(axis=1, keepdims=True) * (1.0 + eps), ends


def _closest_barycentric(p, a, b, c):
    """Barycentric coordinates of the point of triangle (a[i], b[i], c[i]) closest to p[i]: the region
    tests of Ericson's closest point on a triangle, vectorised. A degenerate triangle (a segment or a
    point) gets the coordinates of its closest corner or edge point. All arguments (n, 3).
    Returns (n, 3) non-negative coordinates summing to 1."""
    p, a, b, c = (np.asarray(x, dtype=np.float64).reshape(-1, 3) for x in (p, a, b, c))
    n = len(p)
    ab, ac = b - a, c - a
    ap, bp, cp = p - a, p - b, p - c
    d1, d2 = (ab * ap).sum(axis=1), (ac * ap).sum(axis=1)
    d3, d4 = (ab * bp).sum(axis=1), (ac * bp).sum(axis=1)
    d5, d6 = (ab * cp).sum(axis=1), (ac * cp).sum(axis=1)
    va, vb, vc = d3 * d6 - d5 * d4, d5 * d2 - d1 * d6, d1 * d4 - d3 * d2
    zero = np.zeros(n)
    with np.errstate(divide='ignore', invalid='ignore'):
        den = va + vb + vc
        v, w = vb / den, vc / den
        out = np.stack([1.0 - v - w, v, w], axis=1)
        # Ericson returns at the first region that matches, in the order A, B, AB, C, AC, BC, inside:
        # assigning in the reverse order lets the earlier regions win.
        t = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        m = (va <= 0) & (d4 - d3 >= 0) & (d5 - d6 >= 0)
        out[m] = np.stack([zero, 1.0 - t, t], axis=1)[m]
        t = d2 / (d2 - d6)
        m = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
        out[m] = np.stack([1.0 - t, zero, t], axis=1)[m]
        out[(d6 >= 0) & (d5 <= d6)] = (0.0, 0.0, 1.0)
        t = d1 / (d1 - d3)
        m = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
        out[m] = np.stack([1.0 - t, t, zero], axis=1)[m]
        out[(d3 >= 0) & (d4 <= d3)] = (0.0, 1.0, 0.0)
        out[(d1 <= 0) & (d2 <= 0)] = (1.0, 0.0, 0.0)
    bad = ~np.isfinite(out).all(axis=1)
    if bad.any():
        corner = np.argmin(np.stack([(ap * ap).sum(1), (bp * bp).sum(1), (cp * cp).sum(1)], axis=1), axis=1)
        out[bad] = np.eye(3)[corner[bad]]
    out = np.clip(out, 0.0, None)
    return out / out.sum(axis=1, keepdims=True)


def _transfer_nearest(p, verts, tris, tri, W):
    """Per-vertex values carried to points from the closest point of a chosen triangle each, interpolated
    barycentrically (the Data Transfer modifier's Nearest Face Interpolated mapping).
    p: (n, 3) points; verts: (v, 3) and tris: (t, 3) the source surface, in the same space (metres);
    tri: (n,) the source triangle of each point (its nearest, from a BVH); W: (v, k) per-vertex values.
    Returns ((n, k) values at the closest points, (n,) distances from the points to them)."""
    p = np.asarray(p, dtype=np.float64).reshape(-1, 3)
    verts = np.asarray(verts, dtype=np.float64).reshape(-1, 3)
    W = np.asarray(W, dtype=np.float64)
    c = np.asarray(tris, dtype=np.int64).reshape(-1, 3)[np.asarray(tri, dtype=np.int64)]
    a, b, d = verts[c[:, 0]], verts[c[:, 1]], verts[c[:, 2]]
    bc = _closest_barycentric(p, a, b, d)
    q = bc[:, 0:1] * a + bc[:, 1:2] * b + bc[:, 2:3] * d
    values = bc[:, 0:1] * W[c[:, 0]] + bc[:, 1:2] * W[c[:, 1]] + bc[:, 2:3] * W[c[:, 2]]
    return values, np.linalg.norm(p - q, axis=1)


def _smooth_weights(W, edges, iterations, factor=0.5):
    """Laplacian smoothing of per-vertex weight rows: every iteration moves each row `factor` of the way
    to the mean of its edge neighbours' rows; a vertex without edges keeps its row.
    W: (n, k); edges: (e, 2) vertex index pairs, each edge once; iterations: 0 returns a copy of W.
    Returns a new (n, k) float64 array."""
    W = np.array(W, dtype=np.float64)
    e = np.asarray(edges, dtype=np.int64).reshape(-1, 2)
    if iterations <= 0 or not len(e):
        return W
    deg = np.bincount(e.ravel(), minlength=len(W)).astype(np.float64)
    has = deg > 0
    for _ in range(iterations):
        acc = np.zeros_like(W)
        np.add.at(acc, e[:, 0], W[e[:, 1]])
        np.add.at(acc, e[:, 1], W[e[:, 0]])
        W[has] += factor * (acc[has] / deg[has, None] - W[has])
    return W


def _world(p, mw):
    m = np.array(mw, dtype=np.float64)
    return p @ m[:3, :3].T + m[:3, 3]


def _mesh_arrays(me):
    """(vertex positions (n, 3) float64, loop triangles (t, 3) int64, edges (e, 2) int64) of a mesh."""
    co = np.empty(3 * len(me.vertices), np.float32)
    me.vertices.foreach_get('co', co)
    me.calc_loop_triangles()
    t = np.empty(3 * len(me.loop_triangles), np.int32)
    me.loop_triangles.foreach_get('vertices', t)
    e = np.empty(2 * len(me.edges), np.int32)
    me.edges.foreach_get('vertices', e)
    return (co.reshape(-1, 3).astype(np.float64), t.reshape(-1, 3).astype(np.int64),
            e.reshape(-1, 2).astype(np.int64))


def _seen_islands(pw, tris, labels, heads, tails, chunk=1024):
    """Labels of the islands (_islands) with a vertex that gets bone heat: a straight ray from the vertex
    to the closest point of one of its closest bones (_heat_closest) hits no triangle, tested the way
    Blender's bone heat tests it. pw: (n, 3) world positions; tris: (t, 3); labels: (n,); heads, tails:
    (m, 3) world bone ends of the deform bones. Each island stops at its first such vertex in index
    order. Returns the labels, ascending."""
    normals = _vertex_normals(pw, tris)
    bvh = BVHTree.FromPolygons(pw.tolist(), tris.tolist(), all_triangles=True)
    order = np.argsort(labels, kind='stable')
    seen = []
    for ids in np.split(order, np.flatnonzero(np.diff(labels[order])) + 1):
        for s in range(0, len(ids), chunk):
            part = ids[s:s + chunk]
            close, ends = _heat_closest(pw[part], normals[part], heads, tails)
            if any(_sees(pw[i], ends[r, j], bvh) for r, i in enumerate(part.tolist())
                   for j in np.flatnonzero(close[r]).tolist()):
                seen.append(int(labels[ids[0]]))
                break
    return sorted(seen)


def _sees(v, end, bvh):
    """Blender's heat_ray_source_visible: the ray from v toward the bone point end, starting 1e-5 of the
    way along and stopping 1e-5 short of it, hits nothing."""
    vec = end - v
    length = float(np.linalg.norm(vec))
    if length == 0.0:
        return True
    hit = bvh.ray_cast(Vector((v + vec * 1e-5).tolist()), Vector((vec / length).tolist()), length * (1.0 - 2e-5))
    return hit[2] is None


def heat_proxy_weights(obj_name, rig_name, allowed, fixed=None, voxel=0.01, smooth=0, thickness=2.0,
                       influences=MAX_INFLUENCES):
    """Blender's bone heat solved on a watertight voxel proxy of the mesh and carried back to it by
    nearest-surface interpolation, in place of the distance weights on the body (distance_weights first);
    then vhd_weights' rules, as heat_weights applies them.
    Bone heat on the mesh itself fails for every bone at once when any island has no vertex that sees its
    closest bone, which open shells nested in other shells cause. The proxy is one closed surface per
    connected volume: a temporary object with the mesh's faces (fixed parts left out: their weights are
    fixed anyway and gear would bridge limbs), a Solidify slab of `thickness` voxels grown outward along
    the normals, so open shells, which a voxel remesh drops, become closed and the original surface stays
    on the slab's inner face where the bones are in sight; then a Remesh modifier in Voxel mode, applied.
    Proxy islands without a vertex that gets heat are dropped before the solve, because one of them makes
    the solve fail for every bone. The proxy is parented with automatic weights as heat_weights does, its
    weights are smoothed `smooth` times over its edges, and each vertex takes the weights interpolated at
    the closest point of the proxy's nearest triangle. Every temporary object and mesh is removed; the
    mesh's parent, modifiers, selection, visibility and active object stay as they were.
    voxel: the remesh voxel size, metres in the mesh's local space; gaps narrower than about
    (2 * thickness + 1) voxels close in the proxy and heat crosses them. smooth: smoothing iterations of
    the proxy's weights (0: none). thickness: the Solidify slab in voxels (0: no Solidify, closed shells only).
    Needs both objects in Object mode. Raises RuntimeError, with
    the weights unchanged, when the grid would be more than PROXY_MAX_CELLS voxels across, or the proxy has
    no surface, no island that gets heat, or no heat weights.
    Returns {'weights': 'heat_proxy', 'voxel', 'thickness', 'smooth', 'proxy_verts': vertices of the solved
    proxy, 'proxy_islands': its islands, 'islands_dropped', 'no_heat': vertices of non-fixed parts without
    any transferred weight, 'no_heat_parts': {part: count}, 'far': non-fixed vertices more than
    (thickness + 2) voxels from the proxy: either their shell is missing from it, or they lie inside it
    where the volumes of two parts merge and the remesh fills the notch between them (the midline
    between the legs), with weights blended from both like their neighbours' (a finer voxel need not
    bring the second kind within reach: the bound scales with the voxel, the distance of a vertex inside
    merged volumes can shrink more slowly than it, and the solve's time grows with the cells, so look at
    where the far vertices lie, at their weights against their neighbours' and at the pose captures before
    spending solve time on a finer voxel), 'far_parts': {part: count}, 'far_visible_parts': {part: far
    vertices in sight, those whose ray along the vertex normal leaves the mesh without hitting it (the others
    lie under another surface, such as a body under clothes, or in a deep crease)}, 'far_visible_verts' and
    'far_enclosed_verts': {part: [the indices of the far vertices in sight, and of the others]},
    'max_distance': metres, 'distance_kept', 'distance_kept_parts', 'distance_kept_verts' (as for
    vhd_weights), 'max_influences'}."""
    fixed = fixed or {}
    if not voxel > 0 or thickness < 0 or smooth < 0:
        raise ValueError('heat_proxy_weights: voxel must be > 0, thickness and smooth >= 0')
    ob, rig = bpy.data.objects[obj_name], bpy.data.objects[rig_name]
    from lpk.stages import view
    window = view.window_context()
    for o in (ob, rig):
        if o.mode != 'OBJECT':
            raise RuntimeError('heat_proxy_weights needs Object mode; %s is in %s mode' % (o.name, o.mode))
    deform = [b for b in rig.data.bones if b.use_deform]
    if not deform:
        raise RuntimeError('heat_proxy_weights: %s has no deform bones' % rig.name)
    names = [b.name for b in deform]
    rw = rig.matrix_world
    heads = np.array([tuple(rw @ b.head_local) for b in deform], dtype=np.float64)
    tails = np.array([tuple(rw @ b.tail_local) for b in deform], dtype=np.float64)
    me = ob.data
    n = len(me.vertices)
    co = np.empty(3 * n, np.float32)
    me.vertices.foreach_get('co', co)
    co = co.reshape(-1, 3).astype(np.float64)
    parts = list(ob['parts'])
    pa = np.empty(n, np.int32)
    me.attributes['part'].data.foreach_get('value', pa)
    is_fixed = np.array([p in fixed for p in parts], dtype=bool)[pa]
    fx = is_fixed.tolist()
    faces = [tuple(p.vertices) for p in me.polygons if not all(fx[i] for i in p.vertices)]
    if not faces:
        raise RuntimeError('heat_proxy_weights: every face of %s belongs to a fixed part' % ob.name)
    span = float((co.max(axis=0) - co.min(axis=0)).max()) + 2.0 * thickness * voxel
    if span / voxel > PROXY_MAX_CELLS:
        raise RuntimeError('heat_proxy_weights: voxel %g m gives %d cells across the %.3g m mesh; use a voxel of '
                           'at least %.3g m' % (voxel, span / voxel, span, span / PROXY_MAX_CELLS))
    mw = ob.matrix_world.copy()
    vl = bpy.context.view_layer
    selected = {o.name for o in vl.objects if o.select_get()}
    active = vl.objects.active
    rig_hidden = rig.hide_get()
    proxy = src = pme = None
    try:
        src = bpy.data.meshes.new(ob.name + '_HeatProxy')
        src.from_pydata(co.tolist(), [], faces)
        proxy = bpy.data.objects.new(ob.name + '_HeatProxy', src)
        ob.users_collection[0].objects.link(proxy)
        proxy.matrix_world = mw
        if thickness > 0:
            m = proxy.modifiers.new('Solidify', 'SOLIDIFY')
            m.solidify_mode, m.thickness, m.offset = 'EXTRUDE', thickness * voxel, 1.0
            m.use_rim, m.use_even_offset = True, False
        m = proxy.modifiers.new('Remesh', 'REMESH')
        m.mode, m.voxel_size, m.adaptivity = 'VOXEL', voxel, 0.0
        vl.update()
        pme = bpy.data.meshes.new_from_object(proxy.evaluated_get(bpy.context.evaluated_depsgraph_get()))
        proxy.modifiers.clear()
        proxy.data = pme
        bpy.data.meshes.remove(src)
        src = None
        pv, pt, pe = _mesh_arrays(pme)
        if not len(pt):
            raise RuntimeError('the voxel remesh of %s left no surface (voxel %g m)' % (ob.name, voxel))
        labels = _islands(len(pv), pe)
        islands = len(np.unique(labels))
        seen = _seen_islands(_world(pv, mw), pt, labels, heads, tails)
        if not seen:
            raise RuntimeError('no island of the voxel proxy of %s gets bone heat: are the bones inside the mesh?'
                               % ob.name)
        drop = ~np.isin(labels, seen)
        if drop.any():
            bm = bmesh.new()
            try:
                bm.from_mesh(pme)
                bm.verts.ensure_lookup_table()
                bmesh.ops.delete(bm, geom=[bm.verts[i] for i in np.flatnonzero(drop).tolist()], context='VERTS')
                bm.to_mesh(pme)
            finally:
                bm.free()
            pme.update()
            pv, pt, pe = _mesh_arrays(pme)
        for o in vl.objects:
            o.select_set(False)
        rig.hide_set(False)
        for o in (proxy, rig):
            o.select_set(True)
        vl.objects.active = rig
        with bpy.context.temp_override(**window, active_object=rig, object=rig,
                                       selected_objects=[proxy, rig], selected_editable_objects=[proxy, rig]):
            res = bpy.ops.object.parent_set(type='ARMATURE_AUTO')
        if 'FINISHED' not in res:
            raise RuntimeError('bone heat parenting of the proxy did not finish: %s' % sorted(res))
        heat = _weights(proxy)
    finally:
        if proxy is not None:
            bpy.data.objects.remove(proxy, do_unlink=True)
            bpy.context.view_layer.update()  # a removed object stays as None in view_layer.objects until an update
        for m in (src, pme):
            if m is not None:
                bpy.data.meshes.remove(m)
        for o in vl.objects:
            o.select_set(o.name in selected)
        rig.hide_set(rig_hidden)
        vl.objects.active = active
        vl.update()
    col = {nm: j for j, nm in enumerate(names)}
    W = np.zeros((len(heat), len(names)))
    for i, w in enumerate(heat):
        for nm, x in w.items():
            if nm in col:
                W[i, col[nm]] = x
    if not W.any():
        raise RuntimeError('bone heat found no solution on the voxel proxy of %s (%d vertices, %d islands)'
                           % (ob.name, len(pv), len(seen)))
    W = _smooth_weights(W, pe, smooth)
    pw, cw = _world(pv, mw), _world(co, mw)
    bvh = BVHTree.FromPolygons(pw.tolist(), pt.tolist(), all_triangles=True)
    todo = np.flatnonzero(~is_fixed)
    tri = np.array([bvh.find_nearest(Vector(cw[i].tolist()))[2] for i in todo.tolist()], dtype=np.int64)
    R, dist = _transfer_nearest(cw[todo], pw, pt, tri, W)
    row = np.full(n, -1, dtype=np.int64)
    row[todo] = np.arange(len(todo))
    # A vertex whose shell the proxy holds lies on that shell's slab: its inner face runs through the
    # vertex and its outer face `thickness` voxels out, each up to about sqrt(3)/2 of a voxel off after
    # the remesh. So the nearest proxy surface lies at most about thickness + 1.7 voxels away, even where
    # the remesh lost the inner face; farther than thickness + 2, the proxy lost the vertex's shell, or
    # the vertex lies inside the proxy where two parts' volumes merged over it.
    far_at = (thickness + 2.0) * voxel
    ws, kept, no_heat, by_part, far, far_parts = _weights(ob), {}, 0, {}, 0, {}
    far_ids = []
    for i in range(n):
        part = parts[pa[i]]
        if part in fixed:
            ws[i] = dict(fixed[part]); continue
        r = R[row[i]]
        if dist[row[i]] > far_at:
            far += 1
            far_parts[part] = far_parts.get(part, 0) + 1
            far_ids.append(i)
        w = {names[j]: float(r[j]) for j in np.flatnonzero(r > 0).tolist()}
        if not w:
            no_heat += 1
            by_part[part] = by_part.get(part, 0) + 1
        w = _limit({nm: x for nm, x in w.items() if nm in allowed[part]}, influences)
        if w:
            ws[i] = w
        else:
            kept.setdefault(part, []).append(i)
    _set_weights(ob, ws)
    visible, enclosed = {}, {}
    if far_ids:
        _, mesh_tris, _ = _mesh_arrays(me)
        nrm = np.empty(3 * n, np.float32)
        me.vertices.foreach_get('normal', nrm)
        nrm = _unit(nrm.reshape(-1, 3).astype(np.float64) @ np.array(mw, dtype=np.float64)[:3, :3].T)
        for i, inside in zip(far_ids, _enclosed(cw[far_ids], nrm[far_ids], cw, mesh_tris)):
            (enclosed if inside else visible).setdefault(parts[pa[i]], []).append(i)
    return {'weights': 'heat_proxy', 'voxel': voxel, 'thickness': thickness, 'smooth': smooth,
            'proxy_verts': len(pv), 'proxy_islands': len(seen), 'islands_dropped': islands - len(seen),
            'no_heat': no_heat, 'no_heat_parts': dict(sorted(by_part.items())), 'far': far,
            'far_parts': dict(sorted(far_parts.items())),
            'far_visible_parts': {p: len(v) for p, v in sorted(visible.items())},
            'far_visible_verts': dict(sorted(visible.items())), 'far_enclosed_verts': dict(sorted(enclosed.items())),
            'max_distance': round(float(dist.max()), 6) if len(dist) else 0.0,
            **_kept_report(kept), 'max_influences': max((len(w) for w in ws), default=0)}


def _enclosed(origins, normals, verts, tris, eps=1e-4):
    """Per origin, whether a ray from it along its normal (started eps metres off it) hits the surface
    (verts (v, 3), tris (t, 3), the origins' space): True for a vertex under another surface or facing
    one across a deep crease, False for one in sight from outside along its normal. Returns [bool]."""
    bvh = BVHTree.FromPolygons(np.asarray(verts).tolist(), np.asarray(tris).tolist(), all_triangles=True)
    out = []
    for p, d in zip(np.asarray(origins).tolist(), np.asarray(normals).tolist()):
        if not any(d):
            out.append(False)
            continue
        start = Vector(p) + Vector(d) * eps
        out.append(bvh.ray_cast(start, Vector(d))[0] is not None)
    return out


def _keep_distance(obj_name, rig_name, allowed, fixed=None, influences=MAX_INFLUENCES):
    """The 'distance' backend: the distance weights already on the body (distance_weights') stay, under the
    limit they were made with
    (influences is taken for the backends' common call and not used). Returns {'weights': 'distance',
    'max_influences': the most bones weighting one vertex}."""
    return {'weights': 'distance',
            'max_influences': max((len(w) for w in _weights(bpy.data.objects[obj_name])), default=0)}


# The weights backends bound to their implementations, in auto's order of preference: {name: (the function
# that replaces the distance weights on the body, whether it can run in this session)}. Every implementation
# runs on the distance weights already on the body (distance_weights') and leaves a vertex it gives no weight
# on them.
WEIGHTS = {'vhd': (vhd_weights, lambda: vhd_exe() is not None), 'heat_proxy': (heat_proxy_weights, lambda: True),
           'heat': (heat_weights, lambda: True), 'distance': (_keep_distance, lambda: True)}
# The backend names weights() takes besides AUTO, in WEIGHTS order.
BACKENDS = tuple(WEIGHTS)
# The backend name that tries the available backends in order.
AUTO = 'auto'


def available_backends():
    """The weight backends usable in this session, in the order weights(backend='auto') tries them: 'vhd'
    when the add-on and its binary for this platform are present, and 'heat_proxy', 'heat' and 'distance'
    always (WEIGHTS)."""
    return [name for name, (_, usable) in WEIGHTS.items() if usable()]


def weights(obj_name, rig_name, allowed, fixed=None, backend=AUTO, influences=MAX_INFLUENCES):
    """Replace the distance weights on the body with a backend's (distance_weights first): 'vhd' (vhd_weights
    with its defaults), 'heat_proxy' (heat_proxy_weights with its defaults), 'heat' (heat_weights),
    'distance' (keep them), or 'auto': the first of available_backends() that runs without an error, so
    vhd, then heat_proxy, heat and distance. A backend that fails leaves the weights as they were.
    influences: the backend's limit of bones per vertex (as for distance_weights).
    Returns the backend's report plus {'backend': the backend that ran, 'requested': `backend`, 'available':
    available_backends() in this session}; 'auto' adds 'skipped': [{'backend', 'error'}] for the backends
    that failed before it. Raises ValueError for an unknown backend name."""
    if backend != AUTO and backend not in WEIGHTS:
        raise ValueError('weights backend %r: use one of %s, %s' % (backend, ', '.join(BACKENDS), AUTO))
    available = available_backends()
    if backend != AUTO:
        return dict(WEIGHTS[backend][0](obj_name, rig_name, allowed, fixed, influences=influences), backend=backend,
                    requested=backend, available=available)
    skipped = []
    for name in available:
        try:
            rep = WEIGHTS[name][0](obj_name, rig_name, allowed, fixed, influences=influences)
        except (RuntimeError, OSError, subprocess.SubprocessError) as e:
            skipped.append({'backend': name, 'error': str(e)[-300:]})
            continue
        return dict(rep, backend=name, skipped=skipped, requested=AUTO, available=available)


def join_zones(ob, pairs, rings, layer='join_loop'):
    """[(zone vertex ids, the parent's hole loop, caps)] per concrete (parent part, child part, caps) of
    `pairs`, in their order. The loop is the parent's vertices tagged 1 in the int vertex `layer` next to the
    child (adjacency alone also catches parent vertices that ridge_flip connected to the limb); the zone
    grows the loop and the child's first ring by `rings` edges."""
    me = ob.data; parts = list(ob['parts']); pa = [a.value for a in me.attributes['part'].data]
    tag = [a.value for a in me.attributes[layer].data]
    adj = [set() for _ in me.vertices]
    for e in me.edges:
        a, b = e.vertices; adj[a].add(b); adj[b].add(a)
    out = []
    for parent, child, caps in pairs:
        pid, cid = parts.index(parent), parts.index(child)
        first = {i for i in range(len(adj)) if pa[i] == cid and any(pa[j] == pid for j in adj[i])}
        loop = {j for i in first for j in adj[i] if pa[j] == pid and tag[j]}
        zone = loop | first
        for _ in range(rings):
            zone |= {j for i in zone for j in adj[i]}
        out.append((zone, loop, dict(caps or {})))
    return out


def _nnls_sum1(A, b, lam=10.0):
    """min |Ax - b| with x >= 0 and sum(x) = 1 (a row weighted lam): drop the most negative until none."""
    n = A.shape[1]
    A2 = np.vstack([A, lam * np.ones((1, n))]); b2 = np.concatenate([b, [lam]])
    act = list(range(n))
    while act:
        x = np.linalg.lstsq(A2[:, act], b2, rcond=None)[0]
        if x.min() >= 0:
            out = np.zeros(n); out[act] = x
            return out
        act.pop(int(np.argmin(x)))
    return np.zeros(n)


def smooth_zones(obj_name, rig_name, allowed, pairs, fixed=None, rings=2, poses=240, twist=45.0, seed=1,
                 iterations=10, factor=0.5, mirror=True, influences=MAX_INFLUENCES):
    """Corrective Smooth baked into the weights of the join zones (the idea of the VHD add-on's
    Corrective Smooth Baker): random poses (each bone turned up to `twist` degrees about one axis)
    give the smoothed shape as the target, and every zone vertex takes the non-negative weights over
    its part's allowed bones that reproduce it best, under the export limits (`influences` as for
    distance_weights). pairs: concrete (parent part, child part, caps) joins in zone order (join_zones); caps
    {bone: share} pins those shares on the parent's hole loop; a cap under MIN_WEIGHT is dropped by the
    limit.
    A cap trades one deformation for another: without one the solve can give the hole loop enough of the
    limb's first bone that a raised limb lifts the parent's side with it; a cap on the limb's bone (its share
    pinned on the loop) keeps the side but can kink the top of the joint and raise its stretch. No cap fixes
    a hole in the wrong place: an armhole far below the shoulder (a sleeve welded down the body's side)
    leaves the deep armpit stretched under a low cap and drags the side with the arm under a high one.
    Then the right side mirrors the left, which the random poses leave uneven, one side of a joint moving
    more than the other. The bake starts from the current weights: the same weights and seed bake the
    same result up to floating-point rounding, while a bake on baked weights gives other weights, so the
    bake runs once on each run's backend weights (skin runs it right after the backend).
    mirror: True or 'all' mirrors every right-side vertex that has a left twin; 'zones' only the join
    zones' vertices, so the rest keeps the backend's weights (asymmetric gear away from the joins);
    False mirrors nothing (an asymmetric model: each side keeps its own solve, uneven as the random
    poses left it). Returns {'smooth_baked': zone vertices solved, 'mirror_unmatched': right-side
    vertices it was asked to mirror that have no left twin (None when mirror is False),
    'mirror_unmatched_parts': {part: those vertices}, 'mirror_unmatched_verts': {part: [their indices]}
    (both None when mirror is False)}."""
    if mirror not in (True, False, 'all', 'zones'):
        raise ValueError("smooth_zones mirror=%r: use True, 'all', 'zones' or False" % (mirror,))
    fixed = fixed or {}
    ob, rig = bpy.data.objects[obj_name], bpy.data.objects[rig_name]
    parts = list(ob['parts']); pa = ob.data.attributes['part'].data
    names = [b.name for b in rig.data.bones if b.use_deform]
    rest = np.array([tuple(v.co) + (1.0,) for v in ob.data.vertices])
    T = np.array(rig.matrix_world.inverted() @ ob.matrix_world); Ti = np.linalg.inv(T)
    mod = ob.modifiers.new('SmoothBake', 'CORRECTIVE_SMOOTH')
    mod.iterations, mod.factor, mod.smooth_type = iterations, factor, 'LENGTH_WEIGHTED'
    mod.rest_source, mod.use_pin_boundary = 'ORCO', True
    rng = random.Random(seed)
    targets, mats = [], []
    try:
        for _ in range(poses):
            for pb in rig.pose.bones:
                pb.rotation_mode = 'XYZ'; pb.location = (0, 0, 0)
                e = [0.0, 0.0, 0.0]; e[rng.randrange(3)] = math.radians(rng.uniform(-twist, twist))
                pb.rotation_euler = e
            bpy.context.view_layer.update()
            ev = ob.evaluated_get(bpy.context.evaluated_depsgraph_get()); me = ev.to_mesh()
            targets.append(np.array([tuple(v.co) for v in me.vertices]))
            ev.to_mesh_clear()
            # Skinning matrix in mesh space: armature-space pose * rest^-1, conjugated by the mesh frame.
            mats.append({n: Ti @ np.array(rig.pose.bones[n].matrix @ rig.data.bones[n].matrix_local.inverted()) @ T
                         for n in names})
    finally:
        for pb in rig.pose.bones:
            pb.rotation_euler = (0, 0, 0)
        ob.modifiers.remove(mod)
        bpy.context.view_layer.update()
    # Zones of neighbouring joins overlap (the right shoulder's reaches the left armhole over the
    # chest), so the caps belong to the loop vertices, not to the zone being solved.
    zone, pins = set(), {}
    for z, loop, caps in join_zones(ob, pairs, rings):
        zone |= z
        for i in loop:
            pins.setdefault(i, {}).update(caps)
    ws, done = _weights(ob), 0
    for i in sorted(zone):
        part = parts[pa[i].value]
        if part in fixed:
            continue
        bones = [n for n in allowed[part] if n in names]
        A = np.zeros((3 * poses, len(bones))); b = np.zeros(3 * poses)
        for k in range(poses):
            for j, n in enumerate(bones):
                A[3 * k:3 * k + 3, j] = (mats[k][n] @ rest[i])[:3]
            b[3 * k:3 * k + 3] = targets[k][i]
        pin = {n: x for n, x in pins.get(i, {}).items() if n in bones}
        if pin:
            fix = [j for j, n in enumerate(bones) if n in pin]
            free = [j for j in range(len(bones)) if j not in fix]
            left = 1.0 - sum(pin.values())
            x = np.zeros(len(bones))
            x[free] = _nnls_sum1(A[:, free] * left, b - sum(A[:, j] * pin[bones[j]] for j in fix)) * left
            for j in fix:
                x[j] = pin[bones[j]]
        else:
            x = _nnls_sum1(A, b)
        w = _limit({bones[j]: x[j] for j in range(len(bones))}, influences)
        if w:
            ws[i] = w; done += 1
    unmatched = unmatched_parts = unmatched_verts = None
    if mirror:
        ws, missed = _mirror(ob, ws, only=zone if mirror == 'zones' else None)
        unmatched, unmatched_verts = len(missed), {}
        for i in missed:
            unmatched_verts.setdefault(parts[pa[i].value], []).append(i)
        unmatched_parts = {p: len(v) for p, v in unmatched_verts.items()}
    _set_weights(ob, ws)
    return {'smooth_baked': done, 'mirror_unmatched': unmatched, 'mirror_unmatched_parts': unmatched_parts,
            'mirror_unmatched_verts': unmatched_verts}


def _mirror(ob, ws, eps=1e-4, only=None):
    """The right side (x < 0) takes its left twin's weights with .L and .R swapped; vertices with no
    twin (asymmetric gear) keep theirs. only: the vertex ids that may change (None: every one); the
    unmatched ones listed are only among them. Returns (the weights, [vertex ids without a twin])."""
    vs = ob.data.vertices
    kd = kdtree.KDTree(len(vs))
    for v in vs:
        kd.insert(v.co, v.index)
    kd.balance()
    swap = lambda n: n[:-1] + {'L': 'R', 'R': 'L'}[n[-1]] if n.endswith(('.L', '.R')) else n
    out, missed = list(ws), []
    for v in vs:
        if v.co.x < -eps and (only is None or v.index in only):
            _, j, d = kd.find((-v.co.x, v.co.y, v.co.z))
            if d > eps:
                missed.append(v.index)
            else:
                out[v.index] = {swap(n): x for n, x in ws[j].items()}
    return out, missed


# -- the rig and its skin ---------------------------------------------------------------------------------

# Metres below which a bone's head and tail count as one point: Blender drops a bone of (near) zero length
# when it leaves edit mode, so such a bone is refused instead.
BONE_MIN_M = 1e-6
# The keys of an extra bone (build_rig's extra_bones): required, then optional.
EXTRA_KEYS = (('head', 'tail', 'parent'), ('roll', 'deform'))


def bone_table(template, joints, extra_bones=None):
    """The bones of a rig of the skeleton template `template` (lpk.skeletons), in creation order:
    [{'name', 'head', 'tail', 'parent', 'connect', 'roll', 'deform'}].

    joints: {template bone name: (head, tail)}, points (x, y, z) in metres in the body's own space. The rig
    has every bone the template does not mark optional and the optional bones `joints` names, under the
    option values those bones give (lpk.skeletons.options_for: a chain's bones from 1 without a gap, a
    choice's bones complete), in the template's order with a chain longer than its listed bones going on
    after its last listed bone (lpk.skeletons.bones_for). Each takes the template's parent and connection and
    the template's roll rule (lpk.skeletons.roll: the direction its Z axis is aligned to at rest), and
    deforms. extra_bones: {name: {'head', 'tail', 'parent', 'roll'?, 'deform'?}}, the model's own bones, after
    the template's in their order: parent a bone of the template's in the rig, an earlier extra bone, or
    None; unconnected; roll the direction (x, y, z), the roll rule's default when absent; deform True when
    absent. head and tail come back as float tuples.
    Raises ValueError, one line per problem: optional bones that give no option value, a joint naming no
    bone of the template, a required bone without a joint, an extra bone named like a template bone or with
    keys other than EXTRA_KEYS or a parent that is no bone before it, and a bone whose head and tail lie
    within BONE_MIN_M."""
    extra = dict(extra_bones or {})
    wanted = skeletons.bones_for(template, skeletons.options_for(template, joints))
    names = [b['name'] for b in wanted]
    problems = []
    for bone in joints:
        if bone in names:
            continue
        if skeletons.role_of(bone, template) is None:
            problems.append('joints[%r]: the skeleton template %r has no bone %r; give a bone of the model in '
                            'extra_bones' % (bone, template, bone))
        else:
            problems.append('joints[%r]: an optional bone no option of %r requires' % (bone, template))
    missing = [n for n in names if n not in joints]
    if missing:
        problems.append('joints lacks the required bones %s: give each (head, tail)' % ', '.join(missing))
    out = [{'name': b['name'], 'parent': b['parent'], 'connect': b['connect'],
            'roll': skeletons.roll(b['name'], template), 'deform': True, 'at': joints.get(b['name'])}
           for b in wanted if b['name'] in joints]
    known = list(names)
    required, optional = EXTRA_KEYS
    for name, spec in extra.items():
        where = 'extra_bones[%r]' % (name,)
        if not (isinstance(spec, dict) and set(required) <= set(spec) <= set(required + optional)):
            problems.append('%s: give {%s} and optionally %s' % (where, ', '.join(required), ', '.join(optional)))
            continue
        if skeletons.role_of(name, template) is not None:
            problems.append('%s: the skeleton template %r has a bone %r; give it in joints, or give the model '
                            'bone another name' % (where, template, name))
        elif spec['parent'] is not None and spec['parent'] not in known:
            problems.append('%s: the parent %r is no bone of the rig; name a bone of the template the rig has or '
                            'an extra bone given before it' % (where, spec['parent']))
        known.append(name)
        roll = spec.get('roll')
        out.append({'name': name, 'parent': spec['parent'], 'connect': False,
                    'roll': skeletons.roll(name, template) if roll is None else tuple(float(c) for c in roll),
                    'deform': bool(spec.get('deform', True)), 'at': (spec['head'], spec['tail'])})
    for b in out:
        head, tail = (tuple(float(c) for c in p) for p in b.pop('at'))
        if math.dist(head, tail) < BONE_MIN_M:
            problems.append('%r: the head and the tail are one point %s' % (b['name'], head))
        b.update(head=head, tail=tail)
    if problems:
        raise ValueError('\n'.join(problems))
    return [{k: b[k] for k in ('name', 'head', 'tail', 'parent', 'connect', 'roll', 'deform')} for b in out]


def build_rig(obj_name, rig_name, template, joints, extra_bones=None):
    """The armature object `rig_name` of the body `obj_name`: the bones of bone_table(template, joints,
    extra_bones) in their order with their parents, connections and rolls, each deforming as its entry says
    (Blender's use_deform), in place of any object of that name, carrying the body's world transform. The
    body is parented to it with one Armature modifier and an identity local transform, so its own space is
    the armature's. Writes no vertex weights (skin does). Needs a window.
    Raises ValueError as bone_table, before anything changes. Returns {'bones': the armature's bone count,
    'deform': its deform bone count, 'object': the rig object's name, 'armature': its armature data's
    name}."""
    table = bone_table(template, joints, extra_bones)
    ob = bpy.data.objects[obj_name]
    bones = {b['name']: (Vector(b['head']), Vector(b['tail']), b['parent'], b['connect']) for b in table}
    rig = _armature(ob, rig_name, bones, {b['name']: Vector(b['roll']) for b in table})
    for b in table:
        rig.data.bones[b['name']].use_deform = bool(b['deform'])
    _bind(ob, rig)
    rig.select_set(False)
    return {'bones': len(rig.data.bones), 'deform': sum(1 for b in table if b['deform']), 'object': rig.name,
            'armature': rig.data.name}


def built_parts(obj_name):
    """The part names of the mesh object `obj_name` (its 'parts') that carry at least one vertex, in part
    order."""
    ob = bpy.data.objects[obj_name]
    names = list(ob['parts'])
    at = ob.data.attributes.get('part')
    if at is None or not len(ob.data.vertices):
        return []
    ids = np.empty(len(ob.data.vertices), np.int32)
    at.data.foreach_get('value', ids)
    used = set(np.unique(ids).tolist())
    return [p for i, p in enumerate(names) if i in used]


def distance_weights(obj_name, rig_name, allowed, fixed=None, influences=MAX_INFLUENCES):
    """The part-restricted distance weights of the rig's rest bones on the body (the 'distance' backend's
    weights, and the base every other backend keeps where it gives a vertex none): one vertex group per deform
    bone of the rig (use_deform) in its order, in place of the body's groups, so a bone that deforms nothing
    gets no group; a vertex of a part in `fixed` takes its fixed
    weights, any other the `influences` strongest inverse-distance weights over allowed[part], none under
    MIN_WEIGHT, renormalised. The body must be bound to the rig as build_rig binds it, so the rest bones'
    armature space is the mesh's own. Raises RuntimeError when the body's parent is not the rig. Returns
    {'weights': 'distance', 'max_influences': the most bones weighting one vertex}."""
    ob, rig = bpy.data.objects[obj_name], bpy.data.objects[rig_name]
    if ob.parent != rig:
        raise RuntimeError('%s is not bound to the rig %s: build the rig with build_rig first' % (obj_name, rig_name))
    segs = {b.name: (b.head_local.copy(), b.tail_local.copy()) for b in rig.data.bones if b.use_deform}
    return {'weights': 'distance',
            'max_influences': _write_distance_weights(ob, segs, allowed, fixed or {}, influences)}


def binding_problems(parts, bones, deform, allowed, fixed, joins=()):
    """What keeps a skin binding from weighting a body, [str], one line per problem; empty when it can.
    parts: the body's parts that carry vertices (built_parts); bones: the rig's bone names; deform: those
    that deform; allowed: {part: [bones]}; fixed: {part: {bone: weight}}; joins: [(parent part, child part,
    caps)] with every part among `parts`. Finds a built part with neither allowed bones nor fixed weights or
    with an empty bone list, bones the rig lacks, bones that deform nothing, and join parts the body does not
    carry."""
    out = []
    lacking = [p for p in parts if p not in fixed and p not in allowed]
    if lacking:
        out.append('the built parts %s have no bones in allowed and no weights in fixed' % ', '.join(lacking))
    have, moving = set(bones), set(deform)
    unknown, still = {}, {}
    for p in parts:
        given = list(fixed[p]) if p in fixed else list(allowed.get(p, ()))
        if p in allowed and p not in fixed and not given:
            out.append('the built part %r takes no bone: give it bones in allowed' % p)
        if [b for b in given if b not in have]:
            unknown[p] = [b for b in given if b not in have]
        if [b for b in given if b in have and b not in moving]:
            still[p] = [b for b in given if b in have and b not in moving]
    if unknown:
        out.append('bones the rig lacks: %s' % '; '.join('%s: %s' % (p, ', '.join(b)) for p, b in unknown.items()))
    if still:
        out.append('bones that deform nothing: %s' % '; '.join('%s: %s' % (p, ', '.join(b)) for p, b in still.items()))
    for parent, child, _ in joins:
        gone = [p for p in (parent, child) if p not in parts]
        if gone:
            out.append('the join %s - %s names parts the body does not carry: %s' % (parent, child, ', '.join(gone)))
    return out


def skin(obj_name, rig_name, allowed, fixed=None, joins=None, backend='auto', influences=MAX_INFLUENCES,
         mirror=True):
    """The vertex weights of the body `obj_name` under the rig `rig_name` (build_rig), with the rig held in
    its rest pose for the call (lpk.stages.pose.held_pose: the pose it was in comes back): distance_weights,
    then the backend's weights over them (weights()), then, with joins, Corrective Smooth baked into their
    zones (smooth_zones with its defaults and `mirror`); each step ends with drop_zero_weights, so the body
    keeps no assignment of weight 0. The bake runs on this call's backend weights: run skin whole, not the
    bake alone on weights it baked before.

    allowed: {part: [bone names]}, the bones each part's vertices may take weight from (lpk.skeletons.sided
    expands '{s}' in model data; lpk.skeletons.part_binding gives the template's default); fixed: {part:
    {bone: weight}}, rigid parts; joins: [(parent part, child part, caps {bone: share})], the zones to
    smooth (join_zones), None or [] for none; backend: a name of BACKENDS or 'auto'; influences: bones per
    vertex the weights keep (the export target's limit). Raises ValueError, before any weight changes, with
    binding_problems' lines.

    Returns {'weights': weights()'s report plus 'zero_dropped' (the assignments of weight 0 removed after
    it), 'smooth': smooth_zones' report plus 'zero_dropped', or None without joins, 'influences'}."""
    fixed, joins = dict(fixed or {}), [tuple(j) for j in (joins or ())]
    bones = list(bpy.data.objects[rig_name].data.bones)
    problems = binding_problems(built_parts(obj_name), [b.name for b in bones], [b.name for b in bones if b.use_deform],
                                allowed, fixed, joins)
    if problems:
        raise ValueError('\n'.join(problems))
    with pose.held_pose(rig_name):
        distance_weights(obj_name, rig_name, allowed, fixed, influences)
        rep = dict(weights(obj_name, rig_name, allowed, fixed, backend=backend, influences=influences),
                   zero_dropped=drop_zero_weights(obj_name))
        smooth = None
        if joins:
            smooth = dict(smooth_zones(obj_name, rig_name, allowed, joins, fixed, mirror=mirror, influences=influences),
                          zero_dropped=drop_zero_weights(obj_name))
    return {'weights': rep, 'smooth': smooth, 'influences': influences}
