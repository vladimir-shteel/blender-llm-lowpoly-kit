"""Procedural low-poly mesh builder.

Every face carries a palette index (face attribute `pal`) and every vertex a part index (point attribute
`part`); later stages derive vertex colours, texture sheets and skin weights from them. Part index 0 is
reserved: `parts[0]` is '' and no vertex carries it, so geometry nobody attributed never passes for a part.

Builder.loft lays its rings with the section arithmetic and the frame transport of lpk.core.sections
(section_factors through ring_points, loft_frames): one kernel for the blocks and the detailed build.
"""
import bpy, bmesh, math
from mathutils import Vector, Matrix

from lpk.core.sections import loft_frames, ring_points, section_points


def srgb_to_linear(c):
    f = lambda x: x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4
    return tuple(f(v) for v in c) + (1.0,)


def _options(opts):
    o = opts if opts else {}
    return o if isinstance(o, dict) else {'mult': o}


def loft_section(ra, rb, n, opts=None):
    """The n vertices of one Builder.loft section as (x, y) offsets from its centre in metres, x along
    the ring's a axis and y along its b axis, in vertex order, with every option of the ring applied
    (opts as Builder.loft takes it, 'off' excepted: it moves the centre, not the vertices). For a
    profile_loft or snout_head section a is across (+X) and b is up, so (x, y) is the section as the
    front view sees it. It is lpk.core.sections.section_points, the arithmetic Builder.loft lays its vertices
    with: a vertex on an axis of the ring's frame has exact zero and unit components. Builder.loft
    stores the positions in single precision, so the two agree to float32 rounding."""
    return section_points(ra, rb, n, _options(opts))


def _finite_direction(value, what):
    v = tuple(float(x) for x in value)
    if len(v) != 3 or not all(math.isfinite(x) for x in v) or not any(v):
        raise ValueError('loft section %s must be a finite, nonzero direction (got %r)' % (what, value))
    return v


def loft_points(rings, n, ref, axis=None):
    """The ring vertices Builder.loft lays for `rings`, `n`, `ref` and `axis` (as it takes them), without a
    builder: (frames, points), frames [(normal, a)] per ring (lpk.core.sections.loft_frames), points one
    list of n (x, y, z) positions in metres per ring, in vertex order (lpk.core.sections.ring_points).
    Builder.loft lays its vertices from these and stores them in single precision, so the two agree to
    float32 rounding. Raises what Builder.loft raises for malformed rings."""
    centres = [tuple(float(c) for c in r[0]) for r in rings]
    options = [_options(r[3] if len(r) > 3 else None) for r in rings]
    frames = loft_frames(centres, _finite_direction(ref, 'ref'),
                         axis=None if axis is None else _finite_direction(axis, 'axis'),
                         normals=[_finite_direction(o['axis'], 'axis') if 'axis' in o else None for o in options],
                         refs=[_finite_direction(o['ref'], 'ref') if 'ref' in o else None for o in options])
    points = [ring_points(centre, normal, a, r[1], r[2], n, o)
              for (centre, (normal, a)), r, o in zip(zip(centres, frames), rings, options)]
    return frames, points


class Builder:
    def __init__(self, palette, vert_layers=()):
        """palette: {name: sRGB tuple}; its order fixes the face palette indices. vert_layers: extra int
        vertex layers (e.g. 'join_loop'), created here because a layer added after the first vertex
        invalidates every vertex reference held so far.

        Attributes besides the layers: parts, the part names by index ('' at index 0, reserved); mirrored,
        the (src, dst) pairs mirror_part has copied."""
        self.palette = palette            # {name: sRGB tuple}
        self.keys = list(palette)
        self.bm = bmesh.new()
        self.fpal = self.bm.faces.layers.int.new('pal')
        self.vpart = self.bm.verts.layers.int.new('part')
        for name in vert_layers:
            self.bm.verts.layers.int.new(name)
        self.parts = ['']
        self.mirrored = []                # (src, dst) pairs mirror_part has copied, in call order

    def pid(self, name):
        """The index of part `name`, registering a new name at the end of `parts`. Raises ValueError for
        '' (index 0 is reserved for unattributed geometry) and for a name that is not a string."""
        if not isinstance(name, str) or not name:
            raise ValueError('a part needs a non-empty name (got %r): part index 0 is reserved' % (name,))
        if name not in self.parts:
            self.parts.append(name)
        return self.parts.index(name)

    def vert(self, co, pid):
        """A new vertex at `co` (metres) of the part with index `pid`. Raises ValueError for pid 0
        (reserved)."""
        if not pid:
            raise ValueError('part index 0 is reserved for unattributed geometry; take the index from pid(name)')
        v = self.bm.verts.new(Vector(co))
        v[self.vpart] = pid
        return v

    def face(self, verts, col, hint=None):
        """A new face over `verts` with the palette colour `col` (a palette name). hint: a point inside the
        volume; the face is flipped to point away from it."""
        f = self.bm.faces.new(verts)
        f[self.fpal] = self.keys.index(col)
        if hint is not None:
            f.normal_update()
            if f.normal.dot(f.calc_center_median() - Vector(hint)) < 0:
                f.normal_flip()
        return f

    def loft(self, part, rings, n, ref, color, cap0=None, cap1=None, col0=None, col1=None, axis=None):
        """Tube through cross-section rings.

        rings: [(center, ra, rb[, opts])]. a starts as `ref` projected off the path and
        is parallel-transported along it; b = t x a, t the path direction. ra sizes the section
        along a, rb along b, and vertex j sits at pi / n + 2 pi j / n from a toward b. A path down
        -Z with ref = X gives a = +X and b = -Y (the front); a path along -Y with ref = Z gives
        a = +Z (ra is the height) and b = -X.
        opts: a list of per-vertex radius multipliers, or a dict with
          'mult'   per-vertex radius multipliers, one per side,
          'p'      superellipse exponent (2 = ellipse, 3-4 = rounded box),
          'ra_neg' / 'rb_neg'  radius on the -a / -b side (asymmetric sections),
          'ra_bneg'  the a radius of the vertices on the -b half (sin < 0), on both a sides, where
                   ra and ra_neg then hold for the +b half only: with b up, as in
                   shapes.profile_loft, the half width below the section's mid-height (a jaw narrower
                   than the cheeks); the side between the two halves slants from one to the other,
          'off'    (da, db) offset of the ring centre in its own frame,
          'axis' / 'ref' the ring's own normal and reference, which replace the path direction and
                   the transported a there (lpk.core.sections.loft_rings and profile_rings give
                   every ring both, so the detailed loft has exactly the kernel's frames).
        With p == 2 ra/rb are apothems (distance to the flat sides); otherwise they are
        the superellipse extents. A vertex on an axis of the ring's frame lies exactly on it.
        loft_section gives a section's vertices without a builder, loft_points every ring's.
        The frames come from lpk.core.sections.loft_frames, which refuses (SectionError, a ValueError)
        a ring without a path direction (its neighbours share a centre and no axis is given),
        consecutive normals that reverse, a step that runs backward against its normals, and rings
        that never advance along their normals; a malformed axis or ref, or a 'mult' of another
        length than n, raises ValueError.
        color: palette name, or fn(i, j, d) returning one for each side face: i the band from ring i
        to ring i + 1 (0 to len(rings) - 2), j the column, the face from vertex j to vertex j + 1 (0 to
        n - 1, from a toward b), d the column's nominal outward direction at ring i, the unit vector
        at the face's middle angle in that ring's plane: across the path, never along it, and not the
        face's normal.
        cap0/cap1: None, 'flat', or an apex point for a cone. col0/col1: the colour of the cap on
        the first / last ring. A cap, flat or apex, takes one colour for all its faces: col0 / col1,
        else color(0, 0, d) / color(len(rings) - 2, 0, d), the colour the first / last band gives
        its column 0, whatever way the cap faces.
        axis: fixed ring normal for every ring. By default each ring is perpendicular to the
        path through its neighbours' centres, so shifting centres sideways (a snout dropped
        below the cranium) tilts the rings; pass an axis to keep sections parallel.

        Side winding (ring j -> j+1 -> next ring) is outward by construction because
        b = t x a, so no normal fix-up is needed, including on step rings.
        """
        pid = self.pid(part)
        k = len(rings)
        frames, points = loft_points(rings, n, ref, axis)
        ph = math.pi / n
        R = [[self.vert(p, pid) for p in ring] for ring in points]

        def col_of(i, j):
            if not callable(color):
                return color
            th = ph + 2 * math.pi * (j + 0.5) / n
            normal, a = frames[min(i, k - 1)]
            a = Vector(a); b = Vector(normal).cross(a)
            return color(i, j, (a * math.cos(th) + b * math.sin(th)).normalized())
        for i in range(k - 1):
            for j in range(n):
                self.face([R[i][j], R[i][(j + 1) % n], R[i + 1][(j + 1) % n], R[i + 1][j]], col_of(i, j))
        c0 = col0 or col_of(0, 0)
        c1 = col1 or col_of(k - 2, 0)
        if cap0 == 'flat':
            self.face(list(reversed(R[0])), c0)
        elif cap0 is not None:
            p = self.vert(cap0, pid)
            for j in range(n):
                self.face([R[0][(j + 1) % n], R[0][j], p], c0)
        if cap1 == 'flat':
            self.face(R[-1], c1)
        elif cap1 is not None:
            p = self.vert(cap1, pid)
            for j in range(n):
                self.face([R[-1][j], R[-1][(j + 1) % n], p], c1)
        return R

    def pyramid(self, part, base, apex, col, cap=False):
        """Open-based pyramid (base hidden inside another part unless cap=True).
        col: palette name or fn(side index, -1 for the cap)."""
        pid = self.pid(part)
        bv = [self.vert(p, pid) for p in base]
        av = self.vert(apex, pid)
        hint = (sum((Vector(p) for p in base), Vector()) / len(base) + Vector(apex)) / 2
        for j in range(len(bv)):
            self.face([bv[j], bv[(j + 1) % len(bv)], av], col(j) if callable(col) else col, hint)
        if cap:
            self.face(bv, col(-1) if callable(col) else col, hint)

    def box(self, part, center, half, rot, col):
        """col: palette name or fn(side) with side in '-x', '+x', '-y', '+y', '-z', '+z'."""
        pid = self.pid(part)
        c = Vector(center); m = rot.to_3x3() if rot else Matrix.Identity(3)
        hx, hy, hz = half
        vs = {}
        for ix in (-1, 1):
            for iy in (-1, 1):
                for iz in (-1, 1):
                    vs[ix, iy, iz] = self.vert(c + m @ Vector((ix * hx, iy * hy, iz * hz)), pid)
        quads = [((-1, -1, -1), (-1, 1, -1), (-1, 1, 1), (-1, -1, 1)), ((1, -1, -1), (1, 1, -1), (1, 1, 1), (1, -1, 1)),
                 ((-1, -1, -1), (1, -1, -1), (1, -1, 1), (-1, -1, 1)), ((-1, 1, -1), (1, 1, -1), (1, 1, 1), (-1, 1, 1)),
                 ((-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1)), ((-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1))]
        for q, side in zip(quads, ['-x', '+x', '-y', '+y', '-z', '+z']):
            self.face([vs[k] for k in q], col(side) if callable(col) else col, c)

    def decal(self, part, pts, col, normal):
        """Single floating polygon facing `normal`; offset it off the surface by a few mm."""
        pid = self.pid(part)
        f = self.face([self.vert(p, pid) for p in pts], col)
        f.normal_update()
        if f.normal.dot(Vector(normal)) < 0:
            f.normal_flip()

    def mirror_part(self, src, dst):
        """Copy part `src` mirrored through X = 0 into part `dst`. Paired parts built this way
        are exact mirror images; building each side separately is not, because an odd-sided
        section (a 3-sided finger) does not mirror with its side's ring frame. Several sources may
        mirror into one part, but a pair copied a second time raises ValueError: the copy would
        overlay the first one. Returns {source vertex: its mirrored copy}."""
        if (src, dst) in self.mirrored:
            raise ValueError('mirror_part(%r, %r) already ran on this builder; a second copy would overlay the '
                             'first: mirror the source once it is complete, and mirror what is added to it later '
                             'from a part of its own' % (src, dst))
        self.mirrored.append((src, dst))
        sid, did = self.pid(src), self.pid(dst)
        self.bm.verts.ensure_lookup_table()
        faces = [f for f in self.bm.faces if f.verts[0][self.vpart] == sid]
        return self._mirror_faces(faces, did)

    def _mirror_faces(self, faces, pid):
        """Copy `faces` mirrored through X = 0 into the part with id `pid`: each of their vertices once,
        in the order the faces reach them, then each face with its vertices reversed (the mirror flips
        the winding) and its palette index. An exact mirror image for any section. Returns {source
        vertex: its mirrored copy}."""
        copy = {}
        for f in faces:
            for v in f.verts:
                if v not in copy:
                    copy[v] = self.vert((-v.co.x, v.co.y, v.co.z), pid)
        for f in faces:
            nf = self.bm.faces.new([copy[v] for v in reversed(f.verts)])
            nf[self.fpal] = f[self.fpal]
        return copy

    def scale_part(self, part, pivot, factor):
        pid = self.pid(part); pivot = Vector(pivot)
        for v in self.bm.verts:
            if v[self.vpart] == pid:
                v.co = pivot + (v.co - pivot) * factor

    def _verts_of(self, part, call):
        """The vertices of part `part`, in the mesh's order. Raises ValueError when it has none (a part
        not built yet, or a misspelt name): `call` would move nothing."""
        pid = self.parts.index(part) if part in self.parts else None
        verts = [v for v in self.bm.verts if v[self.vpart] == pid] if pid is not None else []
        if not verts:
            raise ValueError('%s(%r): the part has no vertices to move; the builder holds the parts %s'
                             % (call, part, ', '.join(repr(p) for p in self.parts[1:]) or 'none'))
        return verts

    def move_part(self, part, offset):
        """Move every vertex of part `part` by `offset`, (x, y, z) in metres: a form that builds at a
        fixed place (an ankle at y = 0) set where the model needs it. Only that part's vertices move: on
        a part welded to another, the faces they share stretch across the join. Raises ValueError for a
        part without vertices."""
        off = Vector(offset)
        for v in self._verts_of(part, 'move_part'):
            v.co = v.co + off

    def ground_part(self, part, z=0.0):
        """Move part `part` straight up or down so that its lowest vertex sits at height `z` (metres; 0
        is the floor), and return the shift in metres (positive: moved up). It reads the part's
        vertices each time it runs, so it follows every change of the part's shape, where a constant
        typed back from floor.lowest stops matching once the shape changes. Call it after the part's
        last shaping step and before Builder.mirror_part copies it, so the copy stands on the floor
        too. Only that part's vertices move: on a part welded to another, the faces they share stretch
        across the join. Raises ValueError for a part without vertices."""
        verts = self._verts_of(part, 'ground_part')
        dz = z - min(v.co.z for v in verts)
        for v in verts:
            v.co.z += dz
        return dz


# The area (m^2) under which finish reports a triangle as degenerate: a 10 by 20 micrometre sliver, far
# below anything a capture or a 512 atlas resolves, where the triangle's normal and UV area are float32
# rounding of its positions (a collapsed weld, a cap on coincident points) rather than surface.
DEGENERATE_M2 = 1e-10


def degenerate_faces(b):
    """{part: faces of the builder `b` whose area is under DEGENERATE_M2}, each face counted for the part of
    its first vertex (finish's by_part rule), in the order the faces first reach each part; {} when none.
    finish reads it after triangulating, so it counts triangles."""
    out = {}
    for f in b.bm.faces:
        if f.calc_area() < DEGENERATE_M2:
            nm = b.parts[f.verts[0][b.vpart]]
            out[nm] = out.get(nm, 0) + 1
    return out


def finish(b, name, collection, location=(0, 0, 0), *, colours=None):
    """Triangulate, replace any object called `name` in the scene, link the new object into the
    collection `collection` (created when missing), add the `Col` corner colour attribute from the face
    palette (paint_corners), and report triangle counts per part. location: the object's location
    (metres). colours: {palette name: sRGB} the `Col` attribute takes, by default the builder's palette; a
    palette name without a colour raises ValueError before the scene changes. The object's 'parts'
    property lists the part names by index, '' (reserved, on no vertex) first, and 'palette' the palette
    names by face index. The builder's mesh is freed: the builder makes no more geometry. Returns (the
    object, body_report's report with the builder's degenerate_faces). A degenerate triangle is reported,
    not removed: it keeps the vertex order, and the unwrap and the bake take it as a face of no area."""
    palette = b.palette if colours is None else colours
    missing = [k for k in b.keys if palette.get(k) is None]
    if missing:
        raise ValueError('finish(%r): no colour for the palette names %s' % (name, ', '.join(missing)))
    bmesh.ops.triangulate(b.bm, faces=b.bm.faces[:], quad_method='BEAUTY', ngon_method='EAR_CLIP')
    degenerate = degenerate_faces(b)
    me = bpy.data.meshes.new(name)
    b.bm.to_mesh(me); b.bm.free()
    ob = replace_object(name, me, collection, location)
    paint_corners(me, b.keys, palette)
    ob['parts'] = list(b.parts)
    ob['palette'] = list(b.keys)
    return ob, body_report(ob, list(b.parts), degenerate)


def replace_object(name, me, collection, location=(0, 0, 0)):
    """A new object `name` over the mesh `me`, linked into the collection `collection` (created and linked
    to the scene when missing; one anywhere in the scene's collection tree, a child collection included,
    stays where it is) at `location` (metres), after removing every object called `name` and every mesh
    called `name` without users. A mesh `me` that lost the name to a mesh still in use keeps Blender's
    numbered name. Returns the object."""
    for o in [o for o in bpy.data.objects if o.name == name]:
        bpy.data.objects.remove(o, do_unlink=True)
        bpy.context.view_layer.update()  # a removed object stays as None in view_layer.objects until an update
    for m in [m for m in bpy.data.meshes if m.name == name and m.users == 0 and m != me]:
        bpy.data.meshes.remove(m)
    me.name = name
    coll = bpy.data.collections.get(collection) or bpy.data.collections.new(collection)
    if coll not in list(bpy.context.scene.collection.children_recursive):
        bpy.context.scene.collection.children.link(coll)
    ob = bpy.data.objects.new(name, me)
    ob.location = location
    coll.objects.link(ob)
    return ob


def hidden_collection(name, parent):
    """The collection `name` as a child of the collection `parent` (each created when missing, `parent`
    linked to the scene when it is in no collection of the scene's tree), excluded from the active view
    layer, so the objects in it are kept in the .blend but neither shown, selectable nor in that view
    layer's object list. A collection `name` elsewhere in the scene's tree is moved under `parent`. An
    excluded object cannot be hidden, selected or baked: a tool that needs it includes the collection for
    the call (lpk.stages.texture.bake does). Returns the collection."""
    scene = bpy.context.scene
    top = bpy.data.collections.get(parent) or bpy.data.collections.new(parent)
    if top not in list(scene.collection.children_recursive):
        scene.collection.children.link(top)
    coll = bpy.data.collections.get(name) or bpy.data.collections.new(name)
    for holder in [scene.collection] + list(scene.collection.children_recursive):
        if holder != top and coll.name in holder.children:
            holder.children.unlink(coll)
    if coll.name not in top.children:
        top.children.link(coll)
    layer = layer_collection(bpy.context.view_layer.layer_collection, coll)
    if layer is not None:
        layer.exclude = True
    return coll


def layer_collection(layer, coll):
    """The layer collection of the collection `coll` under the layer collection `layer` (a view layer's
    layer_collection), searched depth first in child order; None when it is not there."""
    if layer.collection == coll:
        return layer
    for child in layer.children:
        found = layer_collection(child, coll)
        if found is not None:
            return found
    return None


def paint_corners(me, keys, colours):
    """The `Col` corner colour attribute of the mesh `me` (replaced when present, made the active colour)
    from its face attribute `pal`: every corner of a face takes the linear colour of colours[keys[pal]].
    keys: the palette names by face index; colours: {name: sRGB}. Raises ValueError naming the palette
    names colours lacks, and a face index outside keys, before the mesh changes."""
    missing = [k for k in keys if colours.get(k) is None]
    if missing:
        raise ValueError('mesh %r: no colour for the palette names %s' % (me.name, ', '.join(missing)))
    lins = [srgb_to_linear(colours[k]) for k in keys]
    pal = me.attributes['pal'].data
    bad = sorted({pal[p.index].value for p in me.polygons} - set(range(len(keys))))
    if bad:
        raise ValueError('mesh %r: faces carry palette indices %s outside its %d palette names'
                         % (me.name, bad, len(keys)))
    old = me.color_attributes.get('Col')
    if old is not None:
        me.color_attributes.remove(old)
    col = me.color_attributes.new('Col', 'FLOAT_COLOR', 'CORNER')
    for p in me.polygons:
        c = lins[pal[p.index].value]
        for li in p.loop_indices:
            col.data[li].color = c
    me.color_attributes.active_color = col


def degenerate_polygons(me, parts):
    """{part: polygons of the mesh `me` whose area is under DEGENERATE_M2}, each counted for the part of its
    first vertex, in the order the polygons first reach each part; {} when none: degenerate_faces' rule
    on a written mesh. parts: the part names by index."""
    out = {}
    pa = me.attributes['part'].data
    for p in me.polygons:
        if p.area < DEGENERATE_M2:
            nm = parts[pa[p.vertices[0]].value]
            out[nm] = out.get(nm, 0) + 1
    return out


def body_report(ob, parts, degenerate):
    """finish's report of a written body object `ob` (its mesh with the `part` attribute): {'tris': its
    triangles, 'verts': its vertices, 'by_part': {part: triangles, each counted for the part of its first
    vertex, so the faces of a join split between the joined parts by their vertex order and mirrored
    parts can differ by a few}, 'dims': its dimensions in metres, rounded to the millimetre, 'zmin':
    {part: its lowest vertex z in world metres (the object's location included), rounded to 0.1 mm, in
    part order}, 'ztop': {part: its highest vertex z, alike}, 'degenerate': `degenerate`, {part: its
    triangles under DEGENERATE_M2}}. parts: the part names by index."""
    me = ob.data
    location = ob.location
    by_part = {}
    pa = me.attributes['part'].data
    for p in me.polygons:
        nm = parts[pa[p.vertices[0]].value]
        by_part[nm] = by_part.get(nm, 0) + 1
    low, high = {}, {}
    for v in me.vertices:
        i = pa[v.index].value
        if i not in low or v.co.z < low[i]:
            low[i] = v.co.z
        if i not in high or v.co.z > high[i]:
            high[i] = v.co.z
    zmin = {nm: round(low[i] + location[2], 4) for i, nm in enumerate(parts) if i in low}
    ztop = {nm: round(high[i] + location[2], 4) for i, nm in enumerate(parts) if i in high}
    return {'tris': len(me.polygons), 'verts': len(me.vertices), 'by_part': by_part,
            'dims': [round(x, 3) for x in ob.dimensions], 'zmin': zmin, 'ztop': ztop,
            'degenerate': dict(degenerate)}


def lift_dark(palette, f=0.1):
    """Palette for in-shader shading (no baked cel lift): add f * (1 - V) in sRGB to every channel
    (V = the brightest channel), so near-blacks rise by ~f while light and saturated colours
    barely move and hues stay."""
    return {name: tuple(min(1.0, x + f * (1 - max(c))) for x in c) for name, c in palette.items()}
