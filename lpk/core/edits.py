"""The human's hand edits of generated parts, kept as data so a rebuild keeps them.

The human moves vertices of a built body in Blender (smoother transitions, a shorter muzzle). capture diffs
the edited object against a fresh build of the same model and stores per-vertex offsets for each part the
model's build_mesh applies edits to; apply replays them right after the part is made, so whatever is cast
onto the part later (eyes, hair, decals) follows the edited shape.

Offsets key on the part's vertex order. A change to the part's construction can keep the vertex count and
still reorder the vertices, so an entry also stores the topology key of the part as it was captured (its
faces over its own vertices, after its triangulation). An entry whose count, topology or unit differs from
the part as built raises ValueError naming the part: an entry is never applied to other vertices and never
skipped; the human captures the part again or drops its entry.

Offsets are stored in units: metres = stored offset * unit, where unit is the metres per stored unit apply
is given (a head height for a head), so the edits scale with the measurements.

File (plain JSON, UTF-8, LF, sorted keys): {part: {'unit': the unit's name, 'count': vertices, 'topology':
the part's topology key, 'deltas': {local vertex index: [dx, dy, dz] in stored units}}}."""
import hashlib
import json
from pathlib import Path

import bmesh
import numpy as np
from mathutils import Vector

# Positions closer than this (metres) are the same position: float32 rounding of a written mesh stays
# below it, a deliberate move does not.
EPS = 1e-5
# The key of the measurements dict P under which apply records each part's reference for capture.
REFS = '_edit_ref'


def load(path):
    """The entries of the edit file at `path`, {part: entry}; {} when the file does not exist."""
    p = Path(path)
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}


def save(path, data):
    """Write the entries `data` ({part: entry}) to the edit file at `path`: JSON with sorted keys, UTF-8,
    LF line ends."""
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(json.dumps(data, indent=1, sort_keys=True) + '\n')


def triangulate(bm, faces):
    """Triangulate the faces of `faces` that have more than three corners, as finish does (BEAUTY quads,
    EAR_CLIP n-gons). apply triangulates a part this way before its topology key is taken and its edits
    replayed: the human edits a triangulated mesh, and triangulating after the moves picks other
    diagonals."""
    polygons = [f for f in faces if f.is_valid and len(f.verts) > 3]
    if polygons:
        bmesh.ops.triangulate(bm, faces=polygons, quad_method='BEAUTY', ngon_method='EAR_CLIP')


def topology(b, pid, *, verts=None, faces=None):
    """The topology key of a part: the SHA-256 hex of its faces over its own vertices: each face as the
    local indices of its vertices in the part's vertex order (a vertex of another part, at a join, counts as
    -1), rotated to start at its smallest index so the key does not depend on where a face's loop starts,
    the faces sorted. Sorting makes the key independent of the bmesh face order, which reuses the slots of
    faces deleted earlier in the build (triangulation, welds): a part keeps its key when another part's
    construction changes. A face belongs to the part of its first vertex. Read only.

    b: the Builder; pid: the part's index. verts, faces: the part's vertices in mesh order and the faces to
    read, when the caller has them, else every vertex and face of b."""
    if verts is None:
        verts = [v for v in b.bm.verts if v[b.vpart] == pid]
    local = {v: i for i, v in enumerate(verts)}
    keys = []
    for f in (b.bm.faces if faces is None else faces):
        if f.verts[0][b.vpart] != pid:
            continue
        idx = [local.get(v, -1) for v in f.verts]
        k = idx.index(min(idx))
        keys.append(idx[k:] + idx[:k])
    h = hashlib.sha256()
    for key in sorted(keys):
        h.update(repr(key).encode())
    return h.hexdigest()


def conflict(entry, count, key, unit_name=None):
    """Why a stored entry cannot be replayed on a part built with `count` vertices, topology key `key` and,
    when given, the unit named `unit_name`: 'count', 'topology', 'unit', or None when it fits. An entry
    without a topology key conflicts; an entry without a unit name fits any unit."""
    if entry.get('count') != count:
        return 'count'
    if entry.get('topology') != key:
        return 'topology'
    if unit_name is not None and entry.get('unit', unit_name) != unit_name:
        return 'unit'
    return None


def apply(b, P, part, data, unit=1.0, unit_name='m'):
    """Replay the stored edits of part `part` on the builder `b` and record the part's reference for a later
    capture. Call it right after the part is made, before anything is cast onto it or joined to it.

    The part's faces are triangulated first (triangulate), on the unedited positions; then its topology
    key is taken and, when `data` ({part: entry}, load's result, or None) holds an entry for the part, every
    stored offset times `unit` (metres per stored unit) is added to its vertex. P: the model's measurements
    dict; P[REFS][part] receives {'positions': the part's vertex positions after the replay (m, part
    order), 'count', 'topology', 'unit', 'unit_name'}. unit_name: the name the entry stores for the unit.
    Returns the number of vertices moved. Raises ValueError naming the part when its entry was captured on
    another vertex count, topology or unit: the build stops before the body is written."""
    pid = b.pid(part)
    triangulate(b.bm, [f for f in b.bm.faces if f.verts[0][b.vpart] == pid])
    verts = [v for v in b.bm.verts if v[b.vpart] == pid]
    key = topology(b, pid, verts=verts)
    entry = (data or {}).get(part)
    moved = 0
    if entry:
        why = conflict(entry, len(verts), key, unit_name)
        if why == 'count':
            raise ValueError('edits of part %r were captured on %d vertices; the part now has %d: capture the part '
                             'again or drop its entry' % (part, entry.get('count'), len(verts)))
        if why == 'topology':
            raise ValueError('edits of part %r were captured on another topology (the part keeps its %d vertices '
                             'in another order or with other faces): capture the part again or drop its entry'
                             % (part, len(verts)))
        if why == 'unit':
            raise ValueError('edits of part %r are stored in the unit %r; the build gives %r: capture the part '
                             'again or drop its entry' % (part, entry['unit'], unit_name))
        for k, d in sorted(entry['deltas'].items(), key=lambda kv: int(kv[0])):
            verts[int(k)].co += Vector(d) * unit
        moved = len(entry['deltas'])
    P.setdefault(REFS, {})[part] = {'positions': [tuple(float(c) for c in v.co) for v in verts],
                                    'count': len(verts), 'topology': key, 'unit': float(unit),
                                    'unit_name': unit_name}
    return moved


def capture_positions(edited, generated, refs, data, eps=EPS):
    """Add the human's offsets to `data`, from vertex positions: the pure part of capture.

    edited, generated: the vertex positions (m, mesh order) of the edited object and of a fresh build of
    the same model, one per vertex in the same order. refs: {part: reference} as apply records them in
    P[REFS] during that fresh build. data: {part: entry}, changed in place. A vertex counts as moved when
    its edited position differs from the generated one by more than eps (m); a moved vertex belongs to a
    part when its generated position lies within eps of one of the part's reference positions, the nearest
    one, the lowest index on a tie. Its offset in stored units (the move over the reference's unit) is
    added to the entry's offset of that vertex, so offsets captured before stay; a second moved vertex at
    the same reference vertex is left out. An entry takes the part's count, topology and unit name; a part
    without any offset gets no entry. Parts are taken in the order of refs.

    Returns {'parts': {part: vertices captured by this call}, 'moved': vertices moved, 'untracked': moved
    vertices no part keeps, 'stored': {part: vertices with a stored offset in `data` after the call, earlier
    captures included}}; untracked moves are lost on the next build. A part edited earlier and not moved
    since captures 0 vertices and keeps its stored offsets. Raises ValueError when the two position lists
    differ in length (the build's topology changed since the edited object was made)."""
    e = np.asarray(edited, dtype=float).reshape(-1, 3)
    g = np.asarray(generated, dtype=float).reshape(-1, 3)
    if len(e) != len(g):
        raise ValueError('the edited mesh has %d vertices, a fresh build %d: the topology changed, the edits '
                         'cannot be matched' % (len(e), len(g)))
    moved = np.flatnonzero(np.linalg.norm(e - g, axis=1) > eps)
    kept = np.zeros(len(moved), dtype=bool)
    report = {}
    for part, ref in refs.items():
        positions = np.asarray(ref['positions'], dtype=float).reshape(-1, 3)
        entry = data.get(part) or {'deltas': {}}
        deltas = dict(entry.get('deltas', {}))
        taken, n = set(), 0
        if len(positions) and len(moved):
            dist = np.linalg.norm(g[moved][:, None, :] - positions[None, :, :], axis=2)
            nearest = np.argmin(dist, axis=1)
            for k, (i, j) in enumerate(zip(moved, nearest)):
                if dist[k, j] > eps or int(j) in taken:
                    continue
                taken.add(int(j))
                kept[k] = True
                old = deltas.get(str(int(j)), (0.0, 0.0, 0.0))
                deltas[str(int(j))] = [float(o + d / ref['unit']) for o, d in zip(old, e[i] - g[i])]
                n += 1
        if deltas:
            data[part] = {'unit': ref['unit_name'], 'count': ref['count'], 'topology': ref['topology'],
                          'deltas': deltas}
        report[part] = n
    stored = {part: len(entry.get('deltas', {})) for part, entry in sorted(data.items())}
    return {'parts': report, 'moved': int(len(moved)), 'untracked': int(len(moved) - kept.sum()), 'stored': stored}


def capture(edited, generated, P, data, eps=EPS):
    """Add the offsets of the edited object `edited` from the freshly built object `generated` (same model,
    same location, its parts recorded by apply in P[REFS]) to `data`, {part: entry}, changed in place; save
    writes it. Reads each object's mesh vertex positions and runs capture_positions over them; returns its
    report. Raises ValueError when the two meshes differ in vertex count."""
    return capture_positions([tuple(v.co) for v in edited.data.vertices],
                             [tuple(v.co) for v in generated.data.vertices], P.get(REFS, {}), data, eps)
