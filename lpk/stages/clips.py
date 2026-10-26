"""Clips of another skeleton sampled onto a model's rig, for review: a clip file is imported into a
temporary collection (load_clip), chosen frames of it become pose entries of the model's rig (sample), the
feet can be planted on the floor (plant), and the clip goes again (remove_clip). The poses go to the pose
sheet (lpk.stages.review.pose_captures); nothing is keyed on the model's rig.

A bone map {rig bone: (clip bone, mode)} says which clip bone drives which rig bone, and how. Per frame a
mapped bone takes its clip bone's rotation in world space: 'delta' carries the clip bone's turn away from
its own rest onto the rig bone's rest (a spine, a head, legs: the rests differ only a little, and a
digitigrade leg keeps its own angles); 'dir' points the rig bone where the clip bone points (arms: a T-pose
clip on an A-pose rig would otherwise hold every gesture low by the rests' difference). The rig's root
also travels, by the clip root's travel scaled by the ratio of the two roots' heights. A rig bone the map
leaves out keeps its rest against its parent, or takes the turn of `extra`. The map is the caller's data:
bone names say nothing the kit may read meaning from.

Two corrections make clips from other tools comparable. A clip's top bone that the map leaves out (a root
above the hips) is held at its rest: an exporter's unit scale or axis turn keyed on it drops out, and so
does its root motion. And the clip is turned into the rig's frame by the rotation that best lays the rest
directions of its 'delta' bones onto the rig's (fit_rotation): a clip whose file axes differ stands up, and
a clip already in the rig's frame turns by about nothing."""
import math
import os

import bpy
import numpy as np
from mathutils import Euler, Matrix, Quaternion, Vector

from lpk.stages import pose as pose_stage

MODES = ('delta', 'dir')
# The temporary collection the clip is imported into; remove_clip removes it.
COLLECTION = 'lpk_clip'


def load_clip(path):
    """The clip file `path` (.fbx, .glb or .gltf) imported into the collection COLLECTION, made anew.
    Returns {'armature': the name of the armature object carrying an action, 'action': its name,
    'frames': (first, last) whole frames of the action, 'bones': its bone names in order, 'objects': every
    object the import made}. Raises ValueError for another extension and for a file with no animated
    armature (after removing what it imported)."""
    ext = os.path.splitext(path)[1].lower()
    if ext not in ('.fbx', '.glb', '.gltf'):
        raise ValueError('clip %s: give an .fbx, .glb or .gltf file' % path)
    old = bpy.data.collections.get(COLLECTION)
    if old is not None:
        remove_clip({'objects': [o.name for o in old.objects], 'action': None})
    coll = bpy.data.collections.new(COLLECTION)
    bpy.context.scene.collection.children.link(coll)
    before, actions = set(bpy.data.objects), set(bpy.data.actions)
    layer = bpy.context.view_layer
    keep = layer.active_layer_collection
    layer.active_layer_collection = layer.layer_collection.children[COLLECTION]
    try:
        if ext == '.fbx':
            bpy.ops.import_scene.fbx(filepath=path, automatic_bone_orientation=True)
        else:
            bpy.ops.import_scene.gltf(filepath=path)
    finally:
        layer.active_layer_collection = keep
    made = [o for o in bpy.data.objects if o not in before]
    arms = [o for o in made if o.type == 'ARMATURE' and o.animation_data and o.animation_data.action]
    if not arms:
        remove_clip({'objects': [o.name for o in made], 'action': None,
                     'actions': [a.name for a in bpy.data.actions if a not in actions]})
        raise ValueError('clip %s: no armature with an action in it' % path)
    arm = arms[0]
    act = arm.animation_data.action
    first, last = act.frame_range
    return {'armature': arm.name, 'action': act.name, 'frames': (int(round(first)), int(round(last))),
            'bones': [b.name for b in arm.data.bones], 'objects': [o.name for o in made],
            'actions': [a.name for a in bpy.data.actions if a not in actions]}


def remove_clip(clip):
    """Remove what load_clip made: the objects of clip['objects'] with their data, the actions of
    clip['actions'] (or clip['action']), and the collection COLLECTION."""
    for name in clip.get('objects', ()):
        ob = bpy.data.objects.get(name)
        if ob is None:
            continue
        kind, data = ob.type, (ob.data.name if ob.data is not None else None)
        bpy.data.objects.remove(ob, do_unlink=True)
        store = {'ARMATURE': bpy.data.armatures, 'MESH': bpy.data.meshes}.get(kind)
        if store is not None and data in store and store[data].users == 0:
            store.remove(store[data])
    for name in clip.get('actions', ()) or ([clip['action']] if clip.get('action') else []):
        act = bpy.data.actions.get(name)
        if act is not None:
            bpy.data.actions.remove(act)
    coll = bpy.data.collections.get(COLLECTION)
    if coll is not None:
        bpy.data.collections.remove(coll)


def tail_sway(prefix='Tail.', period=1.0, amp=12.0, lag=0.55, lift=4.0):
    """An `extra` for sample: a wave travelling down a chain of bones named prefix + number, `period`
    seconds a cycle, `amp` degrees about each bone's Z and a smaller `lift` about its X at twice the rate,
    each bone `lag` radians of phase behind the one before. Returns fn(bone name, seconds) -> (x, y, z)
    degrees, None for a bone outside the chain."""
    def fn(name, t):
        if not name.startswith(prefix) or not name[len(prefix):].isdigit():
            return None
        ph = 2 * math.pi * t / period - lag * int(name[len(prefix):])
        return (lift * math.sin(2 * ph), 0.0, amp * math.sin(ph))
    return fn


def map_problems(bone_map, rig_bones, clip_bones, root):
    """The problems of a bone map against the rig's and the clip's bone names, [str]: an entry that is not
    (clip bone, mode), a rig bone the rig lacks, a clip bone the clip lacks, a mode not in MODES, and the
    rig's root `root` left unmapped (the travel needs it)."""
    out = []
    for bone, entry in bone_map.items():
        if not (isinstance(entry, (tuple, list)) and len(entry) == 2):
            out.append('bone_map[%r]: give (clip bone, mode)' % (bone,))
            continue
        src, mode = entry
        if bone not in rig_bones:
            out.append('bone_map[%r]: the rig has no bone %r' % (bone, bone))
        if src not in clip_bones:
            out.append('bone_map[%r]: the clip has no bone %r' % (bone, src))
        if mode not in MODES:
            out.append('bone_map[%r]: mode %r is not one of %s' % (bone, mode, ', '.join(MODES)))
    if root not in bone_map:
        out.append('bone_map: map the rig\'s root %r, whose travel the clip drives' % root)
    return out


def fit_rotation(pairs):
    """The rotation, a 3x3 nested list, that best turns the unit directions a onto the unit directions b
    of pairs [(a, b)], each (x, y, z), in least squares (Kabsch: the singular value decomposition of the
    sum of b a^T, with its reflection removed). Fewer than two pairs, or pairs all along one line, leave
    a turn about that line free: the result is then one of the rotations that fit."""
    if not pairs:
        return [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    a = np.array([p[0] for p in pairs], dtype=np.float64)
    b = np.array([p[1] for p in pairs], dtype=np.float64)
    u, _, vt = np.linalg.svd(b.T @ a)
    d = np.sign(np.linalg.det(u @ vt)) or 1.0
    return (u @ np.diag([1.0, 1.0, d]) @ vt).tolist()


def _rot(m):
    return m.to_quaternion().normalized()


def _entry(basis, root):
    """A pose entry (lpk.stages.pose.channels) of a basis matrix: its rotation as Euler XYZ degrees, its
    offset for the root alone."""
    loc, rot, _ = basis.decompose()
    e = rot.to_euler('XYZ')
    entry = {'rot': tuple(round(math.degrees(a), 4) for a in e)}
    if root:
        entry['loc'] = tuple(round(c, 6) for c in loc)
    return entry


def sample(clip_rig, rig, frames, bone_map, hips_scale=None, extra=None):
    """Pose entries of the rig `rig` for `frames` of the clip on the armature `clip_rig` (both armature
    objects' names), by `bone_map` (the module docstring).

    hips_scale: the root's travel factor, by default the rig root's rest height over the clip's mapped
    root's. extra: fn(bone name, seconds) -> (x, y, z) degrees or None, the turn of a bone the map leaves
    out (tail_sway); seconds count from the first frame at the scene's frame rate. The scene's frame comes
    back afterwards. Raises ValueError with map_problems' lines.

    Returns {'poses': {frame: {bone: pose entry}} for every rig bone the map or extra turns, 'mapped': the
    rig bones the map drives, 'unmapped': the rig bones it leaves out, 'root': the rig's root bone,
    'anchor': the clip bone held at its rest or None, 'turn': the angle of the fitted rotation in
    degrees}."""
    scn = bpy.context.scene
    src, tgt = bpy.data.objects[clip_rig], bpy.data.objects[rig]
    roots = [b for b in tgt.data.bones if b.parent is None]
    root = roots[0].name
    problems = map_problems(bone_map, set(tgt.data.bones.keys()), set(src.data.bones.keys()), root)
    if problems:
        raise ValueError('\n'.join(problems))
    Wt = tgt.matrix_world
    Wt_inv = Wt.inverted()
    top = src.data.bones[bone_map[root][0]]
    while top.parent is not None:
        top = top.parent
    used = {n for n, _ in bone_map.values()}
    anchor = top.name if top.name not in used else None
    rest_t = {b.name: Wt @ b.matrix_local for b in tgt.data.bones}
    raw = {n: src.matrix_world @ src.data.bones[n].matrix_local for n in used}
    up = lambda m: tuple((m.to_3x3() @ Vector((0, 1, 0))).normalized())
    fit = [(up(raw[n]), up(rest_t[bone])) for bone, (n, mode) in bone_map.items() if mode == 'delta']
    C = Matrix(fit_rotation(fit)).to_4x4()
    Ws = C @ src.matrix_world
    rest_s = {n: C @ m for n, m in raw.items()}
    root_s = rest_s[bone_map[root][0]].translation
    root_t = rest_t[root].translation
    k = hips_scale if hips_scale is not None else root_t.z / max(root_s.z, 1e-6)
    align = {}
    for bone, (n, mode) in bone_map.items():
        if mode == 'dir':
            ds = (rest_s[n].to_3x3() @ Vector((0, 1, 0))).normalized()
            dt = (rest_t[bone].to_3x3() @ Vector((0, 1, 0))).normalized()
            align[bone] = dt.rotation_difference(ds)
    order = []

    def walk(b):
        order.append(b)
        for c in b.children:
            walk(c)
    for b in roots:
        walk(b)
    kept = scn.frame_current
    poses = {}
    try:
        for f in frames:
            scn.frame_set(f)
            A = (src.data.bones[anchor].matrix_local @ src.pose.bones[anchor].matrix.inverted() if anchor
                 else Matrix.Identity(4))
            posed, entries = {}, {}
            for b in order:
                local_rest = (b.parent.matrix_local.inverted() @ b.matrix_local) if b.parent else b.matrix_local
                base = (posed[b.parent.name] @ local_rest) if b.parent else local_rest
                if b.name in bone_map:
                    n, mode = bone_map[b.name]
                    ps = Ws @ A @ src.pose.bones[n].matrix
                    D = _rot(ps) @ _rot(rest_s[n]).inverted()
                    R = D @ (align[b.name] if mode == 'dir' else Quaternion()) @ _rot(rest_t[b.name])
                    head = base.translation
                    if b.name == root:
                        head = Wt_inv @ (root_t + (ps.translation - root_s) * k)
                    M = Matrix.Translation(head) @ (_rot(Wt).inverted() @ R).to_matrix().to_4x4()
                    basis = base.inverted() @ M
                    entries[b.name] = _entry(basis, b.name == root)
                else:
                    turn = extra(b.name, (f - frames[0]) / scn.render.fps) if extra else None
                    basis = (Euler(tuple(math.radians(a) for a in turn), 'XYZ').to_matrix().to_4x4()
                             if turn else Matrix.Identity(4))
                    if turn:
                        entries[b.name] = {'rot': tuple(float(a) for a in turn)}
                posed[b.name] = base @ basis
            poses[f] = entries
    finally:
        scn.frame_set(kept)
    return {'poses': poses, 'mapped': [b.name for b in order if b.name in bone_map],
            'unmapped': [b.name for b in order if b.name not in bone_map], 'root': root, 'anchor': anchor,
            'turn': round(math.degrees(C.to_quaternion().angle), 2)}


def plant(body, rig, poses, root, parts, floor=0.0):
    """The root's offset in each pose of `poses` ({frame: {bone: pose entry}}, sample's) raised or lowered
    so the lowest vertex of `parts` of the skinned mesh `body` lies on `floor` (metres): a plantigrade
    clip on a digitigrade rig leaves the paws off the floor otherwise. The rig's pose comes back afterwards
    (lpk.stages.pose.held_pose). Changes `poses` in place. Returns [the smallest, the largest] shift in
    metres. Raises ValueError for a part the body lacks."""
    ob = bpy.data.objects[body]
    names = list(ob['parts'])
    missing = [p for p in parts if p not in names]
    if missing:
        raise ValueError('plant: the body has no part %s' % ', '.join(map(repr, missing)))
    ids = {names.index(p) for p in parts}
    pa = ob.data.attributes['part'].data
    idx = [i for i in range(len(pa)) if pa[i].value in ids]
    arm = bpy.data.objects[rig]
    to_local = (arm.matrix_world.to_3x3() @ arm.data.bones[root].matrix_local.to_3x3()).inverted()
    lo, hi = math.inf, -math.inf
    with pose_stage.held_pose(rig, None):
        for f in sorted(poses):
            pose_stage.set_pose(rig, poses[f])
            ev = ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
            z = min((ev.matrix_world @ ev.data.vertices[i].co).z for i in idx)
            dz = floor - z
            lo, hi = min(lo, dz), max(hi, dz)
            entry = dict(poses[f].get(root, {}))
            loc = Vector(entry.get('loc', (0.0, 0.0, 0.0))) + to_local @ Vector((0.0, 0.0, dz))
            entry['loc'] = tuple(round(c, 6) for c in loc)
            poses[f][root] = entry
    return [round(lo, 4), round(hi, 4)]
