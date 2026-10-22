"""Stand-ins for bpy, bmesh and mathutils that let host tests import and run the Blender-side kernels.

Vector is the part of mathutils.Vector the kernels touch; BMesh is bmesh.new(): vertex and face sequences in
creation order with int layers keyed by their names, faces that compute their normal, centre and area, edges
derived from the faces (one object per vertex pair, valid while a face uses it), and the bmesh.ops the
kernels call (triangulate fans a polygon from its first corner; weld_verts merges the mapped vertices into
their targets; delete removes faces, and with them the vertices they leave loose; rotate_edges turns the
edge between two triangles to their other diagonal). BVHTree.FromPolygons keeps its polygons and answers
ray_cast and find_nearest over their fan triangles by brute force; mathutils.geometry holds
intersect_point_tri. stand_ins() installs the modules, and lpk as a bare package over its folder, while a
block runs and puts sys.modules back afterwards. Not a test file: the test files import it."""
import contextlib
import math
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Vector:
    """The part of mathutils.Vector that Builder and the forms under test touch."""

    def __init__(self, seq=(0.0, 0.0, 0.0)):
        self.v = [float(c) for c in seq]

    x = property(lambda s: s.v[0], lambda s, a: s.v.__setitem__(0, float(a)))
    y = property(lambda s: s.v[1], lambda s, a: s.v.__setitem__(1, float(a)))
    z = property(lambda s: s.v[2], lambda s, a: s.v.__setitem__(2, float(a)))

    def __iter__(self):
        return iter(self.v)

    def __len__(self):
        return len(self.v)

    def __getitem__(self, i):
        return self.v[i]

    def __eq__(self, o):
        return list(self) == list(o)

    __hash__ = None

    def __repr__(self):
        return 'Vector(%r)' % (tuple(self.v),)

    def __add__(self, o):
        return Vector(a + b for a, b in zip(self, o))

    __radd__ = __add__

    def __sub__(self, o):
        return Vector(a - b for a, b in zip(self, o))

    def __rsub__(self, o):
        return Vector(b - a for a, b in zip(self, o))

    def __mul__(self, k):
        return Vector(a * k for a in self)

    __rmul__ = __mul__

    def __truediv__(self, k):
        return Vector(a / k for a in self)

    def __neg__(self):
        return self * -1.0

    def dot(self, o):
        return sum(a * b for a, b in zip(self, o))

    def cross(self, o):
        a, b = self.v, list(o)
        return Vector((a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]))

    @property
    def length(self):
        return math.sqrt(self.dot(self))

    def normalized(self):
        n = self.length
        return Vector(a / n for a in self) if n else Vector(self)

    def normalize(self):
        self.v = list(self.normalized())

    def copy(self):
        return Vector(self)

    def angle(self, o, fallback=None):
        n = self.length * Vector(o).length
        if not n:
            return fallback
        return math.acos(max(-1.0, min(1.0, self.dot(o) / n)))

    def rotation_difference(self, o):
        """The shortest rotation taking this direction to `o`, as a Rotation."""
        a, b = self.normalized(), Vector(o).normalized()
        axis = a.cross(b)
        s, c = axis.length, a.dot(b)
        return Rotation(axis.normalized() if s > 1e-12 else Vector((1.0, 0.0, 0.0)), math.atan2(s, c)
                        if s > 1e-12 else (0.0 if c > 0 else math.pi))


class Rotation:
    """A rotation by `angle` about the unit `axis`, applied to a vector with @ (Rodrigues' formula)."""

    def __init__(self, axis, angle):
        self.axis, self.angle = axis, angle

    def __matmul__(self, v):
        v = Vector(v)
        k, c, s = self.axis, math.cos(self.angle), math.sin(self.angle)
        return v * c + k.cross(v) * s + k * (k.dot(v) * (1 - c))


class Element:
    """A BMVert or BMFace: int layer values by layer key."""

    def __init__(self):
        self.layer_values = {}
        self.is_valid = True

    def __getitem__(self, layer):
        return self.layer_values.get(layer, 0)

    def __setitem__(self, layer, value):
        self.layer_values[layer] = value


class BMVert(Element):
    def __init__(self, co):
        super().__init__()
        self.co = Vector(co)
        self.link_faces = []
        self.edges_by_vert = {}
        self.index = -1

    @property
    def link_edges(self):
        """The edges of the faces using this vertex that end at it, in face order, each once."""
        out = []
        for f in self.link_faces:
            n = len(f.verts)
            i = f.verts.index(self)
            for other in (f.verts[i - 1], f.verts[(i + 1) % n]):
                e = edge(self, other)
                if e not in out:
                    out.append(e)
        return out


def _adjacent(f, a, b):
    """Whether a and b are consecutive corners of face f, in either direction."""
    n = len(f.verts)
    return any({f.verts[i], f.verts[(i + 1) % n]} == {a, b} for i in range(n))


class BMEdge:
    """An edge between two vertices: the one object for that pair (edge()), valid while a face uses it."""

    def __init__(self, a, b):
        self.verts = [a, b]
        self.index = -1

    def other_vert(self, v):
        return self.verts[1] if v is self.verts[0] else self.verts[0]

    @property
    def link_faces(self):
        a, b = self.verts
        return [f for f in a.link_faces if f.is_valid and _adjacent(f, a, b)]

    @property
    def is_valid(self):
        return bool(self.link_faces)


def edge(a, b):
    """The BMEdge of the vertices a and b, made on first use."""
    e = a.edges_by_vert.get(id(b))
    if e is None:
        e = a.edges_by_vert[id(b)] = b.edges_by_vert[id(a)] = BMEdge(a, b)
    return e


class BMFace(Element):
    def __init__(self, verts):
        super().__init__()
        self.verts = list(verts)
        if len(set(map(id, self.verts))) != len(self.verts):
            raise ValueError('a face uses a vertex twice')
        for v in self.verts:
            v.link_faces.append(self)

    @property
    def normal(self):
        """The unit normal by Newell's method, (0, 0, 0) for a face without area."""
        n = [0.0, 0.0, 0.0]
        for p, q in zip(self.verts, self.verts[1:] + self.verts[:1]):
            p, q = p.co, q.co
            n[0] += (p.y - q.y) * (p.z + q.z)
            n[1] += (p.z - q.z) * (p.x + q.x)
            n[2] += (p.x - q.x) * (p.y + q.y)
        return Vector(n).normalized()

    def normal_update(self):
        pass

    def normal_flip(self):
        self.verts.reverse()

    def calc_center_median(self):
        return sum((v.co for v in self.verts), Vector()) / len(self.verts)

    def calc_area(self):
        c = self.calc_center_median()
        return sum((p.co - c).cross(q.co - c).length / 2
                   for p, q in zip(self.verts, self.verts[1:] + self.verts[:1]))

    @property
    def edges(self):
        n = len(self.verts)
        return [edge(self.verts[i], self.verts[(i + 1) % n]) for i in range(n)]


class IntLayers(dict):
    def new(self, name):
        self[name] = name
        return name

    def remove(self, layer):
        del self[layer]


class Seq(list):
    def __init__(self, make):
        super().__init__()
        self.make = make
        self.layers = types.SimpleNamespace(int=IntLayers())

    def new(self, arg):
        e = self.make(arg)
        self.append(e)
        return e

    def ensure_lookup_table(self):
        pass

    def index_update(self):
        for i, e in enumerate(self):
            e.index = i


class EdgeSeq:
    """bm.edges: the edges of the valid faces, in face order, each once."""

    def __init__(self, bm):
        self.bm = bm

    def __iter__(self):
        seen = set()
        for f in self.bm.faces:
            for e in f.edges:
                if id(e) not in seen:
                    seen.add(id(e))
                    yield e

    def __len__(self):
        return sum(1 for _ in self)

    def index_update(self):
        for i, e in enumerate(self):
            e.index = i

    def ensure_lookup_table(self):
        pass


class BMesh:
    """bmesh.new(): vertex and face sequences in creation order, with int layers keyed by their names."""

    def __init__(self):
        self.verts, self.faces = Seq(BMVert), Seq(BMFace)
        self.is_valid = True

    @property
    def edges(self):
        return EdgeSeq(self)

    def free(self):
        self.is_valid = False

    def normal_update(self):
        pass

    def from_mesh(self, me):
        """bmesh.from_mesh over a scene_stand_ins mesh: its vertices and polygons in order, its int POINT and
        FACE attributes as layers of those names."""
        verts = [self.verts.new(v.co) for v in me.vertices]
        faces = [self.faces.new([verts[i] for i in p.vertices]) for p in me.polygons]
        for name, attr in me.attributes.items():
            elements, seq = (verts, self.verts) if attr.domain == 'POINT' else (faces, self.faces)
            layer = seq.layers.int.new(name)
            for e, item in zip(elements, attr.data):
                e[layer] = item.value


def _kill_face(bm, f):
    bm.faces.remove(f)
    for v in f.verts:
        v.link_faces.remove(f)
    f.is_valid = False


def triangulate(bm, faces, quad_method=None, ngon_method=None):
    """bmesh.ops.triangulate: each face of more than three corners becomes a fan from its first corner, its
    triangles appended with its layer values; returns {'faces': the new triangles}."""
    out = []
    for f in list(faces):
        if not f.is_valid or len(f.verts) <= 3:
            continue
        verts, values = list(f.verts), dict(f.layer_values)
        _kill_face(bm, f)
        for i in range(1, len(verts) - 1):
            t = bm.faces.new([verts[0], verts[i], verts[i + 1]])
            t.layer_values.update(values)
            out.append(t)
    return {'faces': out}


def weld_verts(bm, targetmap):
    """bmesh.ops.weld_verts: every face takes the target of each mapped vertex; a face that keeps fewer than
    three distinct corners goes; the mapped vertices go."""
    for f in [f for f in bm.faces if any(v in targetmap for v in f.verts)]:
        verts, values = [targetmap.get(v, v) for v in f.verts], dict(f.layer_values)
        kept = [v for i, v in enumerate(verts) if v is not verts[i - 1]]
        _kill_face(bm, f)
        if len({id(v) for v in kept}) >= 3:
            g = bm.faces.new(kept)
            g.layer_values.update(values)
    for v in targetmap:
        if v.is_valid:
            bm.verts.remove(v)
            v.is_valid = False


def delete(bm, geom, context):
    """bmesh.ops.delete of faces: the faces go, and with them the vertices they leave without a face."""
    for f in [g for g in geom if isinstance(g, BMFace) and g.is_valid]:
        verts = list(f.verts)
        _kill_face(bm, f)
        for v in verts:
            if v.is_valid and not v.link_faces:
                bm.verts.remove(v)
                v.is_valid = False


def rotate_edges(bm, edges, use_ccw=False):
    """bmesh.ops.rotate_edges: each edge between two triangles becomes their other diagonal, the two new
    triangles wound as the old ones and taking their layer values; an edge that is not between two
    triangles, or whose other diagonal is an edge already, stays. Returns {'edges': the new edges}."""
    out = []
    for e in edges:
        faces = e.link_faces
        if len(faces) != 2 or any(len(f.verts) != 3 for f in faces):
            continue
        f1, f2 = faces
        i = next(i for i in range(3) if {f1.verts[i], f1.verts[(i + 1) % 3]} == set(e.verts))
        p, q, r = f1.verts[i], f1.verts[(i + 1) % 3], f1.verts[(i + 2) % 3]
        o = next(v for v in f2.verts if v is not p and v is not q)
        if edge(r, o).is_valid:
            continue
        v1, v2 = dict(f1.layer_values), dict(f2.layer_values)
        _kill_face(bm, f1)
        _kill_face(bm, f2)
        bm.faces.new([p, o, r]).layer_values.update(v1)
        bm.faces.new([o, q, r]).layer_values.update(v2)
        out.append(edge(r, o))
    return {'edges': out}


def _closest_on_triangle(p, a, b, c):
    """The point of triangle abc nearest to p, by the Voronoi regions of its corners and edges."""
    ab, ac, ap = b - a, c - a, p - a
    d1, d2 = ab.dot(ap), ac.dot(ap)
    if d1 <= 0 and d2 <= 0:
        return a
    bp = p - b
    d3, d4 = ab.dot(bp), ac.dot(bp)
    if d3 >= 0 and d4 <= d3:
        return b
    vc = d1 * d4 - d3 * d2
    if vc <= 0 and d1 >= 0 and d3 <= 0:
        return a + ab * (d1 / (d1 - d3))
    cp = p - c
    d5, d6 = ab.dot(cp), ac.dot(cp)
    if d6 >= 0 and d5 <= d6:
        return c
    vb = d5 * d2 - d1 * d6
    if vb <= 0 and d2 >= 0 and d6 <= 0:
        return a + ac * (d2 / (d2 - d6))
    va = d3 * d6 - d5 * d4
    if va <= 0 and d4 - d3 >= 0 and d5 - d6 >= 0:
        return b + (c - b) * ((d4 - d3) / ((d4 - d3) + (d5 - d6)))
    denom = 1.0 / (va + vb + vc)
    return a + ab * (vb * denom) + ac * (vc * denom)


def intersect_point_tri(pt, a, b, c):
    """mathutils.geometry.intersect_point_tri: pt projected onto the plane of abc when the projection lies
    inside the triangle, else None."""
    pt, a, b, c = Vector(pt), Vector(a), Vector(b), Vector(c)
    n = (b - a).cross(c - a)
    if not n.length:
        return None
    n = n.normalized()
    q = pt - n * (pt - a).dot(n)
    for u, v in ((a, b), (b, c), (c, a)):
        if (v - u).cross(q - u).dot(n) < -1e-12:
            return None
    return q


class BVHTree:
    """mathutils.bvhtree.BVHTree: FromPolygons keeps the points and polygons it was made from; ray_cast and
    find_nearest answer over the polygons' fan triangles, each hit with its polygon's normal and index."""

    def __init__(self, verts=(), polys=()):
        self.verts, self.polys = [Vector(v) for v in verts], [list(p) for p in polys]
        self.tris = [(k, self.verts[p[0]], self.verts[p[i]], self.verts[p[i + 1]])
                     for k, p in enumerate(self.polys) for i in range(1, len(p) - 1)]
        self.normals = [self._normal(p) for p in self.polys]

    def _normal(self, poly):
        n = [0.0, 0.0, 0.0]
        pts = [self.verts[i] for i in poly]
        for p, q in zip(pts, pts[1:] + pts[:1]):
            n[0] += (p.y - q.y) * (p.z + q.z)
            n[1] += (p.z - q.z) * (p.x + q.x)
            n[2] += (p.x - q.x) * (p.y + q.y)
        return Vector(n).normalized()

    @classmethod
    def FromPolygons(cls, verts, polys):
        return cls(verts, polys)

    def ray_cast(self, origin, direction, distance=math.inf):
        """(location, normal, index, distance) of the nearest hit along the ray within `distance`, else four
        Nones (the Moller-Trumbore test, on either side of a triangle)."""
        o, d = Vector(origin), Vector(direction).normalized()
        best = None
        for k, a, b, c in self.tris:
            e1, e2 = b - a, c - a
            p = d.cross(e2)
            det = e1.dot(p)
            if abs(det) < 1e-15:
                continue
            t0 = o - a
            u = t0.dot(p) / det
            if u < 0 or u > 1:
                continue
            q = t0.cross(e1)
            v = d.dot(q) / det
            if v < 0 or u + v > 1:
                continue
            t = e2.dot(q) / det
            if 0 <= t <= distance and (best is None or t < best[0]):
                best = (t, k)
        if best is None:
            return None, None, None, None
        t, k = best
        return o + d * t, Vector(self.normals[k]), k, t

    def find_nearest(self, point, distance=math.inf):
        """(location, normal, index, distance) of the surface point nearest to `point` within `distance`,
        else four Nones."""
        p = Vector(point)
        best = None
        for k, a, b, c in self.tris:
            q = _closest_on_triangle(p, a, b, c)
            dist = (q - p).length
            if dist <= distance and (best is None or dist < best[0]):
                best = (dist, k, q)
        if best is None:
            return None, None, None, None
        dist, k, q = best
        return Vector(q), Vector(self.normals[k]), k, dist


@contextlib.contextmanager
def stand_ins():
    """bpy, bmesh and mathutils stand-ins for the module-level imports of lpk.core, lpk.forms and lpk.build, and
    lpk as a bare package over its folder; sys.modules is restored afterwards."""
    names = ('bpy', 'bmesh', 'bmesh.ops', 'mathutils', 'mathutils.bvhtree', 'mathutils.geometry')
    ours = lambda name: name in names or name == 'lpk' or name.startswith('lpk.')
    saved = {k: v for k, v in sys.modules.items() if ours(k)}
    for k in saved:
        del sys.modules[k]
    mathutils = types.ModuleType('mathutils')
    mathutils.Vector, mathutils.Matrix = Vector, type('Matrix', (), {})
    bvhtree = types.ModuleType('mathutils.bvhtree')
    bvhtree.BVHTree = BVHTree
    mathutils.bvhtree = bvhtree
    geometry = types.ModuleType('mathutils.geometry')
    geometry.intersect_point_tri = intersect_point_tri
    mathutils.geometry = geometry
    bmesh = types.ModuleType('bmesh')
    bmesh.new = BMesh
    ops = types.ModuleType('bmesh.ops')
    ops.triangulate, ops.weld_verts, ops.delete, ops.rotate_edges = triangulate, weld_verts, delete, rotate_edges
    bmesh.ops = ops
    lpk = types.ModuleType('lpk')
    lpk.__path__ = [os.path.join(ROOT, 'lpk')]
    sys.modules.update({'bpy': types.ModuleType('bpy'), 'bmesh': bmesh, 'bmesh.ops': ops, 'mathutils': mathutils,
                        'mathutils.bvhtree': bvhtree, 'mathutils.geometry': geometry, 'lpk': lpk})
    try:
        yield
    finally:
        for k in [k for k in sys.modules if ours(k)]:
            del sys.modules[k]
        sys.modules.update(saved)
