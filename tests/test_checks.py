"""Host tests of the numpy parts and the part-name rules of lpk.stages.checks (no Blender
needed): the rasterizer, the separations, the hole loops, the shell clearance and the mirror twins, the latter against the
smooth bake's mirror rule written out."""
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lpk.stages import checks  # noqa: E402


def _raises(exc, fn, *args, **kw):
    try:
        fn(*args, **kw)
    except exc:
        return
    raise AssertionError('%s not raised' % exc.__name__)


def _rect(u0, v0, u1, v1):
    return [[(u0, v0), (u1, v0), (u1, v1)], [(u0, v0), (u1, v1), (u0, v1)]]


def test_fan_triangles_and_face_parts():
    tris = checks.fan_triangles([0, 3], [3, 4], [0, 1, 2, 3, 4, 5, 6])
    assert tris.tolist() == [[0, 1, 2], [3, 4, 5], [3, 5, 6]]
    vpart = [0, 1, 1, 2, 2, 0, 5]
    assert checks.face_parts(vpart, [[0, 1, 2], [0, 0, 1], [1, 0, 0], [0, 3, 6], [3, 4, 0]]).tolist() == [1, 0, 0, 0, 2]


def _barycentric_cover(tris, shape):
    """The coverage cover gives, written out: a pixel centre (c, r) passes the barycentric test of a
    triangle, one triangle at a time."""
    H, W = shape
    out = np.zeros((H, W), bool)
    Y, X = np.mgrid[0:H, 0:W].astype(np.float64)
    for (ax, ay), (bx, by), (cx, cy) in np.asarray(tris, np.float64).reshape(-1, 3, 2):
        area = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
        if abs(area) < 1e-18:
            continue
        w0 = ((bx - X) * (cy - Y) - (by - Y) * (cx - X)) / area
        w1 = ((cx - X) * (ay - Y) - (cy - Y) * (ax - X)) / area
        out |= (w0 >= -1e-9) & (w1 >= -1e-9) & (1.0 - w0 - w1 >= -1e-9)
    return out


def test_cover_takes_the_pixel_centres_inside_each_triangle():
    rng = np.random.default_rng(7)
    shape = (40, 50)
    tris = rng.uniform(-8, 58, size=(60, 3, 2))
    tris[0] = [[3.0, 3.0], [9.0, 9.0], [15.0, 15.0]]          # degenerate: covers nothing
    tris[1] = [[-20.0, -20.0], [-10.0, -20.0], [-15.0, -5.0]]  # off the picture
    for t in tris:
        assert np.array_equal(checks.cover(t[None], shape), _barycentric_cover(t[None], shape)), t
    assert np.array_equal(checks.cover(tris, shape), _barycentric_cover(tris, shape))
    on_grid = rng.integers(-6, 110, size=(200, 3, 2)) / 2.0     # edges through pixel centres: ties included
    for t in on_grid:
        assert np.array_equal(checks.cover(t[None], shape), _barycentric_cover(t[None], shape)), t
    assert not checks.cover(np.zeros((0, 3, 2)), shape).any()
    quad = [[[-0.5, -0.5], [3.5, -0.5], [3.5, 2.5]], [[-0.5, -0.5], [3.5, 2.5], [-0.5, 2.5]]]
    assert checks.cover(quad, (4, 6))[:3, :4].all() and not checks.cover(quad, (4, 6))[3].any()
    assert np.array_equal(checks.rasterize(_rect(0, 0, 1, 1), 0.0, 0.0, 0.1, (10, 10)), np.ones((10, 10), bool))


def test_rasterize_triangle_counts_centres_inside():
    m = checks.rasterize([[(0, 0), (1, 0), (0, 1)]], 0.0, 0.0, 0.1, (10, 10))
    assert m.sum() == 55
    assert m[0, 0] and m[0, 9] and m[9, 0] and not m[9, 9]


def test_rasterize_shared_edge_leaves_no_crack_and_winding_is_free():
    m = checks.rasterize(_rect(0, 0, 1, 1), 0.0, 0.0, 0.1, (10, 10))
    assert m.all()
    flipped = checks.rasterize([[(0, 0), (0, 1), (1, 0)]], 0.0, 0.0, 0.1, (10, 10))
    assert flipped.sum() == 55
    assert not checks.rasterize([[(0, 0), (1, 1), (2, 2)]], 0.0, 0.0, 0.1, (30, 30)).any()


def test_rasterize_rows_go_up_from_v0():
    m = checks.rasterize(_rect(0.0, 0.5, 1.0, 1.0), 0.0, 0.0, 0.1, (10, 10))
    assert not m[:5].any() and m[5:].all()


def test_separation_touching_span():
    limb = _rect(0.1, 0.0, 0.2, 1.0)
    body = _rect(-0.2, 0.5, 0.1, 1.5)
    r = checks.separation(limb, body, px=0.01)
    assert r['rows'] == 50
    assert r['span'] == [0.5, 1.0] and math.isclose(r['length'], 0.5)
    assert r['runs'] == [[0.5, 1.0]]


def test_separation_gap_of_two_pixels_separates():
    r = checks.separation(_rect(0.12, 0.0, 0.2, 1.0), _rect(-0.2, 0.5, 0.1, 1.5), px=0.01)
    assert r == {'span': None, 'length': 0.0, 'rows': 0, 'runs': []}


def test_separation_gap_under_a_pixel_touches():
    r = checks.separation(_rect(0.104, 0.0, 0.2, 1.0), _rect(-0.2, 0.5, 0.1, 1.5), px=0.01)
    assert r['rows'] == 50


def test_separation_runs_and_z_range():
    limb = _rect(0.1, 0.0, 0.2, 1.0)
    body = _rect(-0.2, 0.8, 0.1, 1.5) + _rect(-0.2, 0.0, 0.1, 0.2)
    r = checks.separation(limb, body, px=0.01)
    assert r['runs'] == [[0.8, 1.0], [0.0, 0.2]]
    assert r['span'] == [0.0, 1.0] and r['rows'] == 40
    low = checks.separation(limb, body, px=0.01, z_range=(0.0, 0.5))
    assert low['runs'] == [[0.0, 0.2]] and low['rows'] == 20


def test_separation_reads_a_mirrored_pair_the_same_on_both_sides():
    rng = np.random.default_rng(14)
    body = np.array(_rect(-0.1, 0.0, 0.1, 1.0))                      # symmetric about x = 0
    for _ in range(200):
        x0 = rng.uniform(0.1, 0.12)                                  # a gap of up to a few pixels
        limb = np.array(_rect(x0, rng.uniform(0.0, 0.5), x0 + rng.uniform(0.02, 0.1), rng.uniform(0.6, 1.2)))
        limb[0, 2, 0] += rng.uniform(-0.02, 0.0)                     # a slanted inner edge
        twin = limb * [-1.0, 1.0]
        px = rng.uniform(0.004, 0.012)
        left, right = checks.separation(limb, body, px=px), checks.separation(twin, body, px=px)
        assert left == right, (x0, px, left, right)


def test_separation_needs_both_sets():
    _raises(ValueError, checks.separation, [], _rect(0, 0, 1, 1))


def test_join_loops_by_child_and_unfilled():
    # torso ring 0-3 tagged with arm 4-5 grown from it; ring 6-8 tagged with nothing grown yet
    vpart = [0, 0, 0, 0, 1, 1, 0, 0, 0, 0]
    tag = [1, 1, 1, 1, 0, 0, 1, 1, 1, 0]
    edges = [(0, 1), (1, 2), (2, 3), (3, 0), (0, 4), (1, 4), (2, 5), (3, 5), (4, 5),
             (6, 7), (7, 8), (8, 6), (6, 9)]
    loops = checks.join_loops(edges, vpart, tag, ['torso', 'arm'])
    assert loops == {'arm': [0, 1, 2, 3], 'loop0': [6, 7, 8]}


def test_loop_stats_square():
    pts = [(0.5, 0, 1), (0.5, 1, 2), (0.5, 0, 2), (0.5, 1, 1)]
    st = checks.loop_stats(pts)
    assert st['verts'] == 4 and math.isclose(st['perimeter'], 4.0)
    assert st['height'] == 1.0 and st['bottom'] == 1.0 and st['top'] == 2.0
    assert st['centroid'] == [0.5, 0.5, 1.5]


# -- shells -------------------------------------------------------------------------------------------

def _octahedron(r=1.0):
    """A closed octahedron of radius r round the origin, its triangles counter-clockwise from outside."""
    v = [(r, 0, 0), (-r, 0, 0), (0, r, 0), (0, -r, 0), (0, 0, r), (0, 0, -r)]
    tris = []
    for a in (0, 1):
        for b in (2, 3):
            for c in (4, 5):
                t = [v[a], v[b], v[c]]
                n = np.cross(np.subtract(t[1], t[0]), np.subtract(t[2], t[0]))
                if np.dot(n, np.mean(t, axis=0)) < 0:
                    t = [t[0], t[2], t[1]]
                tris.append(t)
    return np.array(tris, np.float64)


def _plate(z, size=1.0):
    """A square plate at height z over [-size, size]^2, facing +z."""
    a, b, c, d = (-size, -size, z), (size, -size, z), (size, size, z), (-size, size, z)
    return np.array([[a, b, c], [a, c, d]], np.float64)


def test_ray_hits_counts_edges_and_reads_both_ways():
    tri = np.array([[(0, 0, 0), (1, 0, 0), (0, 1, 0)]], np.float64)
    t = checks.ray_hits([(0.2, 0.2, 1), (0.2, 0.2, -2), (0.5, 0.5, 1), (2, 2, 1), (0, 0, 1)],
                        [(0, 0, -1), (0, 0, -1), (0, 0, -1), (0, 0, -1), (1, 0, 0)], tri)[:, 0]
    assert math.isclose(t[0], 1.0) and math.isclose(t[1], -2.0), 'a ray is a line: behind its origin t < 0'
    assert math.isclose(t[2], 1.0), 'the hypotenuse counts'
    assert math.isnan(t[3]) and math.isnan(t[4]), 'a miss and a parallel ray'
    assert checks.ray_hits(np.zeros((0, 3)), np.zeros((0, 3)), tri).shape == (0, 1)


def test_clearance_from_a_centre_inside_outside_and_uncovered():
    shell = _octahedron(1.0)
    pts = [(0.5, 0, 0), (0, 0, 0.9), (0, 0, 1.25), (0.3, 0.3, 0.3), (0, 0, 0)]
    r = checks.clearance(pts, shell, centre=(0, 0, 0))
    g = r['gap']
    assert math.isclose(g[0], 0.5) and math.isclose(g[1], 0.1, abs_tol=1e-12), g
    assert math.isclose(g[2], -0.25), 'outside: minus how far past the shell'
    assert math.isclose(g[3], 1 / math.sqrt(3) - math.sqrt(0.27)), 'along the ray, not the normal'
    assert math.isnan(g[4]) and r['tri'][4] == -1, 'the centre itself has no ray'
    cap = shell[[i for i, t in enumerate(shell) if t[:, 2].max() > 0]]
    low = checks.clearance([(0, 0, -0.5), (0, 0, 0.5)], cap, centre=(0, 0, 0))['gap']
    assert math.isnan(low[0]) and math.isclose(low[1], 0.5), 'under a cap only what its rays meet'
    _raises(ValueError, checks.clearance, pts, shell)
    _raises(ValueError, checks.clearance, pts, shell, centre=(0, 0, 0), normals=[(0, 0, 1)] * 5)


def test_clearance_along_normals_needs_the_outer_side_and_no_wall_between():
    plate = _plate(0.1)
    up = [(0, 0, 1)] * 4
    r = checks.clearance([(0, 0, 0), (0.5, 0.5, 0.2), (3, 0, 0), (0, 0, -0.5)], plate, normals=up)
    g = r['gap']
    assert math.isclose(g[0], 0.1) and math.isclose(g[1], -0.1), g
    assert math.isnan(g[2]), 'off the plate'
    assert math.isclose(g[3], 0.6), 'under the plate, however far'
    under = checks.clearance([(0, 0, 0.3)], plate, normals=[(0, 0, -1)])['gap']
    assert math.isnan(under[0]), 'a plate seen from its inner side is not one the point stands out of'
    wall = _plate(0.2, 0.5)
    shown = checks.clearance([(0, 0, 0.3)], plate, normals=[(0, 0, 1)])['gap'][0]
    hidden = checks.clearance([(0, 0, 0.3)], plate, normals=[(0, 0, 1)], inner=wall)['gap'][0]
    assert math.isclose(shown, -0.2) and math.isnan(hidden), 'a covered wall between them rules the hit out'


def test_open_edge_triangles():
    quad = [[0, 1, 2], [0, 2, 3]]
    assert checks.open_edge_triangles(quad).tolist() == [True, True]
    tetra = [[0, 2, 1], [0, 1, 3], [1, 2, 3], [0, 3, 2]]
    assert not checks.open_edge_triangles(tetra).any()
    strip = [[0, 1, 4], [1, 2, 4], [2, 3, 4], [3, 0, 4], [5, 6, 7]]
    assert checks.open_edge_triangles(strip).tolist() == [True, True, True, True, True]
    assert checks.open_edge_triangles(np.zeros((0, 3), int)).shape == (0,)


# -- mirror -------------------------------------------------------------------------------------------

def _rig_mirror_rule(co, eps=checks.MIRROR_TOLERANCE):
    """lpk.stages.rig._mirror's rule, written out: each vertex at x < -eps takes the vertex nearest its
    mirror image when that lies within eps. {vertex: twin or -1}."""
    co = np.asarray(co, np.float64)
    out = {}
    for i, p in enumerate(co):
        if p[0] < -eps:
            d = np.linalg.norm(co - p * [-1, 1, 1], axis=1)
            j = int(np.argmin(d))
            out[i] = j if d[j] <= eps else -1
    return out


def test_mirror_tolerance_is_the_smooth_bakes():
    import ast
    tree = ast.parse((Path(__file__).resolve().parents[1] / 'lpk' / 'stages' / 'rig.py').read_text(encoding='utf-8'))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_mirror')
    eps = dict(zip([a.arg for a in fn.args.args][-len(fn.args.defaults):], fn.args.defaults))['eps']
    assert ast.literal_eval(eps) == checks.MIRROR_TOLERANCE


def test_mirror_twins_follow_the_smooth_bakes_rule():
    rng = np.random.default_rng(7)
    half = rng.uniform([0.01, -0.3, 0.0], [0.4, 0.3, 1.8], (300, 3))
    other = half * [-1, 1, 1]
    other[:40] += rng.normal(0, 4e-5, (40, 3))          # within the twin distance, mostly
    other[40:60] += rng.normal(0, 3e-3, (20, 3))        # off mirror
    mid = np.column_stack([np.zeros(10), rng.uniform(-0.3, 0.3, 10), rng.uniform(0, 1.8, 10)])
    lone = rng.uniform([-0.4, -0.3, 0.0], [-0.01, 0.3, 1.8], (15, 3))
    co = np.concatenate([half, other, mid, lone])
    twin = checks.mirror_twins(co)
    rule = _rig_mirror_rule(co)
    assert rule and all(twin[i] == j for i, j in rule.items()), [(i, twin[i], j) for i, j in rule.items() if twin[i] != j]
    assert sum(j >= 0 for j in rule.values()) > 200 and sum(j < 0 for j in rule.values()) > 10
    n = len(half) + len(other)
    assert (twin[n:n + 10] == np.arange(n, n + 10)).all(), 'a midline vertex is its own twin'
    left = np.flatnonzero(co[:, 0] > checks.MIRROR_TOLERANCE)
    assert all(twin[twin[i]] == i for i in left if twin[i] >= 0 and twin[twin[i]] >= 0)
    assert checks.mirror_twins(np.zeros((0, 3))).shape == (0,)


def test_mirror_twins_take_the_nearest_and_break_ties_by_id():
    co = [(0.1, 0, 0), (-0.1, 0, 0.00004), (-0.1, 0, -0.00002), (-0.10003, 0, 0)]
    assert checks.mirror_twins(co)[0] == 2
    tie = [(0.1, 0, 0), (-0.1, 0, 0.00003), (-0.1, 0, -0.00003)]
    assert checks.mirror_twins(tie)[0] == 1


def _mirror_mesh():
    """Parts: arm.L / arm.R mirrored, leg.L / leg.R with one vertex 2 mm off, head on the midline
    with mirrored sides, pouch on one side only."""
    arm = [(0.3, 0, 1.4), (0.4, 0.02, 1.3), (0.5, 0, 1.2)]
    leg = [(0.1, 0, 0.8), (0.12, 0.01, 0.4), (0.1, 0, 0.1)]
    head = [(0, 0, 1.7), (0.05, 0.02, 1.65), (-0.05, 0.02, 1.65)]
    pouch = [(0.2, -0.1, 1.0), (0.22, -0.1, 0.95)]
    legr = [(-x, y, z) for x, y, z in leg]
    legr[1] = (legr[1][0], legr[1][1], legr[1][2] + 0.002)
    co = arm + [(-x, y, z) for x, y, z in arm] + leg + legr + head + pouch
    vpart = [0] * 3 + [1] * 3 + [2] * 3 + [3] * 3 + [4] * 3 + [5] * 2
    return np.array(co, np.float64), vpart, ['arm.L', 'arm.R', 'leg.L', 'leg.R', 'head', 'pouch']


def test_mirror_parts_pair_by_position():
    co, vpart, names = _mirror_mesh()
    r = checks.mirror_parts(co, vpart, names)
    assert r['pairs'] == [['arm.L', 'arm.R'], ['leg.L', 'leg.R'], ['head', 'head']], r['pairs']
    assert r['unpaired'] == ['pouch']
    assert [i for i, _ in r['parts']['leg.L']['unmatched']] == [7]
    assert [i for i, _ in r['parts']['leg.R']['unmatched']] == [10]
    assert math.isclose(r['parts']['leg.R']['unmatched'][0][1], 0.002, abs_tol=1e-9)
    assert r['parts']['arm.L']['twins'] == {'arm.R': 3} and r['parts']['head']['twins'] == {'head': 3}
    assert r['parts']['pouch']['twins'] == {} and len(r['parts']['pouch']['unmatched']) == 2


def test_mirror_parts_list_the_vertices_mirroring_into_each_part():
    co = np.array([(0.1, 0, z) for z in np.linspace(0.0, 0.9, 10)]
                  + [(-0.1, 0, z) for z in np.linspace(0.0, 0.5, 6)]
                  + [(-0.1, 0, z) for z in np.linspace(0.6, 0.9, 4)], np.float64)
    vpart = [0] * 10 + [1] * 6 + [2] * 4
    rep = checks.mirror_parts(co, vpart, ['A', 'B', 'C'])
    assert rep['pairs'] == [['A', 'B']] and rep['unpaired'] == ['C']
    assert rep['parts']['A']['twin_verts'] == {'B': list(range(6)), 'C': list(range(6, 10))}
if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print('ok', name)
