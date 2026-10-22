"""UV unwrap and pack of the colour atlas, and the bake of flat colour into it.

The atlas holds each face's palette colour and the colour sources baked over it in bake order, with an
optional grit; no light is baked into it. The body's final material shows the atlas (_final_material,
FINAL_MATERIALS): shading belongs to the runtime shader, which the preview (lpk.stages.preview) only
imitates.

The entries take plain arguments and return plain dicts: unwrap (the UVs, not packed), pack_step (one pack
of the whole atlas; repeat it until the face island's size settles, with an optional pack cache) and bake
(the recolour of Col, the bake with the colour sources, the final material on the body's slot 0). Under a
frozen texture (ARCHITECTURE.md "Build modes") store_image keeps a copy of the atlas packed in the .blend,
bake_over composites new colour sources over it without touching any other texel, and stamp_image and
image_edited guard a hand-painted atlas. `atlas`
is (size in pixels, {group: relative texel density}) throughout; sheet_of(colour, part) places each face in
a group, and the parts of `own` ({part: material name}) lie outside the atlas with a material of their own.
"""
import base64
from contextlib import contextmanager
import hashlib
import json
import math
import os
import zlib

import bpy, bmesh
import numpy as np
from mathutils import Vector

from lpk.stages import imaging, preview, zones
from lpk.stages.checks import POSITION_NOISE

GRIT = (0.86, 0.85, 0.88, 1)
# The UV layer the unwrap makes on the body and the pack and the bake read: the atlas UVs.
UV_LAYER = 'UVMap'
# Metres a colour source's bake rays start above the body (cage) and run from there (ray), unless the
# source sets its own ('cage' and 'ray' of bake's sources): a source surface reaches the bake between cage
# above the body and ray - cage below it.
BAKE_CAGE, BAKE_RAY = 0.015, 0.03
# Texels the bake extends each island's colours beyond its border: nearest-texel and filtered sampling at
# a border read texels just outside it.
BAKE_MARGIN = 2
# The property of the atlas image '<NAME>_Atlas' holding the digest of the texels the bake wrote
# (stamp_image): a frozen-texture bake refuses an atlas painted by hand since.
IMAGE_STAMP = 'lpk_texels'
# Texels a painted line must span across to bake unbroken. A line at least one texel wide keeps a
# texel centre in every texel column (or row) it crosses, at any angle, and the bake samples texel
# centres; a thinner one misses the centres where it runs between them and bakes as dashes, or not at
# all where it runs along a row of texels between two rows of centres.
MIN_LINE_TEXELS = 1.0
# The object property that holds the painted marks a builder recorded (marks_text), as JSON.
MARKS = 'lpk_marks'
# How the packer may turn islands: by quarter turns only, which keeps the strips and the islands
# _orient_islands lined up with the texel rows straight.
PACK_ROTATE = 'CARDINAL'
# The prefix of the atlas group of an `own` part's material: its faces lie outside the atlas.
OWN_PREFIX = 'Own:'
# The pack steps the pack cache holds, the latest kept: the packs of a chain from an unchanged unwrap, and
# of a few variants of a layout switched back and forth, find theirs.
PACK_CACHE_ENTRIES = 24


def _base_links(nt, tex, bsdf):
    """The 'base' final material: the image as the base colour only, which every final material links."""


def _emission_links(nt, tex, bsdf):
    """The 'emission' final material: the image also as the emission, at strength 1, so renders show the
    atlas unlit like the runtime target."""
    nt.links.new(tex.outputs['Color'], bsdf.inputs['Emission Color'])
    bsdf.inputs['Emission Strength'].default_value = 1.0



# The final materials bound to their implementations: {name: function(node tree, image node, Principled
# BSDF node)} adding what the material shows beyond the base colour link.
FINAL_MATERIALS = {'base': _base_links, 'emission': _emission_links}
# The final materials the kernels take (the keys of FINAL_MATERIALS), in order of preference.
MATERIALS = ('base', 'emission')
# The packer's island shapes (uv.pack_islands shape_method), the default first.
PACK_SHAPES = ('CONCAVE', 'CONVEX', 'AABB')
# The packer's margin methods (the margin_method of uv.pack_islands and uv.smart_project), the default first.
PACK_MARGINS = ('FRACTION', 'ADD', 'SCALED')


def _final_material(name, img, material='emission'):
    """Principled BSDF with the baked image as base colour: the FBX exporter only carries a
    diffuse map from a Principled base-colour link. material (FINAL_MATERIALS): 'emission' also
    feeds the image into the emission so renders stay unlit like the runtime target; 'base' leaves
    the emission off."""
    if material not in FINAL_MATERIALS:
        raise ValueError('final material %r: use one of %s' % (material, ', '.join(MATERIALS)))
    fm = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    fm.use_nodes = True
    nt = fm.node_tree; nt.nodes.clear()
    o = nt.nodes.new('ShaderNodeOutputMaterial'); bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled')
    t = nt.nodes.new('ShaderNodeTexImage'); t.image = img; t.interpolation = 'Closest'
    nt.links.new(t.outputs['Color'], bsdf.inputs['Base Color'])
    FINAL_MATERIALS[material](nt, t, bsdf)
    bsdf.inputs['Roughness'].default_value = 1.0
    nt.links.new(bsdf.outputs[0], o.inputs['Surface'])
    nt.nodes.active = t
    return fm


def _flat_material(name, colour, material='emission'):
    """The final material `material` (_final_material) in the flat linear RGBA `colour` instead of an image:
    every socket the image fed holds the colour. The placeholder of an `own` material the scene lacks."""
    fm = _final_material(name, None, material)
    nt = fm.node_tree
    t = nt.nodes.active
    for link in list(t.outputs['Color'].links):
        link.to_socket.default_value = colour
        nt.links.remove(link)
    nt.nodes.remove(t)
    return fm


def _own(group):
    """Whether an atlas group is an `own` part's (OWN_PREFIX): its faces lie outside the atlas."""
    return group.startswith(OWN_PREFIX)


def _own_sheet(sheet_of, own):
    """sheet_of with the parts of `own` ({part: material name}) placed in their own groups:
    (colour, part) -> OWN_PREFIX + the material for a part of `own`, else sheet_of(colour, part)."""
    def placed(colour, part):
        material = own.get(part)
        return sheet_of(colour, part) if material is None else OWN_PREFIX + material
    return placed


def _unwrap_own(me, ctx, ug, angle_limit, margin, margin_method):
    """Smart-project each group of the `own` parts (ug, each polygon's group) alone into the whole UV square,
    its own image's space: the smart projection packs its islands there with `margin` and `margin_method`
    (PACK_MARGINS). No density scaling follows (_finish_unwrap) and the atlas's pack leaves the group out
    (pack_step). Raises ValueError for an unknown margin_method."""
    if margin_method not in PACK_MARGINS:
        raise ValueError('margin_method %r: use one of %s' % (margin_method, ', '.join(PACK_MARGINS)))
    for g in dict.fromkeys(g for g in ug if _own(g)):
        _isolate(me, ug, g)
        _uv_ops(ctx, lambda: bpy.ops.uv.smart_project(angle_limit=math.radians(angle_limit), island_margin=margin,
                                                      margin_method=margin_method, area_weight=0.0,
                                                      correct_aspect=True, scale_to_bounds=False))


def _isolate(me, group_of, g):
    # UV operators in Blender 5 act on every visible face regardless of face selection,
    # so the other groups are hidden while one group is unwrapped or packed.
    for p in me.polygons:
        p.hide = group_of[p.index] != g
        p.select = not p.hide


def _uv_ops(ctx, op):
    with bpy.context.temp_override(**ctx):
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        op()
        bpy.ops.object.mode_set(mode='OBJECT')


def _group_areas(me, group_of):
    """{group: (uv area, surface area)} from the current UVs."""
    uv = me.uv_layers[UV_LAYER].data
    out = {}
    for p in me.polygons:
        a, b, c = (Vector(uv[li].uv) for li in p.loop_indices[:3])
        ua, sa = out.get(group_of[p.index], (0.0, 0.0))
        out[group_of[p.index]] = (ua + abs((b - a).cross(c - a)) / 2, sa + p.area)
    return out


# ---------------- colour-only atlas: shape in the mesh, colour detail in sources ----------------
#
# unwrap -> pack_step (repeat until the face area converges) -> bake.
# The atlas holds colour only, with the print grit where a model asks for it; shading is left to the
# runtime shader and to painted art shadows.


def _strip_check(bm, pid_layer, pid, n, part):
    """Raise ValueError unless the part's vertices are what _strip_uv unrolls: one Builder.loft of n
    sides, its rings in index order, each a closed loop of n vertices, and its cap apex last, joined to
    the last ring only. Anything else (another form in the part, an apex at the start, a wrong side
    count) would be unrolled into garbled UVs without an error."""
    vs = sorted((v for v in bm.verts if v[pid_layer] == pid), key=lambda v: v.index)
    fix = ("strips {%r: sides} needs the part to be one Builder.loft of that many sides with "
           "its cap apex last and nothing else in it" % part)
    if not isinstance(n, int) or isinstance(n, bool) or n < 3:
        raise ValueError('%s: %r is not a number of sides' % (fix, n))
    k = (len(vs) - 1) // n
    if k < 1 or len(vs) != k * n + 1:
        raise ValueError('%s: the part has %d vertices, not rings of %d plus an apex' % (fix, len(vs), n))
    base = vs[0].index
    if vs[-1].index - base != len(vs) - 1:
        raise ValueError('%s: its vertex indices are not one run' % fix)
    for i in range(k):
        for j in range(n):
            a, b = vs[i * n + j], vs[i * n + (j + 1) % n]
            if not any(e.other_vert(a) is b for e in a.link_edges):
                raise ValueError('%s: vertices %d and %d do not close ring %d' % (fix, a.index, b.index, i))
    apex = vs[-1]
    if any(e.other_vert(apex).index - base < (k - 1) * n for e in apex.link_edges):
        raise ValueError('%s: the last vertex is not a cap apex on the last ring' % fix)


def _check_strips(me, parts, strips):
    """_strip_check for every strip part the mesh has, before the unwrap changes anything."""
    if not any(p in parts for p in strips):
        return
    bm = bmesh.new(); bm.from_mesh(me)
    try:
        pl = bm.verts.layers.int['part']
        for part, sides in strips.items():
            if part in parts:
                _strip_check(bm, pl, parts.index(part), sides, part)
    finally:
        bm.free()


def _strip_uv(bm, uvl, pid_layer, pid, n):
    """Unroll a loft part into one straight strip: u across the ring (centred, per-ring perimeter),
    v along the path, so bands baked across it fall on texel rows. Needs Builder.loft's ring-major
    vertex order with the cap apex last and nothing else in the part (_strip_check)."""
    vs = sorted((v for v in bm.verts if v[pid_layer] == pid), key=lambda v: v.index)
    base = vs[0].index; k = (len(vs) - 1) // n; apex = vs[-1]
    rings = [vs[i * n:(i + 1) * n] for i in range(k)]
    cent = [sum((v.co for v in r), Vector()) / n for r in rings]
    perim = [sum((r[j].co - r[(j + 1) % n].co).length for j in range(n)) for r in rings]
    s = [0.0]
    for a, b in zip(cent, cent[1:]):
        s.append(s[-1] + (b - a).length)
    s_apex = s[-1] + (apex.co - cent[-1]).length
    for f in bm.faces:
        if f.verts[0][pid_layer] != pid:
            continue
        js = [(v.index - base) % n for v in f.verts if v is not apex]
        wrap = 0 in js and n - 1 in js          # the seam face takes column n, not 0
        for l in f.loops:
            v = l.vert
            if v is apex:
                jj = [j + n if (wrap and j == 0) else j for j in js]
                l[uvl].uv = ((sum(jj) / len(jj) / n - 0.5) * perim[-1], s_apex)
            else:
                i, j = divmod(v.index - base, n)
                if wrap and j == 0:
                    j = n
                l[uvl].uv = ((j / n - 0.5) * perim[i], s[i])


def _atlas_setup(obj_name, sheet_of, face_part, face_pred, strips):
    ob = bpy.data.objects[obj_name]
    me = ob.data
    vl = bpy.context.view_layer
    for o in vl.objects:
        o.select_set(False)
    ob.select_set(True); vl.objects.active = ob
    from lpk.stages import view
    ctx = dict(view.view3d_context(), active_object=ob, object=ob, selected_objects=[ob])
    parts = list(ob['parts']); palette = list(ob['palette'])
    pal = me.attributes['pal'].data
    pa = me.attributes['part'].data
    part_of = [parts[pa[p.vertices[0]].value] for p in me.polygons]
    group_of = [sheet_of(palette[pal[p.index].value], part_of[p.index]) for p in me.polygons]
    is_face = _is_face(me, part_of, face_part, face_pred)
    ug = ['Face' if f else ('Strip' if pn in strips else g) for f, g, pn in zip(is_face, group_of, part_of)]
    return ob, me, ctx, parts, part_of, is_face, ug


def _is_face(me, part_of, face_part, face_pred):
    """Per polygon of mesh `me`, whether it belongs to the face island: a polygon of face_part (part_of
    holds each polygon's part) that face_pred(centre, normal) selects; none without face_pred."""
    if face_pred is None:
        return [False] * len(me.polygons)
    return [part_of[p.index] == face_part and face_pred(Vector(p.center), Vector(p.normal)) for p in me.polygons]


def unwrap_key(obj_name, face_part=None, face_pred=None):
    """A digest of everything a pack of the object's current UVs reads, so two unwraps with the same key
    pack alike: the sha256 (hex) of the UVMap's UVs as float32 pairs in loop order, each loop's vertex,
    each polygon's loop count, the vertex coordinates as float32 (the face island's target area is read
    from polygon areas), the face island's polygons (face_part, face_pred, as for unwrap_color_atlas) and
    the Blender version and build, whose packer packs them. It holds no setting of the pack itself: the
    pack cache keys on those beside it (pack_key)."""
    ob = bpy.data.objects[obj_name]
    me = ob.data
    parts = list(ob['parts'])
    pa = me.attributes['part'].data
    part_of = [parts[pa[p.vertices[0]].value] for p in me.polygons]
    loops = np.empty(len(me.loops), np.int32)
    me.loops.foreach_get('vertex_index', loops)
    totals = np.empty(len(me.polygons), np.int32)
    me.polygons.foreach_get('loop_total', totals)
    co = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get('co', co)
    face = np.array(_is_face(me, part_of, face_part, face_pred), np.bool_)
    build = bpy.app.build_hash
    h = hashlib.sha256()
    for part in (uv_bytes(obj_name), loops.tobytes(), totals.tobytes(), co.tobytes(), face.tobytes(),
                 bpy.app.version_string.encode('utf-8'), build if isinstance(build, bytes) else str(build).encode()):
        h.update(len(part).to_bytes(8, 'little'))
        h.update(part)
    return h.hexdigest()


def uv_bytes(obj_name):
    """The object's UVMap as bytes: its UVs as float32 (u, v) pairs in loop order, as Blender stores them."""
    me = bpy.data.objects[obj_name].data
    uv = np.empty(len(me.loops) * 2, np.float32)
    me.uv_layers[UV_LAYER].uv.foreach_get('vector', uv)
    return uv.tobytes()


def set_uv_bytes(obj_name, data):
    """Write uv_bytes' bytes back into the object's UVMap, which holds them then byte for byte. Raises
    ValueError when they do not hold two float32 values per loop of the mesh."""
    me = bpy.data.objects[obj_name].data
    uv = np.frombuffer(data, np.float32).copy()
    if uv.size != len(me.loops) * 2:
        raise ValueError('set_uv_bytes: %d values for %d loops' % (uv.size, len(me.loops)))
    me.uv_layers[UV_LAYER].uv.foreach_set('vector', uv)
    me.update()


def unwrap_color_atlas(obj_name, sheet_of, atlas, face_part=None, face_pred=None, boost_parts=None, strips=None,
                       angle_limit=66, default_group='Body', margin=0.006, margin_method='FRACTION'):
    """UVs for the colour atlas, not packed yet. atlas: (size in pixels, {group: relative texel density}).
    face_pred(centre, normal) picks the faces of `face_part` that form the face island,
    bounded by seams and scaled later to its own texel budget (pack_step): one conformal piece per
    region of the selection, so regions that share no edge (each side of a long head) become pieces scaled
    alike; without face_pred there is no face island. strips: {part: loft sides}, each unrolled into one
    straight strip (a banded tail). The strips and the face island take the density of `default_group`, an
    atlas group. Every other group is smart-projected on its own and scaled to its density; a group of
    `own` parts (sheet_of gives it, _own_sheet) is smart-projected alone into the whole UV square with
    `margin` and `margin_method` (the pack's) and not scaled (_unwrap_own). boost_parts:
    {part: linear UV scale} on top of the part's group density, so a part boosted by k gets k squared
    times the texels; the face island takes none. The pack shares one square, so a boost takes texels from
    every other island: the more of the atlas the boosted parts take, the lower every other island's texels
    per metre after the pack (bake's report gives each group's). A strip part must be one loft of its
    sides with its cap apex last (_strip_check): anything else
    raises ValueError before the UVs change. Returns {'face_tris': the face island's triangles,
    'face_angle': how far the face island's up direction (world +Z) turns off the texel columns, in
    degrees from -45 to 45 (packing turns islands by quarter turns only, so it stays), the largest turn of
    its pieces when it has several, None without a face island}."""
    boost_parts = boost_parts or {}; strips = strips or {}
    ob, me, ctx, parts, part_of, is_face, ug = _atlas_setup(obj_name, sheet_of, face_part, face_pred, strips)
    _check_strips(me, parts, strips)
    while me.uv_layers:
        me.uv_layers.remove(me.uv_layers[0])
    me.uv_layers.new(name=UV_LAYER)
    bpy.context.scene.tool_settings.use_uv_select_sync = False
    bm = bmesh.new(); bm.from_mesh(me)
    for e in bm.edges:
        fs = e.link_faces
        e.seam = len(fs) == 2 and is_face[fs[0].index] != is_face[fs[1].index]
    bm.to_mesh(me); bm.free()
    for g in atlas[1]:
        _isolate(me, ug, g)
        _uv_ops(ctx, lambda: bpy.ops.uv.smart_project(angle_limit=math.radians(angle_limit), island_margin=0.0,
                                                      area_weight=0.0, correct_aspect=True, scale_to_bounds=False))
    if any(is_face):
        _isolate(me, ug, 'Face')
        _uv_ops(ctx, lambda: bpy.ops.uv.unwrap(method='CONFORMAL', margin=0.0))
    _unwrap_own(me, ctx, ug, angle_limit, margin, margin_method)
    _finish_unwrap(me, ug, is_face, parts, atlas, boost_parts, strips, default_group)
    return {'face_tris': sum(is_face), 'face_angle': _face_angle(me, is_face)}


def _finish_unwrap(me, ug, is_face, parts, atlas, boost_parts, strips, default_group='Body'):
    """Strips unrolled, every face scaled to its group's density (default_group's for the face island
    and the strips) times its part's boost (none on the face island), the `own` parts' faces left as they are,
    selection and hiding cleared."""
    bm = bmesh.new(); bm.from_mesh(me)
    uvl = bm.loops.layers.uv[UV_LAYER]; pl = bm.verts.layers.int['part']
    for part, sides in strips.items():
        if part in parts:
            _strip_uv(bm, uvl, pl, parts.index(part), sides)
    bm.to_mesh(me); bm.free()
    areas = _group_areas(me, ug)
    bm = bmesh.new(); bm.from_mesh(me)
    uvl = bm.loops.layers.uv[UV_LAYER]; pl = bm.verts.layers.int['part']
    bm.faces.ensure_lookup_table()
    for f in bm.faces:
        g = ug[f.index]
        if _own(g):
            continue
        ua, sa = areas[g]
        dens = atlas[1].get(g, atlas[1][default_group])
        k = dens * math.sqrt(sa / ua) * (1.0 if is_face[f.index] else boost_parts.get(parts[f.verts[0][pl]], 1.0))
        for l in f.loops:
            l[uvl].uv *= k
    bm.to_mesh(me); bm.free()
    for coll in (me.polygons, me.edges, me.vertices):
        for e in coll:
            e.hide = False; e.select = False


def _regions(bm, key, cut):
    """Face regions joined across edges that are not cut and link faces of one key."""
    par = list(range(len(bm.faces)))

    def find(a):
        while par[a] != a:
            par[a] = par[par[a]]; a = par[a]
        return a
    for e in bm.edges:
        fs = e.link_faces
        if len(fs) == 2 and not cut[e.index] and key[fs[0].index] == key[fs[1].index]:
            par[find(fs[0].index)] = find(fs[1].index)
    out = {}
    for f in bm.faces:
        out.setdefault(find(f.index), []).append(f)
    return list(out.values())


def _topology(fs):
    """(Euler characteristic, boundary loops as vertex sets) of a face region."""
    fset = set(fs)
    vs = {v for f in fs for v in f.verts}
    es = {e for f in fs for e in f.edges}
    bnd = [e for e in es if sum(g in fset for g in e.link_faces) == 1]
    by_vert = {}
    for e in bnd:
        for v in e.verts:
            by_vert.setdefault(v, []).append(e)
    seen, loops = set(), []
    for e in bnd:
        if e in seen:
            continue
        loop, stack = set(), [e]
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x); loop.update(x.verts)
            for v in x.verts:
                stack.extend(by_vert[v])
        loops.append(loop)
    return len(vs) - len(es) + len(fs), loops


def _cut_path(fs, sources, targets, side, blocked, k=6.0):
    """Cheapest edge path inside a region from a source vertex to a target vertex, through no
    blocked vertex. Edge cost is its length, raised up to (1 + k) times as the edge's faces turn
    away from `side`, so the cut runs on that side. With no targets: (None, {vertex: distance})."""
    import heapq
    fset = set(fs)
    dist = {v: 0.0 for v in sources}
    prev = {}
    heap = [(0.0, v.index, v) for v in sources]
    heapq.heapify(heap)
    while heap:
        d, _, v = heapq.heappop(heap)
        if d > dist[v]:
            continue
        if v in targets:
            path = []
            while v in prev:
                e, v = prev[v]
                path.append(e)
            return d, path
        for e in v.link_edges:
            lf = [f for f in e.link_faces if f in fset]
            if len(lf) != 2:
                continue
            w = e.other_vert(v)
            if w in blocked and w not in targets:
                continue
            cost = e.calc_length()
            if side is not None:
                n = (lf[0].normal + lf[1].normal).normalized()
                cost *= 1.0 + k * (1.0 - n.dot(side)) / 2.0
            nd = d + cost
            if nd < dist.get(w, float('inf')):
                dist[w] = nd; prev[w] = (e, v)
                heapq.heappush(heap, (nd, w.index, w))
    return None if targets else (None, dist)


def _open_region(fs, sides, cut):
    """Cut a region into one disk: join two boundary loops per cut (`sides[i]` steers the i-th
    cut, the last one repeats), or for a closed region cut once between its two extremes along
    the first side. Returns False when the region stays no disk (a handle), for a fallback."""
    chi, loops = _topology(fs)
    side = lambda i: Vector(sides[min(i, len(sides) - 1)]).normalized() if sides else None
    if not loops:
        axis = side(0)
        vs = list({v for f in fs for v in f.verts})
        if axis is None:
            c = sum((v.co for v in vs), Vector()) / len(vs)
            far = max(vs, key=lambda v: (v.co - c).length)
            axis = (far.co - c).normalized()
        a = min(vs, key=lambda v: v.co.dot(axis)); b = max(vs, key=lambda v: v.co.dot(axis))
        hit = _cut_path(fs, {a}, {b}, None, set())
        if not hit:
            return False
        for e in hit[1]:
            cut[e.index] = True
        chi, loops = chi - 1, [{a, b}]
    i = 0
    while len(loops) > 1:
        blocked = set().union(*loops)
        best = None
        for j, src in enumerate(loops):
            hit = _cut_path(fs, src, blocked - src, side(i), blocked)
            if hit and (best is None or hit[0] < best[0]):
                best = hit + (j,)
        if not best:
            return False
        for e in best[1]:
            cut[e.index] = True
        end = best[1][0].verts
        j = best[2]
        k = next(n for n, l in enumerate(loops) if n != j and (end[0] in l or end[1] in l))
        loops[j] = loops[j] | loops[k] | {v for e in best[1] for v in e.verts}
        del loops[k]
        chi += 1; i += 1
    return chi == 1


def _folded_regions(me, regions, flip=0.01, stretch=3.0, stretched=0.2):
    """Regions whose unwrap folded: more than `flip` of the area turned over, or more than
    `stretched` of it scaled over `stretch` times off the region's mean density. A face of no area (a
    degenerate triangle, lpk.core.builder.DEGENERATE_M2) weighs nothing in either share and is never
    measured for stretch, which it has none of; a region whose faces have no area in total, or no UV
    area, counts as folded."""
    uv = me.uv_layers[UV_LAYER].data
    polys = me.polygons
    bad = []
    for fs in regions:
        rows = []
        for f in fs:
            q = [Vector(uv[li].uv) for li in polys[f.index].loop_indices]
            s = sum((q[i] - q[0]).cross(q[i + 1] - q[0]) for i in range(1, len(q) - 1)) / 2
            rows.append((s, f.calc_area()))
        sa = sum(a for _, a in rows); ua = sum(abs(s) for s, _ in rows)
        if sa < 1e-12 or ua < 1e-12:
            bad.append(fs); continue
        pos = sum(a for s, a in rows if s > 0)
        off = sum(a for s, a in rows if a > 0 and not 1 / stretch < (abs(s) / ua) / (a / sa) < stretch)
        if min(pos, sa - pos) / sa > flip or off / sa > stretched:
            bad.append(fs)
    return bad


def _projection_axis(fs, min_cos):
    """The region's area-weighted mean normal when every face turns less than acos(min_cos) from
    it (a flat projection along it then neither folds nor squeezes a face past that), else None."""
    n = sum((f.normal * f.calc_area() for f in fs), Vector())
    if n.length < 1e-12:
        return None
    n.normalize()
    return n if all(f.normal.dot(n) >= min_cos for f in fs) else None


def _split_projectable(fs, cut, min_cos, depth=2):
    """Split a region that folds when flattened (an ear, a toe) into the two sides its normals
    face, across the direction they spread most along; returns [(face indices, axis)] for every
    connected piece when each one projects flat (_projection_axis), a piece that does not being
    split again up to `depth` times; the splits are marked as seams, else None and nothing changes."""
    m = [[sum(f.normal[i] * f.normal[j] * f.calc_area() for f in fs) for j in range(3)] for i in range(3)]
    axis = Vector((1, 0.3, 0.1)).normalized()
    for _ in range(40):
        nxt = Vector([sum(m[i][j] * axis[j] for j in range(3)) for i in range(3)])
        if nxt.length < 1e-12:
            return None
        axis = nxt.normalized()
    side = {f: f.normal.dot(axis) >= 0 for f in fs}
    split = [e for f in fs for e in f.edges
             if len(e.link_faces) == 2 and all(g in side for g in e.link_faces)
             and side[e.link_faces[0]] != side[e.link_faces[1]]]
    par = {f: f for f in fs}

    def find(a):
        while par[a] is not a:
            par[a] = par[par[a]]; a = par[a]
        return a
    for f in fs:
        for e in f.edges:
            lf = e.link_faces
            if len(lf) == 2 and all(g in side for g in lf) and side[lf[0]] == side[lf[1]] and not cut[e.index]:
                par[find(lf[0])] = find(lf[1])
    pieces = {}
    for f in fs:
        pieces.setdefault(find(f), []).append(f)
    out = []
    trial = list(cut)
    for e in split:
        trial[e.index] = True
    for piece in pieces.values():
        a = _projection_axis(piece, min_cos)
        if a is not None:
            out.append(([f.index for f in piece], a))
            continue
        sub = _split_projectable(piece, trial, min_cos, depth - 1) if depth > 1 else None
        if sub is None:
            return None
        out.extend(sub)
    cut[:] = trial
    return out


def _cut_to_far(fs, sides, cut):
    """Cut from the region's border (seams and earlier cuts included) to the vertex farthest from
    it along the surface, steered to the first of `sides`."""
    _, loops = _topology(fs)
    fset = set(fs)
    border = set().union(*loops) if loops else set()
    border |= {v for f in fs for e in f.edges if cut[e.index] for v in e.verts}
    if not border:
        return False
    side = Vector(sides[0]).normalized() if sides else None
    hit = _cut_path(fs, border, set(), side, set())       # no target: explores the whole region
    far = max(hit[1], key=hit[1].get) if hit else None
    if far is None or far in border:
        return False
    path = _cut_path(fs, border, {far}, side, border - {far})
    if not path or not path[1]:
        return False
    for e in path[1]:
        cut[e.index] = True
    return True


def unwrap_seamed_atlas(obj_name, sheet_of, atlas, face_part=None, face_pred=None, cut_sides=None, panels=None,
                        hard=None, boost_parts=None, strips=None, method='ANGLE_BASED', angle_limit=66, min_region=3,
                        retries=2, default_group='Body', margin=0.006, margin_method='FRACTION'):
    """UVs for the colour atlas like unwrap_color_atlas (the face island, the strips and
    `default_group` as there), but in islands cut along seams instead of smart-projected ones. Cutting
    along the seams below can leave fewer and larger islands, which spend less of the atlas on margins
    and leave more texels per metre to the surface; how many fewer depends on the topology and the seams
    (the report below, and bake's island count and texels per metre, read it).

    Seams run along part, group and flat-colour borders: an island border bakes as a clean polygon
    edge, a colour border inside an island as texel stairs wherever it runs diagonally (an ear's
    rim); the face island stays out of the cuts, one conformal piece per region of its selection, for
    its texel budget. Regions under `min_region` faces (the odd faces of welded joins) join a neighbour
    of their group. `panels` {part: [direction, ...]} splits a part like a garment pattern, each face
    going to the direction its normal is nearest to (a torso's front, back, sides, top and bottom);
    `hard` {part: degrees} adds seams on sharper edges.

    A region every face of which turns less than `angle_limit` from the region's mean normal is
    projected flat along it, up the body along V: a projection keeps lines straight and decals
    unturned, which a flattening of a curved panel does not. Every other region is cut into a
    disk, `cut_sides` {part: [direction, ...]} steering the cuts to that side (the arm's
    underside, the leg's inner side), flattened (`method`) and turned so its mesh grid follows
    the texel grid. A region that flattens folded (an ear, a toe, a mitten open only at the
    wrist) is split by its normals into pieces that project, else cut from its border to its
    farthest vertex, up to `retries` times; what still folds is smart-projected.

    Strip parts are checked as in unwrap_color_atlas. The `own` groups stay out of the cuts and are
    smart-projected alone into the whole UV square with `margin` and `margin_method`, as there.

    Returns {'regions': the regions outside the face, the strips and the `own` groups, 'projected': those
    projected flat, 'cut_open': those that were not a disk and were cut open, 'split': {part: folded regions
    split into projecting pieces}, 'extra_cuts': {part: cuts added from a border to the farthest
    vertex}, 'fallback': [the part of each region left to smart project], 'fallback_tris': {part:
    triangles left to smart project}, 'face_tris': the face island's triangles, 'face_angle': as in
    unwrap_color_atlas}."""
    boost_parts = boost_parts or {}; strips = strips or {}; hard = hard or {}; cut_sides = cut_sides or {}
    ob, me, ctx, parts, part_of, is_face, ug = _atlas_setup(obj_name, sheet_of, face_part, face_pred, strips)
    _check_strips(me, parts, strips)
    while me.uv_layers:
        me.uv_layers.remove(me.uv_layers[0])
    me.uv_layers.new(name=UV_LAYER)
    bpy.context.scene.tool_settings.use_uv_select_sync = False
    bm = bmesh.new(); bm.from_mesh(me)
    bm.faces.ensure_lookup_table(); bm.edges.ensure_lookup_table()
    pal = me.attributes['pal'].data
    key = [(part_of[i], ug[i], None if is_face[i] else pal[i].value) for i in range(len(ug))]
    for part, dirs in (panels or {}).items():
        dirs = [Vector(d).normalized() for d in dirs]
        for f in bm.faces:
            if part_of[f.index] == part:
                key[f.index] += (max(range(len(dirs)), key=lambda i: f.normal.dot(dirs[i])),)
    none = [False] * len(bm.edges)
    for fs in sorted(_regions(bm, key, none), key=len):
        if len(fs) >= min_region:
            continue
        shared = {}
        for f in fs:
            for e in f.edges:
                for g in e.link_faces:
                    if g not in fs and ug[g.index] == ug[f.index]:
                        shared[key[g.index]] = shared.get(key[g.index], 0) + 1
        if shared:
            k = max(shared, key=shared.get)
            for f in fs:
                key[f.index] = k
    cut = [False] * len(bm.edges)
    for e in bm.edges:
        fs = e.link_faces
        if len(fs) != 2:
            continue
        a, b = fs
        cut[e.index] = key[a.index] != key[b.index]
        lim = hard.get(key[a.index][0])
        if lim is not None and key[a.index] == key[b.index] and a.normal.angle(b.normal, 0) > math.radians(lim):
            cut[e.index] = True
    regions = _regions(bm, key, cut)
    owner = {f: n for n, fs in enumerate(regions) for f in fs}
    for e in bm.edges:                      # a hard seam that splits nothing is no seam
        fs = e.link_faces
        if cut[e.index] and len(fs) == 2 and owner[fs[0]] == owner[fs[1]]:
            cut[e.index] = False
    min_cos = math.cos(math.radians(angle_limit))
    fallback = set()
    report = {'regions': 0, 'projected': 0, 'cut_open': 0, 'split': {}, 'extra_cuts': {}, 'fallback': []}
    projected = []
    special = [g in ('Face', 'Strip') or _own(g) for g in ug]
    for fs in regions:
        if special[fs[0].index]:
            continue
        report['regions'] += 1
        axis = _projection_axis(fs, min_cos)
        if axis:
            projected.append(([f.index for f in fs], axis)); report['projected'] += 1
            continue
        chi, loops = _topology(fs)
        if chi == 1 and len(loops) == 1:
            continue
        report['cut_open'] += 1
        if not _open_region(fs, cut_sides.get(key[fs[0].index][0]), cut):
            fallback.update(f.index for f in fs)
            report['fallback'].append(key[fs[0].index][0])
    flat = {i for idx, _ in projected for i in idx}
    main = {i for i in range(len(ug)) if not special[i] and i not in fallback and i not in flat}
    for attempt in range(retries + 1):
        for e in bm.edges:
            e.seam = cut[e.index]
        bm.to_mesh(me)
        _isolate(me, ['Main' if i in main else 'Other' for i in range(len(ug))], 'Main')
        _uv_ops(ctx, lambda: bpy.ops.uv.unwrap(method=method, margin=0.0, correct_aspect=True))
        bad = _folded_regions(me, [fs for fs in _regions(bm, key, cut) if fs[0].index in main])
        if not bad:
            break
        for fs in bad:
            p = key[fs[0].index][0]
            pieces = _split_projectable(fs, cut, min_cos)
            if pieces:
                for idx, axis in pieces:
                    projected.append((idx, axis)); flat.update(idx); main.difference_update(idx)
                report['split'][p] = report['split'].get(p, 0) + 1
                continue
            if attempt == retries or not _cut_to_far(fs, cut_sides.get(p), cut):
                fallback.update(f.index for f in fs); main.difference_update(f.index for f in fs)
                report['fallback'].append(p)
            else:
                report['extra_cuts'][p] = report['extra_cuts'].get(p, 0) + 1
    bm.free()
    if fallback:
        _isolate(me, ['Fallback' if i in fallback else 'Other' for i in range(len(ug))], 'Fallback')
        _uv_ops(ctx, lambda: bpy.ops.uv.smart_project(angle_limit=math.radians(angle_limit), island_margin=0.0,
                                                      area_weight=0.0, correct_aspect=True, scale_to_bounds=False))
    if any(is_face):
        _isolate(me, ug, 'Face')
        _uv_ops(ctx, lambda: bpy.ops.uv.unwrap(method='CONFORMAL', margin=0.0))
    if projected:
        bm = bmesh.new(); bm.from_mesh(me); bm.faces.ensure_lookup_table()
        uvl = bm.loops.layers.uv[UV_LAYER]
        for idx, axis in projected:
            up = Vector((0, 0, 1)) if abs(axis.z) < 0.9 else Vector((0, 1, 0))
            up = (up - axis * up.dot(axis)).normalized()
            right = up.cross(axis)
            for i in idx:
                for l in bm.faces[i].loops:
                    l[uvl].uv = (l.vert.co.dot(right), l.vert.co.dot(up))
        bm.to_mesh(me); bm.free()
    _true_scale_islands(me)
    _orient_islands(me, fallback | flat | {i for i in range(len(ug)) if special[i]})
    _unwrap_own(me, ctx, ug, angle_limit, margin, margin_method)
    _finish_unwrap(me, ug, is_face, parts, atlas, boost_parts, strips, default_group)
    left = {}
    for i in sorted(fallback):
        left[part_of[i]] = left.get(part_of[i], 0) + 1
    report['fallback_tris'] = left
    report['face_tris'] = sum(is_face)
    report['face_angle'] = _face_angle(me, is_face)
    return report


def _uv_islands(bm, uvl):
    """The bmesh's faces grouped into UV islands (lpk.stages.zones.uv_islands on the bmesh's corners and
    the UV layer uvl): [[BMFace, ...] per island], in the order of their first face, each in face order."""
    bm.verts.index_update()
    bm.faces.index_update()
    starts, totals, verts, uv = [], [], [], []
    for f in bm.faces:
        starts.append(len(verts))
        totals.append(len(f.loops))
        for l in f.loops:
            verts.append(l.vert.index)
            uv.append(tuple(l[uvl].uv))
    ids = zones.uv_islands(starts, totals, verts, np.asarray(uv, np.float64).reshape(-1, 2))
    out = {}
    for f, i in zip(bm.faces, ids.tolist()):
        out.setdefault(i, []).append(f)
    return list(out.values())


def _orient_islands(me, skip):
    """Turn every island so its mesh grid (a loft's rings and columns) runs along the texel rows
    and columns: an unwrapped island lies at any angle, and lines that follow the grid on the body
    (piping, bands, fur edges) then cross the texels diagonally and bake as stairs. The angle is
    the circular mean of the island's edge directions modulo 90 degrees; each triangle's longest
    edge is left out as the diagonal of a triangulated quad. Packing turns islands by 90 degrees
    only, which keeps them aligned. Faces in `skip` keep their UVs."""
    bm = bmesh.new(); bm.from_mesh(me)
    uvl = bm.loops.layers.uv[UV_LAYER]
    diagonal = {max(f.edges, key=lambda e: e.calc_length()) for f in bm.faces}
    for fs in _uv_islands(bm, uvl):
        if fs[0].index in skip:
            continue
        sx = sy = 0.0
        for f in fs:
            for l in f.loops:
                if l.edge in diagonal:
                    continue
                d = l.link_loop_next[uvl].uv - l[uvl].uv
                w = d.length_squared
                if w < 1e-16:
                    continue
                phi = math.atan2(d.y, d.x) * 4
                sx += w * math.cos(phi); sy += w * math.sin(phi)
        if sx * sx + sy * sy < 1e-24:
            continue
        ang = -math.atan2(sy, sx) / 4
        ca, sa = math.cos(ang), math.sin(ang)
        uc = sum((l[uvl].uv for f in fs for l in f.loops), Vector((0, 0))) / sum(len(f.loops) for f in fs)
        for f in fs:
            for l in f.loops:
                d = l[uvl].uv - uc
                l[uvl].uv = uc + Vector((d.x * ca - d.y * sa, d.x * sa + d.y * ca))
    bm.to_mesh(me); bm.free()


def _true_scale_islands(me):
    """Every island scaled to its surface area, so one group density holds across islands
    (Blender's unwrap packs islands at its own scale)."""
    bm = bmesh.new(); bm.from_mesh(me)
    uvl = bm.loops.layers.uv[UV_LAYER]
    for fs in _uv_islands(bm, uvl):
        ua = 0.0
        for f in fs:
            q = [l[uvl].uv for l in f.loops]
            ua += sum(abs((q[i] - q[0]).cross(q[i + 1] - q[0])) / 2 for i in range(1, len(q) - 1))
        if ua < 1e-12:
            continue
        k = math.sqrt(sum(f.calc_area() for f in fs) / ua)
        for f in fs:
            for l in f.loops:
                l[uvl].uv *= k
    bm.to_mesh(me); bm.free()


def _face_area(me, is_face):
    uv = me.uv_layers[UV_LAYER].data
    a = 0.0
    for p in me.polygons:
        if is_face[p.index]:
            q = [Vector(uv[li].uv) for li in p.loop_indices]
            for i in range(1, len(q) - 1):
                a += abs((q[i] - q[0]).cross(q[i + 1] - q[0])) / 2
    return a


def _face_span(me, is_face):
    """The longest side of the UV bounds of the face island's largest piece (_uv_islands), a share of
    the atlas's side. A face selection that unwraps into several pieces is packed apart, every piece
    scaled alike: the bounds of all of them would count the gaps between them, and the largest piece's
    side is the one a pack moves most."""
    bm = bmesh.new(); bm.from_mesh(me)
    uvl = bm.loops.layers.uv[UV_LAYER]
    span = 0.0
    for fs in _uv_islands(bm, uvl):
        uv = [l[uvl].uv for f in fs if is_face[f.index] for l in f.loops]
        if uv:
            us, vs = [p[0] for p in uv], [p[1] for p in uv]
            span = max(span, max(us) - min(us), max(vs) - min(vs))
    bm.free()
    return span


def _turn(tris):
    """How far a surface's up direction (+Z) turns off the UV's v axis, from triangles [(three (u, v),
    three z, area)]: each triangle's direction of rising z in its UVs, as a unit vector weighted by its
    area, summed; the angle of the sum from +v, folded to the nearest quarter turn. Returns degrees from
    -45 to 45, None when no triangle has a direction (flat in z or degenerate in UV)."""
    sx = sy = 0.0
    for (p0, p1, p2), (z0, z1, z2), area in tris:
        ax, ay = p1[0] - p0[0], p1[1] - p0[1]
        bx, by = p2[0] - p0[0], p2[1] - p0[1]
        det = ax * by - ay * bx
        if abs(det) < 1e-18:
            continue
        # The UV direction g with g . (p1 - p0) = z1 - z0 and g . (p2 - p0) = z2 - z0.
        gx = ((z1 - z0) * by - (z2 - z0) * ay) / det
        gy = (ax * (z2 - z0) - bx * (z1 - z0)) / det
        g = math.hypot(gx, gy)
        if g < 1e-12:
            continue
        sx += area * gx / g
        sy += area * gy / g
    if math.hypot(sx, sy) < 1e-12:
        return None
    return round((math.degrees(math.atan2(sx, sy)) + 45.0) % 90.0 - 45.0, 1)


def _face_angle(me, is_face):
    """The turn of the face island: _turn of each of its pieces (_uv_islands; the mesh is triangulated),
    their triangles in polygon order, and of those the largest (_largest_turn); None without a face
    island. A face selection of regions that share no edge unwraps into one conformal piece per region,
    each lying at its own angle: a mean over all of them reads two turned pieces as their average, or as
    no turn when they cancel."""
    if not any(is_face):
        return None
    bm = bmesh.new(); bm.from_mesh(me)
    piece_of = {}
    for n, fs in enumerate(_uv_islands(bm, bm.loops.layers.uv[UV_LAYER])):
        for f in fs:
            if is_face[f.index]:
                piece_of[f.index] = n
    bm.free()
    uv = me.uv_layers[UV_LAYER].data
    vs, loops = me.vertices, me.loops
    pieces = {}
    for p in me.polygons:
        if p.index in piece_of:
            pieces.setdefault(piece_of[p.index], []).append(
                ([tuple(uv[i].uv) for i in p.loop_indices[:3]], [vs[loops[i].vertex_index].co.z
                                                                 for i in p.loop_indices[:3]], p.area))
    return _largest_turn([_turn(tris) for tris in pieces.values()])


def _largest_turn(turns):
    """The turn farthest from zero among `turns` (degrees, None for a piece without a direction), the first
    of equal ones; None when no piece has a direction."""
    known = [t for t in turns if t is not None]
    return max(known, key=abs) if known else None


def face_area_for(surface_m2, texels_per_m, size):
    """The packed UV area (a share of the atlas) that gives an island of `surface_m2` square metres
    `texels_per_m` texels per metre in a `size` pixel square atlas."""
    return surface_m2 * (texels_per_m / size) ** 2


# A pack settles the face island when its longest side moves by less than this many texels: another pack
# would not change the texels it covers.
SETTLED_TEXELS = 1.0


def pack_settled(report):
    """Whether a pack_step report settles the chain of packs: its face_side_change is under SETTLED_TEXELS,
    or there is no face island (one pack is final)."""
    change = report.get('face_side_change')
    return change is None or change < SETTLED_TEXELS


def pack_step(obj_name, sheet_of, atlas, face_part=None, face_pred=None, face_area=None, face_texels=None, strips=None,
              own=None, rescale=True, margin=0.006, shape_method='CONCAVE', margin_method='FRACTION', cache=None):
    """One pack of the whole atlas after scaling the face island toward `face_area` (its UV area after
    packing, a share of the atlas; 0.053 is a 118 px square of a 512 atlas), or toward the area that gives it
    `face_texels` texels per metre in the atlas (face_area_for over the island's surface) when face_area is
    None. A pinned island does not keep the others off it (Blender packs over it), so the face is scaled and
    the atlas packed normally, again until the face island's size settles: call it repeatedly, the first
    time after the unwrap with rescale=False (that pack reads the island's area as the unwrap leaves it).
    Without face_pred there is no face island: nothing is scaled and one pack is final. Islands turn by
    PACK_ROTATE. The faces of the `own` parts ({part: material name}) stay out of the pack, as the unwrap laid
    them out in their own square.

    atlas: (size in pixels, {group: density}); sheet_of, face_part, face_pred, strips and own as given to
    unwrap. Raises ValueError for a face island without face_area or face_texels, and for an unknown
    shape_method or margin_method.

    A face_area is a share of the atlas whatever the face's size, so the texels per metre it gives fall
    as the face's surface grows (size * sqrt(face_area / surface), face_area_for solved for the density);
    face_texels states the density instead. margin: the gap round every island, a share of the atlas.
    Every island pays it along its whole border, so the gaps' share of the atlas grows with the islands'
    count and border length: many small islands (a smart-projected clothed body) can spend a large share of
    the atlas on gaps, which a smaller margin or fewer, larger islands (unwrap_seamed_atlas) give back to
    the islands. bake reports that share ('margin_share') and the coverage.

    shape_method, margin_method: the packer's island shape (PACK_SHAPES) and margin method (PACK_MARGINS).
    The shape is what the packer fits together: CONCAVE (the default) the islands' own outlines, CONVEX
    their convex hulls, AABB their bounding boxes; a looser shape leaves more of the atlas between the
    islands. The default margin method, FRACTION, keeps the gap a fixed number of texels: margin x size from
    the atlas's edge and twice that between islands, whatever the islands' scale before the pack. It is the
    slower method: the gap it holds depends on the scale the pack arrives at. ADD takes the margin in the
    islands' UV units before the pack and SCALED multiplies it by their mean scale; both pack faster, at the
    price of a gap that follows the islands' scale before the pack and so is no fixed number of texels.
    After a chain of packs, whose later packs start from packed UVs, ADD's gap comes near FRACTION's; after a
    single pack from the unwrap (the only pack of a model without a face island) it can fall under twice
    the 2 px margin bake extends every island by, and the extended colours of neighbouring islands then
    overlap. How much faster another method packs, how many packs the face island takes to settle and how
    much of the atlas it covers depend on the topology, the islands, the settings and the Blender build.

    cache: the path of the pack cache (a JSON file, out/<NAME>.pack.json), or None for none. A pack is
    decided by the UVs it starts from and its settings, so the cache keys each pack on them (pack_key over
    unwrap_key) and, on a hit, writes the UVs the cached pack left (set_uv_bytes) instead of packing; a pack
    it lacks is run and added (kept_entries). Deleting the file changes only the time the packs take.

    Returns {'face_area_before': the face island's UV area as this call found it, before any rescale (after
    a pack, that pack's face_area), 'face_area': its UV area after the pack, 'face_span': the longest side of
    the UV bounds of its largest piece (one piece unless face_pred selects regions that do not share an edge)
    in texels, 'face_side_change': how many texels that side moved between the two areas
    (face_span * |1 - sqrt(face_area_before / face_area)|; under one, another pack moves it by less than a
    texel), all None without a face island; 'cached': whether the UVs came from the cache}."""
    if shape_method not in PACK_SHAPES:
        raise ValueError('pack_step(shape_method=%r): use one of %s' % (shape_method, ', '.join(PACK_SHAPES)))
    if margin_method not in PACK_MARGINS:
        raise ValueError('pack_step(margin_method=%r): use one of %s' % (margin_method, ', '.join(PACK_MARGINS)))
    own = own or {}
    sheet = _own_sheet(sheet_of, own)
    entries = key = None
    if cache is not None:
        key = pack_key(unwrap_key(obj_name, face_part, face_pred),
                       {'face_part': face_part, 'face_area': face_area, 'face_texels': face_texels, 'size': atlas[0],
                        'strips': dict(strips or {}), 'own': dict(own), 'rescale': bool(rescale), 'margin': margin,
                        'shape_method': shape_method, 'margin_method': margin_method, 'rotate': PACK_ROTATE})
        entries = read_pack_cache(cache)
        hit = cached_pack(entries, key)
        if hit is not None:
            set_uv_bytes(obj_name, hit['uv'])
            return dict(hit['report'], cached=True)
    report = _pack(obj_name, sheet, face_part, face_pred, face_area, face_texels, strips or {}, atlas[0], rescale,
                   margin, shape_method, margin_method)
    if cache is not None:
        write_pack_cache(cache, kept_entries(entries, key, report, uv_bytes(obj_name)))
    return dict(report, cached=False)


def _pack(obj_name, sheet_of, face_part, face_pred, face_area, face_texels, strips, size, rescale, margin,
          shape_method, margin_method):
    """pack_step's pack itself, without the cache; returns its report but 'cached'."""
    ob, me, ctx, parts, part_of, is_face, ug = _atlas_setup(obj_name, sheet_of, face_part, face_pred, strips)
    face = any(is_face)
    if face and face_area is None:
        if face_texels is None:
            raise ValueError('pack_step: a face island needs face_area or face_texels')
        face_area = face_area_for(sum(p.area for p in me.polygons if is_face[p.index]), face_texels, size)
    before = _face_area(me, is_face) if face else None
    if rescale and face:
        uv = me.uv_layers[UV_LAYER].data
        idx = [li for p in me.polygons if is_face[p.index] for li in p.loop_indices]
        c = sum((Vector(uv[i].uv) for i in idx), Vector((0, 0))) / len(idx)
        k = math.sqrt(face_area / before)
        for i in idx:
            uv[i].uv = c + (Vector(uv[i].uv) - c) * k
    for p in me.polygons:
        p.hide = _own(ug[p.index]); p.select = not p.hide
    _uv_ops(ctx, lambda: (bpy.ops.uv.select_all(action='SELECT'),
                          bpy.ops.uv.pack_islands(udim_source='CLOSEST_UDIM', rotate=True, rotate_method=PACK_ROTATE,
                                                  scale=True, margin_method=margin_method,
                                                  margin=margin, shape_method=shape_method)))
    for coll in (me.polygons, me.edges, me.vertices):
        for e in coll:
            e.hide = False; e.select = False
    if not face:
        return {'face_area_before': None, 'face_area': None, 'face_span': None, 'face_side_change': None}
    after = _face_area(me, is_face)
    span = _face_span(me, is_face) * size
    change = span * abs(1.0 - math.sqrt(before / after)) if before > 0 and after > 0 else None
    return {'face_area_before': round(before, 4), 'face_area': round(after, 4), 'face_span': round(span, 1),
            'face_side_change': None if change is None else round(change, 2)}


def pack_key(unwrap, settings):
    """The key of one pack in the pack cache: the SHA-256 hex of the JSON (sorted keys) of {'unwrap': the
    UVs and mesh the pack starts from (unwrap_key), 'settings': the pack's settings (a dict of JSON values),
    'code': the SHA-256 of this module's source, whose pack kernel packs them}."""
    with open(__file__, 'rb') as f:
        code = hashlib.sha256(f.read()).hexdigest()
    text = json.dumps({'unwrap': unwrap, 'settings': settings, 'code': code}, sort_keys=True)
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def read_pack_cache(path):
    """The pack cache's entries at `path`, oldest first: [] without a file, and for a file that is not a
    pack cache (the next write replaces it)."""
    try:
        with open(str(path), 'rb') as f:
            data = json.loads(f.read().decode('utf-8'))
    except (FileNotFoundError, ValueError):
        return []
    entries = data.get('entries') if isinstance(data, dict) else None
    return [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []


def cached_pack(entries, key):
    """{'report': the pack's report, 'uv': the UV bytes it left (uv_bytes)} of the newest cache entry of
    `key` whose UVs are intact (their SHA-256), else None."""
    entry = next((e for e in reversed(entries) if e.get('key') == key), None)
    if entry is None or not isinstance(entry.get('report'), dict):
        return None
    try:
        raw = zlib.decompress(base64.b64decode(entry['uv']))
    except (KeyError, TypeError, ValueError, zlib.error):
        return None
    if hashlib.sha256(raw).hexdigest() != entry.get('sha'):
        return None
    return {'report': dict(entry['report']), 'uv': raw}


def kept_entries(entries, key, report, raw):
    """The pack cache's entries with the pack `key` recorded: its entry {'key', 'report', 'sha': SHA-256 hex
    of raw, 'uv': raw (the UV bytes the pack left) compressed and in base64} replaces the key's older one
    and goes last; the latest PACK_CACHE_ENTRIES are kept."""
    entry = {'key': key, 'report': dict(report), 'sha': hashlib.sha256(raw).hexdigest(),
             'uv': base64.b64encode(zlib.compress(raw, 9)).decode('ascii')}
    return ([e for e in entries or () if e.get('key') != key] + [entry])[-PACK_CACHE_ENTRIES:]


def write_pack_cache(path, entries):
    """Write the pack cache {'entries': [...]} to `path` as JSON, UTF-8, sorted keys, LF; returns the path."""
    os.makedirs(os.path.dirname(str(path)) or '.', exist_ok=True)
    with open(str(path), 'wb') as f:
        f.write((json.dumps({'entries': entries}, sort_keys=True, indent=1) + '\n').encode('utf-8'))
    return path


def _albedo_material(name, img, grit=GRIT):
    """Flat colour, with the print grit unless `grit` is None: the colour `grit` multiplied in where
    an object-space noise passes a threshold, so a source and the body it is baked onto share the
    pattern."""
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree; nt.nodes.clear()
    N = nt.nodes.new; L = nt.links.new
    vc = N('ShaderNodeVertexColor'); vc.layer_name = 'Col'
    if grit is None:
        em = N('ShaderNodeEmission'); out = N('ShaderNodeOutputMaterial')
        L(vc.outputs['Color'], em.inputs['Color']); L(em.outputs[0], out.inputs['Surface'])
    else:
        tc = N('ShaderNodeTexCoord')
        noise = N('ShaderNodeTexNoise')
        noise.inputs['Scale'].default_value = 60; noise.inputs['Detail'].default_value = 1
        L(tc.outputs['Object'], noise.inputs['Vector'])
        step = N('ShaderNodeMath'); step.operation = 'GREATER_THAN'; step.inputs[1].default_value = 0.64
        L(noise.outputs['Fac'], step.inputs[0])
        mix = N('ShaderNodeMix'); mix.data_type = 'RGBA'; mix.blend_type = 'MULTIPLY'
        L(step.outputs[0], mix.inputs[0]); L(vc.outputs['Color'], mix.inputs[6])
        mix.inputs[7].default_value = tuple(grit) + (1.0,) * (4 - len(grit))
        em = N('ShaderNodeEmission'); out = N('ShaderNodeOutputMaterial')
        L(mix.outputs[2], em.inputs['Color']); L(em.outputs[0], out.inputs['Surface'])
    tex = N('ShaderNodeTexImage'); tex.image = img
    nt.nodes.active = tex
    return m


def _copy_material(name, target, albedo):
    """The baked albedo re-baked onto itself. Its bake margin extends every island's final colours;
    without it the first pass's flat colour stays round islands a source painted and shows as
    seams under nearest-texel sampling."""
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree; nt.nodes.clear()
    src = nt.nodes.new('ShaderNodeTexImage'); src.image = albedo; src.interpolation = 'Closest'
    em = nt.nodes.new('ShaderNodeEmission'); out = nt.nodes.new('ShaderNodeOutputMaterial')
    nt.links.new(src.outputs['Color'], em.inputs['Color']); nt.links.new(em.outputs[0], out.inputs['Surface'])
    tgt = nt.nodes.new('ShaderNodeTexImage'); tgt.image = target
    nt.nodes.active = tgt
    return m


def include_collections(object_names):
    """Include in the active view layer, and show, every layer collection on the way to a collection that
    holds one of the objects `object_names` directly (a colour source in its excluded collection,
    lpk.core.builder.hidden_collection), so the objects can be shown, selected and baked. The layer
    collections are found first and changed after, outer first, each looked up again (a change of exclude
    rebuilds the layer collections under it). Returns [(collection name, its exclude, its hide_viewport)]
    for restore_collections, in the order changed."""
    from lpk.core import builder
    wanted = set(object_names)
    paths = []

    def walk(layer, path):
        for child in layer.children:
            here = path + [child.name]
            if any(o.name in wanted for o in child.collection.objects):
                paths.append(here)
            walk(child, here)
    vl = bpy.context.view_layer
    walk(vl.layer_collection, [])
    changed, seen = [], set()
    for path in paths:
        for name in path:
            lc = builder.layer_collection(vl.layer_collection, bpy.data.collections[name])
            if name in seen or lc is None or not (lc.exclude or lc.hide_viewport):
                continue
            seen.add(name)
            changed.append((name, lc.exclude, lc.hide_viewport))
            lc.exclude, lc.hide_viewport = False, False
    if changed:
        vl.update()
    return changed


def restore_collections(changed):
    """Put back the layer collections include_collections changed (its return value), inner first."""
    from lpk.core import builder
    vl = bpy.context.view_layer
    for name, exclude, hide in reversed(changed):
        coll = bpy.data.collections.get(name)
        lc = None if coll is None else builder.layer_collection(vl.layer_collection, coll)
        if lc is not None:
            lc.hide_viewport, lc.exclude = hide, exclude
    if changed:
        vl.update()


def source_specs(sources):
    """The bake settings of the colour sources in bake order: [{'object': the source's object name, 'mask':
    its parts as a tuple, or None for every part, 'cage': its cage in metres, else BAKE_CAGE, 'ray': its ray
    in metres, else BAKE_RAY, 'over': whether the frozen-texture bake composites it over the frozen atlas
    (bake_over), default False}]. sources: [{'object', and optionally 'mask', 'cage', 'ray', 'over'}] in
    bake order, later sources covering earlier ones. Raises ValueError for a source whose object the scene
    lacks."""
    missing = [s['object'] for s in sources if bpy.data.objects.get(s['object']) is None]
    if missing:
        raise ValueError('colour sources without an object in the scene: %s' % ', '.join(missing))
    return [{'object': s['object'], 'mask': None if s.get('mask') is None else tuple(s['mask']),
             'cage': BAKE_CAGE if s.get('cage') is None else float(s['cage']),
             'ray': BAKE_RAY if s.get('ray') is None else float(s['ray']), 'over': bool(s.get('over', False))}
            for s in sources]


def _bake_sources(obj_name, sheet_of, atlas, specs, face_part, face_pred, strips, save_dir, grit, material, margin,
                  final_name, own):
    """Colour atlas on the current UVs (bake's kernel). Albedo pass: the mesh's flat colours (times the grit
    pattern of colour `grit`, none when it is None; _albedo_material), then each source object baked
    selected-to-active in order (later sources cover earlier ones). specs: the sources' bake settings in
    bake order, [{'object', 'mask', 'cage', 'ray'}] (source_specs): a source with a mask writes only into
    those parts, the other faces baking into a throwaway image, or rays from a plate or a neighbouring part
    pick up a source lying under it; its rays start cage metres above the body and run ray metres from
    there. A copy pass then bakes the albedo onto the atlas so the margin extends the final colours, and the
    body gets the final material `material` (_final_material), named final_name (the atlas image's name
    too), the image saved as <save_dir>/<image name>.png unless save_dir is None. The working images and
    materials it leaves are the ones _working names.

    The faces of the `own` parts' groups (sheet_of gives them, _own_sheet) bake into a throwaway image in
    every pass, so nothing of the atlas is baked onto them, and the final body takes each such material on
    a slot after the atlas's, in the order of `own`, then of their first faces, with its faces' material
    indices. own: {material name: True to use the scene's material of that name as it is}; any other own
    material is made here as a placeholder (_flat_material of the colour most of its faces carry, the
    first in face order on a tie, read from their Col). The face island (face_part, face_pred, as for
    unwrap_color_atlas) only names its group in the report. margin: the pack margin the islands were
    packed with (pack_step's), for the report only, or None. Returns {group: {'coverage': the share of the
    atlas its UV islands cover, 'tris': its triangles, 'texels_per_m': texels per metre of its surface}}
    plus 'coverage_total': the share of the atlas all groups cover, 'islands': the UV islands, 'by_part':
    part_islands' list of every part with its islands and its share of the atlas, the part with the most
    islands first, and 'margin_share': the share of the atlas the pack margin takes round them, estimated
    as their border length times half the margin (None without margin); 'texels': texel_readings' report
    over the body and the sources, 'reach': {source: source_reach's report}, in bake order, and 'own':
    {material: {'tris': its faces, 'slot': its material slot, 'placeholder': whether the bake made it}} of
    the `own` groups, which every other reading leaves out as they lie outside the atlas.

    A painted line samples at its part's density, its group's texels per metre times its boost, and
    bakes unbroken from MIN_LINE_TEXELS across. A source bakes where its surface lies within its rays'
    reach, from cage above the body to ray - cage below it. Each source bakes in a pass of its own with
    only it selected, so within a pass a ray paints the first face of that source it meets, and a later
    source covers an earlier one wherever its rays reach. A source outside the reach bakes holes; layers of
    one source lying almost on each other, or a coarse grid whose flat faces dip between its vertices
    toward what lies under them, can bake patchy, and where a later source's rays miss, the earlier source
    shows through. No fixed lift or layer spacing bakes whole on every surface: 'reach' reads the reach at
    the vertices, and the atlas close-up over an overlap shows the rest."""
    ob, me, ctx, parts, part_of, is_face, ug = _atlas_setup(obj_name, sheet_of, face_part, face_pred, strips)
    outside = {}
    for i, g in enumerate(ug):
        if _own(g):
            outside.setdefault(g[len(OWN_PREFIX):], []).append(i)
    outside = {m: outside[m] for m in [m for m in own if m in outside] + [m for m in outside if m not in own]}
    sunk = {i for faces in outside.values() for i in faces}
    scene = bpy.context.scene
    size = atlas[0]
    imgs = {}
    for key in ('Albedo', 'Atlas'):
        nm = obj_name + '_' + key
        if bpy.data.images.get(nm):
            bpy.data.images.remove(bpy.data.images[nm])
        imgs[key] = bpy.data.images.new(nm, size, size, alpha=False)
    alb, img = imgs['Albedo'], imgs['Atlas']
    me.materials.clear()
    me.materials.append(_albedo_material(obj_name + '_BakeAlbedo', alb, grit))
    sink = bpy.data.images.get(obj_name + '_Sink') or bpy.data.images.new(obj_name + '_Sink', 64, 64)
    me.materials.append(_albedo_material(obj_name + '_BakeSink', sink, grit))
    for p in me.polygons:
        p.material_index = 1 if p.index in sunk else 0
    prev = scene.render.engine
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'; scene.cycles.samples = 1
    scene.render.bake.margin = BAKE_MARGIN; scene.render.bake.margin_type = 'EXTEND'
    with bpy.context.temp_override(active_object=ob, object=ob, selected_objects=[ob]):
        bpy.ops.object.bake(type='EMIT', use_clear=True)
    scene.render.bake.margin = 0
    for spec in specs:
        src = spec['object']
        det = bpy.data.objects[src]
        mask = None if spec['mask'] is None else set(spec['mask'])
        for p, pn in zip(me.polygons, part_of):
            p.material_index = 0 if (mask is None or pn in mask) and p.index not in sunk else 1
        det.hide_set(False); det.hide_render = False
        det.data.materials.clear()
        det.data.materials.append(_albedo_material(src + '_BakeAlbedo', alb, grit))
        with bpy.context.temp_override(active_object=ob, object=ob, selected_objects=[ob, det]):
            bpy.ops.object.bake(type='EMIT', use_clear=False, use_selected_to_active=True,
                                cage_extrusion=spec['cage'], max_ray_distance=spec['ray'])
        det.hide_set(True); det.hide_render = True
    for p in me.polygons:
        p.material_index = 1 if p.index in sunk else 0
    me.materials[0] = _copy_material(obj_name + '_BakeCopy', img, alb)
    scene.render.bake.margin = BAKE_MARGIN
    with bpy.context.temp_override(active_object=ob, object=ob, selected_objects=[ob]):
        bpy.ops.object.bake(type='EMIT', use_clear=True)
    scene.render.engine = prev
    for p in me.polygons:
        p.material_index = 0
    me.materials.pop(index=1)
    me.materials[0] = _final_material(final_name, img, material)
    placed = _place_own(me, outside, own, material)
    if save_dir:
        _save(img, save_dir)
    areas = {g: v for g, v in _group_areas(me, ug).items() if not _own(g)}
    report = {g: {'coverage': round(ua, 3), 'tris': ug.count(g),
                  'texels_per_m': round(math.sqrt(ua * size * size / sa), 1)}
              for g, (ua, sa) in areas.items()}
    report['coverage_total'] = round(sum(ua for ua, _ in areas.values()), 3)
    islands, border = _island_border(me, sunk)
    report['islands'] = len(islands)
    report['by_part'] = part_islands(islands, part_of,
                                     [None if i in sunk else ua for i, (ua, _) in enumerate(_face_areas(me))])
    report['margin_share'] = None if margin is None else round(min(1.0, border * margin / 2), 3)
    report['texels'] = texel_readings(obj_name, specs, part_of, is_face, size, {part_of[i] for i in sunk})
    report['reach'] = {}
    for spec in specs:
        report['reach'][spec['object']] = source_reach(obj_name, spec, part_of)
    report['own'] = placed
    return report


def _place_own(me, outside, kept, material):
    """The `own` materials on the slots after the atlas's: outside, {material: its face indices} in slot
    order; kept: {material: True to use the scene's material as it is}; any other is made as a placeholder
    (_flat_material of _own_colour, in the final material `material`). Each face takes its material's slot.
    Returns {material: {'tris', 'slot', 'placeholder'}}."""
    placed = {}
    for slot, (m, faces) in enumerate(outside.items(), 1):
        made = not kept.get(m)
        me.materials.append(_flat_material(m, _own_colour(me, faces), material) if made else bpy.data.materials[m])
        for i in faces:
            me.polygons[i].material_index = slot
        placed[m] = {'tris': len(faces), 'slot': slot, 'placeholder': made}
    return placed


def _save(img, save_dir):
    """Save the image as <save_dir>/<its name>.png."""
    img.filepath_raw = save_dir.rstrip('/\\') + '/' + img.name + '.png'
    img.file_format = 'PNG'
    img.save()


def _own_colour(me, faces):
    """The linear RGBA (Col) of the palette index most of `faces` (polygon indices of the mesh `me`) carry, the
    first in face order on a tie, read at the first corner of its first face."""
    pal = me.attributes['pal'].data
    count, first = {}, {}
    for i in faces:
        k = pal[i].value
        count[k] = count.get(k, 0) + 1
        first.setdefault(k, i)
    k = max(count, key=lambda k: (count[k], -first[k]))
    return tuple(me.color_attributes['Col'].data[me.polygons[first[k]].loop_start].color)


def _working(obj_name, specs):
    """{'images', 'materials'}: the names of the working images and materials _bake_sources makes besides the
    atlas image and the final material."""
    return {'images': [obj_name + '_Albedo', obj_name + '_Sink'],
            'materials': [obj_name + '_BakeAlbedo', obj_name + '_BakeSink', obj_name + '_BakeCopy']
            + [spec['object'] + '_BakeAlbedo' for spec in specs]}


def _island_border(me, skip=()):
    """(the UV islands of the mesh's UVMap, each a list of its face indices, their border length in UV
    units): an edge is inside an island when its two faces meet in UV at both ends; every other edge
    side is border. The faces in `skip` (outside the atlas) and their islands are left out."""
    bm = bmesh.new(); bm.from_mesh(me)
    try:
        uvl = bm.loops.layers.uv[UV_LAYER]
        islands = [[f.index for f in fs] for fs in _uv_islands(bm, uvl) if fs[0].index not in skip]
        border = 0.0
        for f in bm.faces:
            if f.index in skip:
                continue
            for l in f.loops:
                ends = {l.vert: l[uvl].uv, l.link_loop_next.vert: l.link_loop_next[uvl].uv}
                other = [m for m in l.edge.link_loops if m.face is not f]
                if len(other) == 1:
                    o = other[0]
                    theirs = {o.vert: o[uvl].uv, o.link_loop_next.vert: o.link_loop_next[uvl].uv}
                    if all((uv - theirs[v]).length < zones.UV_MATCH for v, uv in ends.items()):
                        continue
                border += (l.link_loop_next[uvl].uv - l[uvl].uv).length
    finally:
        bm.free()
    return islands, border


def part_islands(islands, part_of, uv_areas):
    """Where the atlas's islands come from, part by part: [{'part', 'islands': the UV islands holding a
    face of the part (an island that spans parts counts for each of them), 'coverage': the share of the
    atlas the part's faces cover, to four places}] for every part with a face, the part with the most
    islands first, then by name. islands: [[face index, ...], ...]; part_of: the part of each face;
    uv_areas: the UV area of each face, a share of the atlas, None for a face outside it (left out).

    A part of many small islands pays a margin ring round each of them, and its texels go wherever its
    group's density puts them: one that carries a single flat colour needs few texels, so routing it
    with sheet_of to a group of lower relative density raises every other island's texels per metre at
    the next bake, though the coverage itself may move little."""
    count, area = {}, {}
    for fs in islands:
        for part in {part_of[i] for i in fs}:
            count[part] = count.get(part, 0) + 1
    for part, a in zip(part_of, uv_areas):
        if a is not None:
            area[part] = area.get(part, 0.0) + a
    return [{'part': p, 'islands': count.get(p, 0), 'coverage': round(area[p], 4)}
            for p in sorted(area, key=lambda p: (-count.get(p, 0), p))]


def marks_text(b):
    """The painted marks a builder recorded (lpk.core.shapes._mark) as the JSON text of the MARKS property
    the bake's texel readings read (marks_of, texel_readings), or None when it recorded none (the object
    then holds no MARKS). b: the Builder."""
    import json
    marks = b.__dict__.get('marks')
    return json.dumps(marks) if marks else None


def marks_of(ob):
    """The painted marks stored on an object (marks_text): [{'tool': the form that drew it, 'part': its
    part on the builder, 'kind': 'line' or 'eye', 'width': metres across, 'points': [[x, y, z], ...]
    where it lies, in the object's own space, and for a line whose width changes along it 'widths':
    [metres across at each point]}], [] without any."""
    import json
    return json.loads(ob[MARKS]) if MARKS in ob else []


def _face_areas(me):
    """[(UV area, surface area)] of every polygon on the current UVMap."""
    uv = me.uv_layers[UV_LAYER].data
    out = []
    for p in me.polygons:
        q = [Vector(uv[li].uv) for li in p.loop_indices]
        out.append((sum(abs((q[i] - q[0]).cross(q[i + 1] - q[0])) / 2 for i in range(1, len(q) - 1)), p.area))
    return out


def _body_tree(ob, part_of, mask):
    """(a BVH tree of the body's polygons in world space, the polygon index of each of its entries):
    the polygons of the parts in `mask`, or all of them when mask is None; (None, []) when none is."""
    from mathutils.bvhtree import BVHTree
    me = ob.data
    idx = [p.index for p in me.polygons if mask is None or part_of[p.index] in mask]
    if not idx:
        return None, []
    M = ob.matrix_world
    verts = [M @ v.co for v in me.vertices]
    return BVHTree.FromPolygons(verts, [tuple(me.polygons[i].vertices) for i in idx]), idx


def texel_readings(obj_name, specs, part_of, is_face, size, outside=()):
    """Texels per metre of every part of the body on its current UVs, boost included, and of each
    painted mark the build recorded on the body and on the colour sources (marks_of).

    obj_name: the body; specs: the sources' bake settings in bake order (source_specs); part_of: the part
    of each polygon; is_face: whether each polygon is in the face island; size: the atlas's side in pixels;
    outside: the parts outside the atlas (`own`), left out, a mark over one read as over no polygon.
    A mark reads, at each of its points, the density of the nearest body polygon among the parts its
    source's mask names (all of them for the body's own marks and an unmasked source), the face island's
    where the polygon is in it, times the mark's width there (its 'widths' where it tapers), and keeps the
    point of fewest texels.

    Returns {'parts': {part: texels per metre over its polygons outside the face island}, in the body's part
    order; 'face': the face island's texels per metre, None without one; 'lines': the marks of kind 'line',
    fewest texels first (the unplaced ones last); 'eyes': the marks of kind 'eye', in the order they were
    drawn}. A mark is {'object', 'tool'} and mark_texels' {'part', 'width', 'texels_per_m', 'texels',
    'points', 'under'}."""
    ob = bpy.data.objects[obj_name]
    sums = {}
    for i, (ua, sa) in enumerate(_face_areas(ob.data)):
        if part_of[i] in outside:
            continue
        key = None if is_face[i] else part_of[i]
        u, s = sums.get(key, (0.0, 0.0))
        sums[key] = (u + ua, s + sa)
    dens = {k: size * math.sqrt(u / s) for k, (u, s) in sums.items() if s > 0}
    out = {'parts': {p: round(dens[p], 1) for p in ob['parts'] if p in dens},
           'face': round(dens[None], 1) if None in dens else None, 'lines': [], 'eyes': []}
    trees = {}
    for name, mask in [(obj_name, None)] + [(spec['object'], spec['mask']) for spec in specs]:
        mobj = bpy.data.objects[name]
        marks = marks_of(mobj)
        if not marks:
            continue
        if mask not in trees:
            trees[mask] = _body_tree(ob, part_of, mask)
        tree, idx = trees[mask]
        for mk in marks:
            samples = []
            for p in mk['points'] if tree else ():
                hit = tree.find_nearest(mobj.matrix_world @ Vector(p))
                f = None if hit[2] is None else idx[hit[2]]
                d = None if f is None else dens.get(None if is_face[f] else part_of[f])
                samples.append(None if d is None else (d, part_of[f]))
            entry = dict({'object': name, 'tool': mk['tool']}, **mark_texels(mk['width'], samples, mk.get('widths')))
            out['lines' if mk['kind'] == 'line' else 'eyes'].append(entry)
    out['lines'].sort(key=lambda e: (e['texels'] is None, e['texels'] or 0.0))
    return out


def mark_texels(width, samples, widths=None):
    """The texel reading of one painted mark (texel_readings). width: metres across; samples: per point
    of the mark, (texels per metre of the body polygon under it, that polygon's part), or None where
    no polygon lies under it; widths: the width at each point (marks_of's 'widths'), None for `width`
    everywhere. Returns {'part': the part under the point of fewest texels, 'width': metres across
    there, 'texels_per_m': the density there, 'texels': the width there in texels, 'points': the points
    read, 'under': those under MIN_LINE_TEXELS}; part, texels_per_m and texels None when no point is
    read, and width then the mark's."""
    best, read, under = None, 0, 0
    for sample, w in zip(samples, widths if widths is not None else [width] * len(samples)):
        if sample is None:
            continue
        d, part = sample
        read += 1
        under += w * d < MIN_LINE_TEXELS
        if best is None or w * d < best[0] * best[1]:
            best = (d, w, part)
    return {'part': best and best[2], 'width': best[1] if best else width,
            'texels_per_m': best and round(best[0], 1), 'texels': best and round(best[0] * best[1], 2),
            'points': read, 'under': under}


def reach_band(heights, cage, ray):
    """Where a source's vertices stand against the reach of its bake rays, which start `cage` metres
    above the body and run `ray` metres from there: a surface between cage above the body and
    ray - cage below it bakes, one outside that band is missed. heights: [metres] each vertex's height
    over the nearest body polygon, negative under its surface. Returns {'highest', 'lowest': metres,
    None without vertices, 'beyond': [[vertex index, height], ...] the vertices above the cage, highest
    first, 'deep': [[vertex index, height], ...] the vertices below the ray's end, lowest first}; a
    height within POSITION_NOISE of the band's edge is inside it."""
    hs = [round(float(h), 6) for h in heights]
    top, bottom = cage + POSITION_NOISE, cage - ray - POSITION_NOISE
    beyond = sorted(([i, h] for i, h in enumerate(hs) if h > top), key=lambda e: (-e[1], e[0]))
    deep = sorted(([i, h] for i, h in enumerate(hs) if h < bottom), key=lambda e: (e[1], e[0]))
    return {'highest': max(hs) if hs else None, 'lowest': min(hs) if hs else None, 'beyond': beyond, 'deep': deep}


def source_reach(obj_name, spec, part_of):
    """How far each vertex of a colour source lies off the body, against its bake rays' reach (_bake_sources:
    a texel's ray starts the source's cage above the body along the polygon's normal and runs its ray
    inward). A vertex's height is its distance from the nearest body polygon among the parts the source's
    mask names (every part without one), negative under the polygon's surface. A vertex whose nearest body
    polygon carries a part outside the mask lies over a part the source does not paint and is left out. The
    reach is read at the vertices, so a face of the source that bulges between them is not seen.

    obj_name: the body; spec: the source's bake settings {'object', 'mask', 'cage', 'ray'} (source_specs);
    part_of: the part of each body polygon. Returns {'cage', 'ray': metres, 'mask': [parts] or None,
    'vertices': the source's vertices, 'faces': the body polygons it can bake onto, 'unmasked': the
    vertices left out over other parts} plus reach_band's {'highest', 'lowest', 'beyond', 'deep'}, whose
    vertex indices are the source's."""
    ob, det = bpy.data.objects[obj_name], bpy.data.objects[spec['object']]
    cage, ray = float(spec['cage']), float(spec['ray'])
    mask = None if spec['mask'] is None else list(spec['mask'])
    tree, idx = _body_tree(ob, part_of, mask)
    every, every_idx = _body_tree(ob, part_of, None) if mask is not None else (None, None)
    ids, heights, unmasked = [], [], 0
    for v in det.data.vertices if tree else ():
        p = det.matrix_world @ v.co
        if every is not None and part_of[every_idx[every.find_nearest(p)[2]]] not in mask:
            unmasked += 1
            continue
        loc, nrm, _, dist = tree.find_nearest(p)
        ids.append(v.index)
        heights.append(dist if (p - loc).dot(nrm) >= 0 else -dist)
    out = {'cage': cage, 'ray': ray, 'mask': mask, 'vertices': len(det.data.vertices), 'faces': len(idx),
           'unmasked': unmasked}
    band = reach_band(heights, cage, ray)
    for key in ('beyond', 'deep'):
        band[key] = [[ids[i], h] for i, h in band[key]]
    out.update(band)
    return out


def check_groups(obj_name, sheet_of, groups, own=()):
    """Raise ValueError unless every atlas group sheet_of gives a face of the mesh object `obj_name` (its
    'palette' colour and its first vertex's part) outside the parts of `own` ({part: material name}) is a
    key of `groups` ({group: density}): the unwrap fails obscurely otherwise."""
    ob = bpy.data.objects[obj_name]
    parts, palette = list(ob['parts']), list(ob['palette'])
    me = ob.data
    pal, part = me.attributes['pal'].data, me.attributes['part'].data
    used = {(palette[pal[p.index].value], parts[part[p.vertices[0]].value]) for p in me.polygons}
    used = {(c, pt) for c, pt in used if pt not in own}
    missing = sorted({sheet_of(c, pt) for c, pt in used} - set(groups))
    if missing:
        raise ValueError('sheet_of gives atlas groups %s that the atlas has no density for' % missing)


def corner_colours(pal, loop_starts, loop_totals, names, colours):
    """The `Col` corner colours of a mesh: linear RGBA as float32, four values per loop in loop order. pal:
    each polygon's palette index; loop_starts, loop_totals: each polygon's first loop and loop count; names:
    the palette names by index (the object's 'palette', as it was built); colours: {name: sRGB (r, g, b)},
    converted as lpk.core.builder.finish converts them (srgb_to_linear), so a recolour with the build's
    colours writes the build's values. Raises ValueError for a name `colours` lacks."""
    missing = [n for n in names if n not in colours]
    if missing:
        raise ValueError('the colours have no colour for the palette names %s the body was built with: run '
                         'the build' % ', '.join(missing))
    from lpk.core.builder import srgb_to_linear
    lins = np.array([srgb_to_linear(colours[n]) for n in names], np.float32).reshape(-1, 4)
    pal = np.asarray(pal, np.int64)
    starts, totals = np.asarray(loop_starts, np.int64), np.asarray(loop_totals, np.int64)
    loops = np.repeat(starts, totals) + np.arange(int(totals.sum())) - np.repeat(np.cumsum(totals) - totals, totals)
    out = np.zeros((int((starts + totals).max()) if len(totals) else 0, 4), np.float32)
    out[loops] = lins[np.repeat(pal, totals)]
    return out.ravel()


def recolour(object_names, colours):
    """The refinement of the build's `Col` before a bake: on each mesh object of object_names (the body,
    then the colour sources) the corner colour attribute `Col` is rewritten from `colours` ({name: sRGB})
    by each face's palette index (corner_colours); nothing else of the mesh changes. Raises ValueError,
    before any object changes, for an object without the `Col` corner colours the build writes and for a
    palette name `colours` lacks. Returns {object name: the corners written}."""
    plan = []
    for name in object_names:
        ob = bpy.data.objects[name]
        me = ob.data
        col = me.color_attributes.get('Col')
        if col is None or col.domain != 'CORNER' or col.data_type != 'FLOAT_COLOR':
            raise ValueError('%s has no Col corner colours: run the build' % name)
        n = len(me.polygons)
        pal, starts, totals = (np.zeros(n, np.int32) for _ in range(3))
        if n:
            me.attributes['pal'].data.foreach_get('value', pal)
            me.polygons.foreach_get('loop_start', starts)
            me.polygons.foreach_get('loop_total', totals)
        plan.append((me, col, corner_colours(pal, starts, totals, list(ob['palette']), colours)))
    out = {}
    for (me, col, data), name in zip(plan, object_names):
        if len(data):
            col.data.foreach_set('color', data)
        me.update()
        out[name] = len(data) // 4
    return out


def own_materials(own):
    """The material names of `own` ({part: material name}), each once, in the order of its first
    part: the order of their slots after the atlas's."""
    return list(dict.fromkeys(own.values()))


def unwrap(obj_name, sheet_of, atlas, face_part=None, face_pred=None, boost=None, strips=None, cuts=None,
           panels=None, hard=None, own=None, default_group=None, angle_limit=66, margin=0.006,
           margin_method='FRACTION'):
    """UVs for the colour atlas on the mesh object `obj_name`, not packed yet: check_groups, then
    unwrap_seamed_atlas when any of cuts, panels and hard is given (None each: not given), else
    unwrap_color_atlas.

    sheet_of(colour, part) -> atlas group; atlas: (size in pixels, {group: relative texel density});
    face_part, face_pred(centre, normal) -> bool: the face island, none without face_pred; boost: {part:
    linear UV scale}; strips: {part: loft sides}; cuts, panels, hard: the seamed unwrap's cut_sides ({part:
    [direction, ...]}), panels ({part: [direction, ...]}) and hard ({part: degrees}); own: {part: material
    name}, parts outside the atlas, smart-projected alone into the whole UV square with `margin` (a share
    of it) and `margin_method` (PACK_MARGINS, as the pack's); default_group: the group whose density the
    face island and the strips take, None for the first of atlas; angle_limit: degrees, the smart
    projection's angle and the seamed unwrap's flat-projection limit. Raises ValueError for a group
    sheet_of gives that atlas lacks, a strip part that is not one loft of its sides, and an unknown
    margin_method. Returns that unwrap's report (unwrap_color_atlas: 'face_tris', 'face_angle';
    unwrap_seamed_atlas adds 'regions', 'projected', 'cut_open', 'split', 'extra_cuts', 'fallback' and
    'fallback_tris', the triangles per part left to smart project)."""
    own = own or {}
    check_groups(obj_name, sheet_of, atlas[1], own)
    common = dict(face_part=face_part, face_pred=face_pred, boost_parts=boost, strips=strips, angle_limit=angle_limit,
                  default_group=next(iter(atlas[1])) if default_group is None else default_group, margin=margin,
                  margin_method=margin_method)
    sheet = _own_sheet(sheet_of, own)
    if cuts is None and panels is None and hard is None:
        return unwrap_color_atlas(obj_name, sheet, atlas, **common)
    return unwrap_seamed_atlas(obj_name, sheet, atlas, cut_sides=cuts, panels=panels, hard=hard, **common)


def bake(obj_name, sheet_of, atlas, sources=(), colours=None, face_part=None, face_pred=None, strips=None, own=None,
         grit=None, material='base', margin=0.006, save_dir=None):
    """The colour atlas baked on the current UVs of the body `obj_name`: the recolour of `Col` on the body
    and every source from `colours` (recolour; none when colours is None), then the bake (_bake_sources)
    with the colour sources in bake order, the grit, and the final material `material` named
    '<obj_name>_Atlas' on the body's slot 0, the atlas image '<obj_name>_Atlas' saved as
    <save_dir>/<obj_name>_Atlas.png unless save_dir is None. A collection holding a source that is excluded
    from the view layer or hidden (the sources' own, lpk.core.builder.hidden_collection) is included for the
    call (include_collections) and put back after it; each source's materials and visibility are put
    back as found, the body's slot links are held on its mesh materials while it bakes
    (lpk.stages.preview.mesh_materials: the preview's display link comes back), and the bake's working
    images and materials are removed.

    sheet_of, atlas, face_part, face_pred, strips, own: as given to unwrap; sources: [{'object': its object
    name, 'mask': the parts it may paint or None, 'cage', 'ray': metres or None for BAKE_CAGE, BAKE_RAY}]
    in bake order (source_specs); colours: {palette name: sRGB (r, g, b)}; grit: None for flat colours,
    else the colour (r, g, b) or (r, g, b, a) multiplied in a sparse object-space noise (GRIT is one);
    material: a name of FINAL_MATERIALS; margin: the pack margin the islands were packed with, for the
    report's margin_share. An `own` material the scene holds is used as it is; any other is made as a
    placeholder. Raises ValueError, before anything changes, for a source without an object, an unknown
    material, an object without Col and a palette name `colours` lacks.

    Returns {'report': _bake_sources' report (coverage per group and in total, islands, by_part,
    margin_share, 'texels': the texel widths of the marked lines and eyes, 'reach': each source's reach,
    'own'), 'files': [the atlas PNG's path], empty without save_dir, 'recoloured': recolour's {object:
    corners}}."""
    specs = source_specs(sources)
    if material not in FINAL_MATERIALS:
        raise ValueError('final material %r: use one of %s' % (material, ', '.join(MATERIALS)))
    own = own or {}
    recoloured = {} if colours is None else recolour([obj_name] + [s['object'] for s in specs], colours)
    if save_dir is not None:
        os.makedirs(str(save_dir), exist_ok=True)
    name = obj_name + '_Atlas'
    kept = {m: bpy.data.materials.get(m) is not None for m in own_materials(own)}
    with _baking(obj_name, specs, _working(obj_name, specs)):
        report = _bake_sources(obj_name, _own_sheet(sheet_of, own), atlas, specs, face_part, face_pred,
                               strips or {}, None if save_dir is None else str(save_dir), grit, material, margin,
                               name, kept)
    return {'report': report, 'files': [] if save_dir is None else [bpy.data.images[name].filepath_raw],
            'recoloured': recoloured}


@contextmanager
def _baking(obj_name, specs, working):
    """The scene set for a bake of the body `obj_name` with the sources `specs` (source_specs) for the
    block: the sources' collections included (include_collections) and the sources hidden, the body's slots
    held on its mesh materials (lpk.stages.preview.mesh_materials); afterwards, also after an error, each
    source's materials and visibility put back as found, the collections restored, and the working images
    and materials `working` ({'images', 'materials'}: names) removed."""
    included = include_collections([s['object'] for s in specs])
    found = {}
    for spec in specs:
        det = bpy.data.objects[spec['object']]
        found[spec['object']] = (det.hide_get(), det.hide_render, list(det.data.materials))
        det.hide_set(True)
    try:
        with preview.mesh_materials(bpy.data.objects[obj_name]):
            yield
    finally:
        for src, (hidden, render, materials) in found.items():
            det = bpy.data.objects[src]
            det.data.materials.clear()
            for m in materials:
                det.data.materials.append(m)
            det.hide_set(hidden)
            det.hide_render = render
        restore_collections(included)
        for m in working['materials']:
            if bpy.data.materials.get(m) is not None:
                bpy.data.materials.remove(bpy.data.materials[m])
        for i in working['images']:
            if bpy.data.images.get(i) is not None:
                bpy.data.images.remove(bpy.data.images[i])


# -- the frozen texture --------------------------------------------------------------------------------------

def image_levels(name):
    """The image `name`'s texels as an atlas array (lpk.stages.imaging: uint8 (H, W, 4), Blender's
    order), its pixels rounded to 8-bit levels (imaging.texel_levels); an image of fewer channels is padded
    with opaque alpha."""
    img = bpy.data.images[name]
    w, h = img.size
    px = np.empty(w * h * img.channels, np.float32)
    img.pixels.foreach_get(px)
    px = px.reshape(h, w, img.channels)
    if img.channels < 4:
        rgb = px[..., :3] if img.channels >= 3 else np.repeat(px[..., :1], 3, axis=2)
        px = np.concatenate([rgb, np.ones((h, w, 1), np.float32)], axis=2)
    return imaging.texel_levels(px)


def texel_digest(levels):
    """The SHA-256 hex of an atlas array's levels and shape: the texel digest of the image stamp."""
    levels = np.ascontiguousarray(np.asarray(levels, np.uint8))
    return hashlib.sha256(repr(levels.shape).encode('ascii') + levels.tobytes()).hexdigest()


def stamp_image(name):
    """Write IMAGE_STAMP, the texel digest of the image `name` as it stands, on it. Returns the digest."""
    img = bpy.data.images[name]
    img[IMAGE_STAMP] = texel_digest(image_levels(name))
    return img[IMAGE_STAMP]


def image_edited(name):
    """How the image `name` differs from its stamp (stamp_image): None when it matches or the image is
    missing, 'unstamped' when it carries no stamp, 'texels' when its texels changed since (a hand paint)."""
    img = bpy.data.images.get(name)
    if img is None:
        return None
    if IMAGE_STAMP not in img:
        return 'unstamped'
    return None if texel_digest(image_levels(name)) == img[IMAGE_STAMP] else 'texels'


def write_image(name, levels, alpha=False):
    """The 8-bit sRGB image `name` (replacing an image of that name) holding the atlas array `levels`
    exactly (its pixels levels / 255, which Blender stores as those levels). Returns the image."""
    levels = np.asarray(levels, np.uint8)
    h, w = levels.shape[:2]
    old = bpy.data.images.get(name)
    if old is not None:
        bpy.data.images.remove(old)
    img = bpy.data.images.new(name, w, h, alpha=alpha)
    img.pixels.foreach_set((levels.astype(np.float32) / 255.0).ravel())
    img.update()
    return img


def store_image(src_name, dst_name):
    """A copy of the image `src_name` as it stands in memory (a hand paint in Texture Paint included, saved
    or not) as the frozen texture's atlas `dst_name` (store_levels). A float image is stored as its pixels
    rounded to 8-bit levels (image_levels): an image the kit baked is 8-bit already and copies exactly.
    Returns store_levels' report. Raises ValueError when `src_name` is missing."""
    if bpy.data.images.get(src_name) is None:
        raise ValueError('no image %s to store: run the bake first' % src_name)
    return store_levels(dst_name, image_levels(src_name))


def store_levels(dst_name, levels):
    """The atlas array `levels` as the 8-bit sRGB image `dst_name` (replacing one of that name), packed
    into the .blend and with a fake user, so a saved .blend keeps it: the frozen texture's atlas. Returns
    {'image': dst_name, 'size': [width, height], 'packed': whether Blender packed it, 'texels': its texel
    digest}."""
    img = write_image(dst_name, levels, alpha=True)
    img.pack()
    img.use_fake_user = True
    return {'image': dst_name, 'size': [int(img.size[0]), int(img.size[1])], 'packed': img.packed_file is not None,
            'texels': texel_digest(levels)}


def island_count(obj_name):
    """The UV islands of the body's atlas UV layer UV_LAYER: faces joined where they meet in UV at both
    ends of a shared edge."""
    bm = bmesh.new()
    bm.from_mesh(bpy.data.objects[obj_name].data)
    try:
        return len(_uv_islands(bm, bm.loops.layers.uv[UV_LAYER]))
    finally:
        bm.free()


def bake_over(obj_name, frozen_image, sources=(), colours=None, own=None, grit=None, material='base',
              save_dir=None, margin=BAKE_MARGIN):
    """The atlas '<obj_name>_Atlas' of a frozen texture: the image `frozen_image` (the frozen atlas
    '<NAME>_AtlasFrozen', never changed) with each colour source of `sources` composited over it in bake
    order on the body's current UVs, at the frozen image's size, then the final material `material` named
    '<obj_name>_Atlas' on the body's slot 0 and the `own` materials after it, and the image saved as
    <save_dir>/<obj_name>_Atlas.png unless save_dir is None. Without sources the atlas is the frozen image.

    Each source bakes as in bake (selected to active, within its mask, from cage above the body over its
    ray; the grit `grit`; faces outside the mask and of the `own` parts into a throwaway image) into a
    transparent layer, so the texels its rays hit are the ones the bake wrote (opaque); those texels, and
    the bake margin of `margin` texels round them outside every island (the islands read off a bake of the
    body itself), take the layer's colour (lpk.stages.imaging.composite_layer). Every other texel keeps the
    frozen image's levels exactly, the pixels a hand paint left included: the composite starts from the
    frozen image on every call, so baking again composites the same sources over the same base. A source
    covers a hand paint wherever its rays hit. The body's own colours (Col) are not baked.

    sources, colours, own, grit, material: as bake's (own: {part: material name}); `sources` here are
    the ones to add (the model's 'over' sources). Raises ValueError, before anything changes, for a
    missing frozen image, a source without an object, an unknown material, and what recolour raises.

    Returns {'report': {'frozen': frozen_image, 'size': [width, height], 'sources': {source object:
    {'hit': texels its rays hit, 'margin': margin texels written, 'changed': texels whose levels it changed
    over what the earlier sources left}}, in bake order, 'changed': texels that differ from the frozen
    image, 'reach': {source: source_reach's report}, 'own': {material: {'tris', 'slot', 'placeholder'}}},
    'files': [the atlas PNG's path], empty without save_dir, 'recoloured': recolour's {source: corners}}."""
    if bpy.data.images.get(frozen_image) is None:
        raise ValueError('no frozen atlas %s in the open .blend: run freeze_texture (or adopt a textured model) '
                         'first' % frozen_image)
    specs = source_specs(sources)
    if material not in FINAL_MATERIALS:
        raise ValueError('final material %r: use one of %s' % (material, ', '.join(MATERIALS)))
    own = own or {}
    recoloured = {} if colours is None else recolour([s['object'] for s in specs], colours)
    if save_dir is not None:
        os.makedirs(str(save_dir), exist_ok=True)
    name = obj_name + '_Atlas'
    working = {'images': [obj_name + '_Layer', obj_name + '_Sink'],
               'materials': [obj_name + '_BakeLayer', obj_name + '_BakeSink']
               + [spec['object'] + '_BakeAlbedo' for spec in specs]}
    with _baking(obj_name, specs, working):
        report = _bake_over(obj_name, frozen_image, specs, own, grit, material, margin, name,
                            None if save_dir is None else str(save_dir))
    return {'report': report, 'files': [] if save_dir is None else [bpy.data.images[name].filepath_raw],
            'recoloured': recoloured}


def _bake_over(obj_name, frozen_image, specs, own, grit, material, margin, name, save_dir):
    """bake_over's kernel, inside _baking."""
    ob = bpy.data.objects[obj_name]
    me = ob.data
    vl = bpy.context.view_layer
    for o in vl.objects:
        o.select_set(False)
    ob.select_set(True)
    vl.objects.active = ob
    parts = list(ob['parts'])
    pa = me.attributes['part'].data
    part_of = [parts[pa[p.vertices[0]].value] for p in me.polygons]
    faces_of = {}
    for i, pn in enumerate(part_of):
        if pn in own:
            faces_of.setdefault(own[pn], []).append(i)
    outside = {m: faces_of[m] for m in own_materials(own) if m in faces_of}
    sunk = {i for faces in outside.values() for i in faces}
    base = image_levels(frozen_image)
    h, w = base.shape[:2]
    result, per = base, {}
    if specs:
        layer = bpy.data.images.new(obj_name + '_Layer', w, h, alpha=True)
        sink = bpy.data.images.get(obj_name + '_Sink') or bpy.data.images.new(obj_name + '_Sink', 64, 64)
        me.materials.clear()
        me.materials.append(_albedo_material(obj_name + '_BakeLayer', layer, None))
        me.materials.append(_albedo_material(obj_name + '_BakeSink', sink, None))
        scene = bpy.context.scene
        prev = scene.render.engine
        scene.render.engine = 'CYCLES'
        scene.cycles.device = 'CPU'; scene.cycles.samples = 1
        scene.render.bake.margin = 0
        clear = np.zeros(w * h * 4, np.float32)
        try:
            layer.pixels.foreach_set(clear)
            for p in me.polygons:
                p.material_index = 1 if p.index in sunk else 0
            with bpy.context.temp_override(active_object=ob, object=ob, selected_objects=[ob]):
                bpy.ops.object.bake(type='EMIT', use_clear=False)
            inside = image_levels(layer.name)[..., 3] > 127
            for spec in specs:
                src = spec['object']
                det = bpy.data.objects[src]
                mask = None if spec['mask'] is None else set(spec['mask'])
                for p, pn in zip(me.polygons, part_of):
                    p.material_index = 0 if (mask is None or pn in mask) and p.index not in sunk else 1
                det.hide_set(False); det.hide_render = False
                det.data.materials.clear()
                det.data.materials.append(_albedo_material(src + '_BakeAlbedo', layer, grit))
                layer.pixels.foreach_set(clear)
                with bpy.context.temp_override(active_object=ob, object=ob, selected_objects=[ob, det]):
                    bpy.ops.object.bake(type='EMIT', use_clear=False, use_selected_to_active=True,
                                        cage_extrusion=spec['cage'], max_ray_distance=spec['ray'])
                det.hide_set(True); det.hide_render = True
                got = image_levels(layer.name)
                result, per[src] = imaging.composite_layer(result, got, got[..., 3] > 127, inside, margin)
        finally:
            scene.render.engine = prev
            for p in me.polygons:
                p.material_index = 0
    img = write_image(name, result)
    me.materials.clear()
    me.materials.append(_final_material(name, img, material))
    kept = {m: bpy.data.materials.get(m) is not None for m in outside}
    placed = _place_own(me, outside, kept, material)
    if save_dir:
        _save(img, save_dir)
    return {'frozen': frozen_image, 'size': [int(w), int(h)], 'sources': per,
            'changed': int((result != base).any(axis=2).sum()),
            'reach': {spec['object']: source_reach(obj_name, spec, part_of) for spec in specs}, 'own': placed}


# -- the UVs of mesh edits under a frozen texture -------------------------------------------------------------

def uv_arrays(obj_name):
    """(the mesh arrays of the body `obj_name` (lpk.stages.zones.read, after object_mode) with 'uv': its
    UV_LAYER as (L, 2) float64, the part name of each polygon: its first corner's, the rule the bake masks
    by). Raises ValueError when the body has no UV_LAYER or no part layer."""
    from lpk.core import builder
    ob = bpy.data.objects[obj_name]
    zones.object_mode(ob)
    A = zones.read(ob.data)
    uv = zones.read_uv(ob.data, UV_LAYER)
    if uv is None:
        raise ValueError('%s has no atlas UV layer %s' % (obj_name, UV_LAYER))
    if A['part'] is None:
        raise ValueError('%s has no part layer' % obj_name)
    A['uv'] = uv.astype(np.float64)
    names = list(ob['parts'])
    part_of = [names[A['part'][p[0]]] if p else '' for p in A['polys']]
    A['min_area'] = builder.DEGENERATE_M2
    return A, part_of


def uv_check(obj_name, size, own=()):
    """The UV check of the body `obj_name` on an atlas of `size` ((width, height) texels): per part the
    faces whose atlas UVs (UV_LAYER) are broken and why (lpk.stages.zones.uv_faults: no UV area, a corner
    outside the atlas, an overlap with a larger island of another part, a texel density far from the
    neighbours'), the parts of `own` (outside the atlas) and faces under lpk.core.builder.DEGENERATE_M2 left
    out. A face's part is its first corner's. It reads, it changes nothing. Returns
    lpk.stages.zones.uv_report's report; face ids are the body's polygons."""
    A, part_of = uv_arrays(obj_name)
    faults = zones.uv_faults(A['co'], A['loop_start'], A['loop_total'], A['loop_vert'], A['uv'], part_of, size,
                             skip=set(own or ()), min_area=A['min_area'])
    return zones.uv_report(faults, part_of, size)


def repair_uvs(obj_name, frozen_image, atlas_image=None, sources=(), colours=None, own=None, grit=None, parts=None,
               margin=BAKE_MARGIN, save_dir=None):
    """The broken UVs of the body `obj_name` under a frozen texture repaired: the faces the UV check lists
    (uv_check at the size of `frozen_image`; only those of the parts `parts` when given) get new islands in
    free atlas space, are baked into the frozen atlas, and nothing else of the UVs or the atlas changes.

    The free space is the atlas less every other face's texels (lpk.stages.imaging.uv_raster, the `own`
    parts left out, as they lie outside the atlas) grown by `margin` texels, the ring their bake margin
    fills; no existing island moves. The faces are laid out by lpk.stages.zones.uv_repair_layout at their
    part's texels per metre (lpk.stages.zones.part_densities), each chart in a cell with a ring of `margin`
    texels. When a chart finds no place nothing is changed. Else the new UVs are written on the body and
    the faces are baked, as bake_over bakes a source, into transparent layers with every other face baking
    into a throwaway image: first their palette colours (Col, recoloured from `colours` when given, with
    the grit `grit`), then each colour source of `sources` within its mask in bake order, each composited
    over the frozen image's levels on the texels it hit and in a bake margin of `margin` texels round them
    outside the new islands, within the cells (lpk.stages.imaging.composite_layer). The result replaces
    `frozen_image` (store_levels); the image `atlas_image`, when given and present, takes the same texels
    in place, so its link in the body's material stays, is stamped (stamp_image) and saved as
    <save_dir>/<its name>.png unless save_dir is None. Every texel outside
    the cells keeps its levels in both images. The body's materials and their face indices are put back as
    found. Storing the UVs on the frozen mesh and stamping the body is the caller's.

    sources, colours, own, grit: as bake's (own: {part: material name}); parts: part names, or None for
    every part; margin: texels. Raises ValueError
    for a missing frozen image, a source without an object, and what recolour raises, before anything
    changes.

    Returns {'before': uv_check's report, 'faces': {part: the faces repaired}, 'charts': uv_repair_layout's
    charts, 'placed': whether every chart found a place (False: nothing changed), 'texels_per_m': {part:
    the density laid out at, rounded to 0.1}, 'cells': texels the placed cells hold, 'changed': texels of
    the frozen image whose levels changed, 'sources': {source object: composite_layer's counts},
    'recoloured': recolour's {object: corners}, 'files': [the atlas PNG's path] when it was saved, and when
    every chart was placed 'after': uv_check's report on the new UVs}."""
    if bpy.data.images.get(frozen_image) is None:
        raise ValueError('no frozen atlas %s in the open .blend: run freeze_texture (or adopt a textured model) '
                         'first' % frozen_image)
    specs = source_specs(sources)
    own = own or {}
    base = image_levels(frozen_image)
    h, w = base.shape[:2]
    size = (w, h)
    A, part_of = uv_arrays(obj_name)
    args = (A['co'], A['loop_start'], A['loop_total'], A['loop_vert'])
    faults = zones.uv_faults(*args, A['uv'], part_of, size, skip=set(own), min_area=A['min_area'])
    before = zones.uv_report(faults, part_of, size)
    broken = [f for f in np.flatnonzero(faults['broken']).tolist() if parts is None or part_of[f] in parts]
    out = {'before': before, 'faces': {}, 'charts': [], 'placed': True, 'texels_per_m': {}, 'cells': 0,
           'changed': 0, 'sources': {}, 'recoloured': {}, 'files': []}
    for f in broken:
        out['faces'].setdefault(part_of[f], []).append(f)
    if not broken:
        out['after'] = before
        return out
    densities = zones.part_densities(faults, part_of, broken)
    out['texels_per_m'] = {k: round(v, 1) for k, v in densities.items()}
    keep = np.ones(len(part_of), bool)
    keep[broken] = False
    keep &= np.array([p not in own for p in part_of], bool)
    occupied = imaging.uv_raster(faults['tris'][keep[faults['tri_face']]], (h, w))
    for _ in range(int(margin)):
        occupied = imaging.grown(occupied)
    layout = zones.uv_repair_layout(*args, broken, part_of, densities, occupied, size, margin)
    out['charts'], out['placed'] = layout['charts'], layout['placed']
    if not layout['placed']:
        return out
    cells = layout['cells']
    out['recoloured'] = {} if colours is None else recolour([obj_name] + [s['object'] for s in specs], colours)
    ob = bpy.data.objects[obj_name]
    me = ob.data
    uv = A['uv'].copy()
    for f, q in layout['uv'].items():
        s0 = int(A['loop_start'][f])
        uv[s0:s0 + len(q)] = q
    me.uv_layers[UV_LAYER].uv.foreach_set('vector', uv.astype(np.float32).ravel())
    me.update()
    working = {'images': [obj_name + '_Layer', obj_name + '_Sink'],
               'materials': [obj_name + '_BakeLayer', obj_name + '_BakeSink']
               + [spec['object'] + '_BakeAlbedo' for spec in specs]}
    with _baking(obj_name, specs, working):
        result, per = _repair_bake(obj_name, base, set(broken), part_of, specs, own, grit, margin, cells)
    store_levels(frozen_image, result)
    atlas = None if atlas_image is None else bpy.data.images.get(atlas_image)
    if atlas is not None and tuple(atlas.size) == (w, h):
        levels = image_levels(atlas_image)
        levels[cells] = result[cells]
        atlas.pixels.foreach_set((levels.astype(np.float32) / 255.0).ravel())
        atlas.update()
        stamp_image(atlas_image)
        if save_dir is not None:
            os.makedirs(str(save_dir), exist_ok=True)
            _save(atlas, str(save_dir))
            out['files'] = [atlas.filepath_raw]
    out['cells'] = int(cells.sum())
    out['changed'] = int((result != base).any(axis=2).sum())
    out['sources'] = per
    out['after'] = uv_check(obj_name, size, own)
    return out


def _repair_bake(obj_name, base, faces, part_of, specs, own, grit, margin, cells):
    """repair_uvs' bake, inside _baking: (the frozen levels `base` with the faces `faces` baked into the
    texels of `cells`, {source object: composite_layer's counts}). The body's materials and face indices are
    put back afterwards, also after an error."""
    ob = bpy.data.objects[obj_name]
    me = ob.data
    vl = bpy.context.view_layer
    for o in vl.objects:
        o.select_set(False)
    ob.select_set(True)
    vl.objects.active = ob
    h, w = base.shape[:2]
    kept_materials = list(me.materials)
    kept_index = [p.material_index for p in me.polygons]
    layer = bpy.data.images.new(obj_name + '_Layer', w, h, alpha=True)
    sink = bpy.data.images.get(obj_name + '_Sink') or bpy.data.images.new(obj_name + '_Sink', 64, 64)
    scene = bpy.context.scene
    prev = scene.render.engine
    clear = np.zeros(w * h * 4, np.float32)
    per = {}
    try:
        me.materials.clear()
        me.materials.append(_albedo_material(obj_name + '_BakeLayer', layer, grit))
        me.materials.append(_albedo_material(obj_name + '_BakeSink', sink, grit))
        scene.render.engine = 'CYCLES'
        scene.cycles.device = 'CPU'; scene.cycles.samples = 1
        scene.render.bake.margin = 0
        for p in me.polygons:
            p.material_index = 0 if p.index in faces else 1
        layer.pixels.foreach_set(clear)
        with bpy.context.temp_override(active_object=ob, object=ob, selected_objects=[ob]):
            bpy.ops.object.bake(type='EMIT', use_clear=False)
        got = image_levels(layer.name)
        hit = (got[..., 3] > 127) & cells
        inside = hit | ~cells
        result, _ = imaging.composite_layer(base, got, hit, inside, margin)
        for spec in specs:
            src = spec['object']
            det = bpy.data.objects[src]
            mask = None if spec['mask'] is None else set(spec['mask'])
            for p, pn in zip(me.polygons, part_of):
                p.material_index = 0 if p.index in faces and (mask is None or pn in mask) else 1
            det.hide_set(False); det.hide_render = False
            det.data.materials.clear()
            det.data.materials.append(_albedo_material(src + '_BakeAlbedo', layer, grit))
            layer.pixels.foreach_set(clear)
            with bpy.context.temp_override(active_object=ob, object=ob, selected_objects=[ob, det]):
                bpy.ops.object.bake(type='EMIT', use_clear=False, use_selected_to_active=True,
                                    cage_extrusion=spec['cage'], max_ray_distance=spec['ray'])
            det.hide_set(True); det.hide_render = True
            got = image_levels(layer.name)
            result, per[src] = imaging.composite_layer(result, got, (got[..., 3] > 127) & cells, inside, margin)
    finally:
        scene.render.engine = prev
        me.materials.clear()
        for m in kept_materials:
            me.materials.append(m)
        for p, i in zip(me.polygons, kept_index):
            p.material_index = i
    return result, per
