"""Fingerprints of built models: every array a stage leaves on its objects, stored whole and hashed.

A snapshot saves the arrays of the named objects into one .npz (keys '<role>/<array>') and returns a
summary {role: {array: sha256}} plus the environment stamp and the material graphs of the mesh roles.
compare() diffs two .npz files array by array, so a mismatch can be measured (largest difference,
element count) instead of only detected; compare_materials() diffs the material graphs of two
summaries. Palette and part indices are stored with their name tables, so a renamed or reordered table
can be compared by name. Only snapshot(), env_stamp() and material_graphs() need Blender; the
comparisons run on any Python with numpy."""
import hashlib
import json
import os
import platform
import re
import sys

import numpy as np

VERSION = 1
MATERIAL_SETTINGS = ('use_nodes', 'blend_method', 'surface_render_method', 'use_backface_culling')
VALUE_NODES = ('ShaderNodeValue', 'ShaderNodeRGB')
_SKIP = object()


def _sha(a):
    a = np.ascontiguousarray(a)
    h = hashlib.sha256()
    h.update(str(a.dtype).encode() + str(a.shape).encode())
    h.update(a.tobytes())
    return h.hexdigest()


def _file_sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def env_stamp(**extra):
    """Blender build, Python, numpy, OS and the VHD add-on binary: a comparison across different stamps
    compares two machines, not two builds of a model. A failure to read the add-on is recorded as
    'vhd_error' instead of raising: a snapshot is taken after a stage has changed the scene, so a raise
    there would lose that stage's arrays."""
    import bpy
    import addon_utils
    stamp = {
        'fingerprint_version': VERSION,
        'blender': bpy.app.version_string,
        'build_hash': bpy.app.build_hash.decode() if isinstance(bpy.app.build_hash, bytes) else str(bpy.app.build_hash),
        'build_date': bpy.app.build_date.decode() if isinstance(bpy.app.build_date, bytes) else str(bpy.app.build_date),
        'python': sys.version.split()[0],
        'numpy': np.__version__,
        'os': platform.platform(),
        'cpu': platform.processor(),
    }
    try:
        for m in addon_utils.modules(refresh=False):
            if m.__name__.endswith('voxel_skinning') and addon_utils.check(m.__name__)[1]:
                stamp['vhd_version'] = '.'.join(str(x) for x in getattr(m, 'bl_info', {}).get('version', ()))
                exe = os.path.join(os.path.dirname(m.__file__), 'bin', 'Windows', 'x64', 'vhd.exe')
                if os.path.exists(exe):
                    stamp['vhd_sha256'] = _file_sha(exe)
    except Exception as e:
        stamp['vhd_error'] = '%s: %s' % (type(e).__name__, e)
    stamp.update(extra)
    return stamp


def _get(coll, attr, n, dtype, width=1):
    a = np.empty(n * width, dtype)
    if n:
        coll.foreach_get(attr, a)
    return a.reshape(n, width) if width > 1 else a


def mesh_arrays(ob):
    """Geometry in creation order (float32 as Blender stores it), topology, seams, the builder's layers
    with their name tables, UVs, corner colours and vertex-group weights in stored order."""
    me = ob.data
    nv, ne, nl, nf = len(me.vertices), len(me.edges), len(me.loops), len(me.polygons)
    out = {
        'co': _get(me.vertices, 'co', nv, np.float32, 3),
        'loop_vert': _get(me.loops, 'vertex_index', nl, np.int32),
        'face_start': _get(me.polygons, 'loop_start', nf, np.int32),
        'face_total': _get(me.polygons, 'loop_total', nf, np.int32),
        'edges': _get(me.edges, 'vertices', ne, np.int32, 2),
        'seam': _get(me.edges, 'use_seam', ne, bool),
        'matrix_world': np.array(ob.matrix_world, np.float32),
    }
    for name, domain in (('pal', 'FACE'), ('part', 'POINT'), ('join_loop', 'POINT')):
        at = me.attributes.get(name)
        if at is not None and at.domain == domain:
            out[name] = _get(at.data, 'value', len(at.data), np.int32)
    names = {}
    for key in ('palette', 'parts', 'bake_mask'):
        if key in ob:
            names[key] = [str(x) for x in ob[key]]
    for i, uv in enumerate(me.uv_layers):
        out['uv%d' % i] = _get(uv.uv, 'vector', nl, np.float32, 2)
        names['uv%d' % i] = [uv.name]
    col = me.color_attributes.get('Col')
    if col is not None:
        out['col'] = _get(col.data, 'color', len(col.data), np.float32, 4)
    if ob.vertex_groups:
        names['groups'] = [g.name for g in ob.vertex_groups]
        vi, gi, w = [], [], []
        for v in me.vertices:
            for g in v.groups:
                vi.append(v.index)
                gi.append(g.group)
                w.append(g.weight)
        out['w_vert'] = np.array(vi, np.int32)
        out['w_group'] = np.array(gi, np.int32)
        out['w_weight'] = np.array(w, np.float32)
    names['materials'] = [m.name if m else '' for m in me.materials]
    return out, names


def armature_arrays(ob):
    """Bones in stored order: names, parents, flags and rest matrices (the matrix carries the roll)."""
    bones = ob.data.bones
    names = {'bones': [b.name for b in bones], 'parents': [b.parent.name if b.parent else '' for b in bones]}
    out = {
        'connect': np.array([b.use_connect for b in bones], bool),
        'deform': np.array([b.use_deform for b in bones], bool),
        'head': np.array([tuple(b.head_local) for b in bones], np.float32).reshape(-1, 3),
        'tail': np.array([tuple(b.tail_local) for b in bones], np.float32).reshape(-1, 3),
        'matrix': np.array([np.array(b.matrix_local, np.float32) for b in bones], np.float32).reshape(-1, 4, 4),
        'matrix_world': np.array(ob.matrix_world, np.float32),
    }
    return out, names


def image_arrays(img):
    w, h = img.size
    px = np.empty(w * h * img.channels, np.float32)
    img.pixels.foreach_get(px)
    return {'pixels': px}, {'size': [str(w), str(h)]}


def _plain(v):
    """A property or socket value as JSON data: an ID by its name, a colour ramp by its settings and
    stops, a set as a sorted list, an array or vector as a list; _SKIP for any other struct (a texture
    mapping, an image user), which the caller leaves out."""
    import bpy
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, bpy.types.ID):
        return v.name
    if isinstance(v, bpy.types.ColorRamp):
        return {'interpolation': v.interpolation, 'color_mode': v.color_mode,
                'hue_interpolation': v.hue_interpolation,
                'elements': [[e.position, list(e.color)] for e in v.elements]}
    if isinstance(v, (set, frozenset)):
        return sorted(v)
    if isinstance(v, bpy.types.bpy_struct):
        return _SKIP
    try:
        return [_plain(x) for x in v]
    except TypeError:
        return _SKIP


def _node(n, base):
    """One node: its type, mute flag, its own properties (those the base Node class lacks: interpolation,
    operation, blend type, data type, image, colour ramp...) and the default values of its enabled
    unlinked inputs by socket identifier; a value node (VALUE_NODES) also gives its outputs' values,
    where it keeps its setting. A group node gives its tree's name, not the tree."""
    props = {}
    for p in n.bl_rna.properties:
        if p.identifier in base or p.type == 'COLLECTION':
            continue
        v = _plain(getattr(n, p.identifier))
        if v is not _SKIP:
            props[p.identifier] = v
    out = {'type': n.bl_idname, 'mute': n.mute, 'props': props, 'inputs': {}}
    for s in n.inputs:
        if s.enabled and not s.is_linked and hasattr(s, 'default_value'):
            v = _plain(s.default_value)
            if v is not _SKIP:
                out['inputs'][s.identifier] = v
    if n.bl_idname in VALUE_NODES:
        out['outputs'] = {s.identifier: _plain(s.default_value) for s in n.outputs if hasattr(s, 'default_value')}
    return out


def _link(lk):
    return '%s.%s -> %s.%s%s%s' % (lk.from_node.name, lk.from_socket.identifier, lk.to_node.name,
                                   lk.to_socket.identifier, ' (muted)' if lk.is_muted else '',
                                   '' if lk.is_valid else ' (invalid)')


def material_graphs(ob):
    """The material slots of a mesh object in slot order, each {'link', 'material', 'settings', 'active',
    'nodes', 'links', 'images'}: the slot's link ('OBJECT' or 'DATA') and material name ('' for an
    empty slot, which has no other key); the settings of MATERIAL_SETTINGS this Blender has (those an
    exporter reads besides the node tree); the active node's name (Cycles bakes into the active image
    node); every node by name (_node); every link as 'from node.socket -> to node.socket' by socket
    identifier, sorted, a muted or invalid link marked so; the names of the images the nodes read,
    sorted. Values are exact (floats as Blender returns them), so two graphs built by the same code
    compare equal."""
    import bpy
    base = {p.identifier for p in bpy.types.Node.bl_rna.properties}
    out = []
    for slot in ob.material_slots:
        m = slot.material
        entry = {'link': slot.link, 'material': m.name if m else ''}
        out.append(entry)
        if m is None:
            continue
        entry['settings'] = {k: _plain(getattr(m, k)) for k in MATERIAL_SETTINGS if hasattr(m, k)}
        nt = m.node_tree
        nodes, links = (list(nt.nodes), list(nt.links)) if nt else ([], [])
        entry['active'] = nt.nodes.active.name if nt and nt.nodes.active else ''
        entry['nodes'] = {n.name: _node(n, base) for n in nodes}
        entry['links'] = sorted(_link(lk) for lk in links)
        entry['images'] = sorted({n.image.name for n in nodes
                                  if isinstance(getattr(n, 'image', None), bpy.types.Image)})
    return out


def snapshot(objects, npz_path, images=(), extra=None):
    """objects: {role: object name}; images: {role: image name}. Writes npz_path and npz_path + '.json'
    and returns the summary. Missing objects are recorded as missing, not skipped silently. The summary
    carries env_stamp() under 'env' and material_graphs() of every mesh role under 'materials'
    ({role: [slot, ...]}); both stay out of the .npz, so compare() never sees them."""
    import bpy
    arrays, summary = {}, {'objects': {}, 'missing': [], 'materials': {}, 'env': env_stamp()}
    items = [(r, n, 'object') for r, n in objects.items()] + [(r, n, 'image') for r, n in dict(images).items()]
    for role, name, kind in items:
        data = (bpy.data.images if kind == 'image' else bpy.data.objects).get(name)
        if data is None:
            summary['missing'].append(name)
            continue
        if kind == 'image':
            out, names = image_arrays(data)
        elif data.type == 'ARMATURE':
            out, names = armature_arrays(data)
        else:
            out, names = mesh_arrays(data)
            summary['materials'][role] = material_graphs(data)
        entry = {'name': name, 'names': names, 'sha': {}, 'shape': {}}
        for k, a in out.items():
            arrays[role + '/' + k] = a
            entry['sha'][k] = _sha(a)
            entry['shape'][k] = list(a.shape)
        for k, v in names.items():
            arrays[role + '/names.' + k] = np.array(v, dtype=str)
        summary['objects'][role] = entry
    if extra:
        summary['extra'] = extra
    os.makedirs(os.path.dirname(npz_path), exist_ok=True)
    np.savez_compressed(npz_path, **arrays)
    with open(npz_path + '.json', 'w', encoding='utf-8', newline='\n') as f:
        json.dump(summary, f, indent=1, sort_keys=True)
    return summary


def _names(z, role, key):
    k = role + '/names.' + key
    return [str(x) for x in z[k]] if k in z.files else None


def _by_name(z, role, array, table):
    """An index layer as names (pal -> palette names, part -> part names) when the table exists."""
    names = _names(z, role, table)
    a = z[role + '/' + array]
    return np.array(names, dtype=object)[a] if names else a


def weights_by_name(z, role):
    """{(vertex, group name): weight}: the weights without the order Blender keeps them in per vertex."""
    groups = _names(z, role, 'groups')
    v, g, w = z[role + '/w_vert'], z[role + '/w_group'], z[role + '/w_weight']
    return {(int(a), groups[int(b)]): float(c) for a, b, c in zip(v, g, w)}


def compare_weights(za, ra, zb, rb):
    """Weights compared by vertex and group name: membership changes and the largest value difference."""
    a, b = weights_by_name(za, ra), weights_by_name(zb, rb)
    only = set(a) ^ set(b)
    common = set(a) & set(b)
    d = [abs(a[k] - b[k]) for k in common]
    if not only and not any(d):
        return 'same'
    return '%d memberships differ, max diff %.3g in %d of %d' % (len(only), max(d or [0]), sum(1 for x in d if x),
                                                               len(common))


def compare(npz_a, npz_b, roles=None, role_map=None):
    """Array-by-array comparison: {role: {array: 'same' | description}}. role_map maps roles of b to
    roles of a when the two builds name their objects differently. pal and part are compared by name."""
    za, zb = np.load(npz_a), np.load(npz_b)
    role_map = role_map or {}
    ra = {k.split('/')[0] for k in za.files}
    rb = {role_map.get(k.split('/')[0], k.split('/')[0]) for k in zb.files}
    result = {}
    for role in sorted(roles or (ra | rb)):
        if role not in ra or role not in rb:
            result[role] = 'only in %s' % ('a' if role in ra else 'b')
            continue
        rb_name = next((k for k, v in role_map.items() if v == role), role)
        keys_a = {k.split('/', 1)[1] for k in za.files if k.split('/')[0] == role}
        keys_b = {k.split('/', 1)[1] for k in zb.files if k.split('/')[0] == rb_name}
        res = {}
        for key in sorted(keys_a | keys_b):
            if key not in keys_a or key not in keys_b:
                res[key] = 'only in %s' % ('a' if key in keys_a else 'b')
                continue
            if key in ('pal', 'part'):
                table = 'palette' if key == 'pal' else 'parts'
                a, b = _by_name(za, role, key, table), _by_name(zb, rb_name, key, table)
            else:
                a, b = za[role + '/' + key], zb[rb_name + '/' + key]
            if a.shape != b.shape:
                res[key] = 'shape %s vs %s' % (a.shape, b.shape)
            elif a.dtype.kind in 'fc':
                if np.array_equal(a, b, equal_nan=True):
                    res[key] = 'same'
                else:
                    d = np.abs(a.astype(np.float64) - b.astype(np.float64))
                    res[key] = 'max diff %.3g in %d of %d' % (np.nanmax(d), int(np.count_nonzero(d)), d.size)
            else:
                same = np.array_equal(a, b)
                res[key] = 'same' if same else '%d of %d differ' % (int(np.count_nonzero(a != b)), a.size)
        if 'w_weight' in keys_a and 'w_weight' in keys_b:
            res['weights_by_name'] = compare_weights(za, role, zb, rb_name)
        result[role] = res
    return result


def _at(where, key):
    return '%s.%s' % (where, key) if re.fullmatch(r'\w+', key) else '%s[%r]' % (where, key)


def _diff_tree(a, b, where, out):
    """Appends to out a line per difference of two nested summary values: dicts key by key, anything
    else whole."""
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append('%s: only in %s' % (_at(where, k), 'a' if k in a else 'b'))
            else:
                _diff_tree(a[k], b[k], _at(where, k), out)
    elif a != b:
        out.append('%s: %s vs %s' % (where, json.dumps(a), json.dumps(b)))


def compare_materials(json_a, json_b):
    """The 'materials' entries of two snapshot summaries (<npz>.json) compared role by role and slot
    by slot: a list of lines, one per difference, empty when the graphs are equal; None when either
    summary is missing or has no 'materials' entry (a snapshot from before they were recorded). A line
    names the place, such as body[0].nodes['Image Texture'].props.interpolation, and ends in
    '<a> vs <b>' or 'only in a' / 'only in b'; links and images are compared as sets, so one rewired
    link gives one line per side."""
    summaries = []
    for path in (json_a, json_b):
        if not os.path.exists(path):
            return None
        with open(path, encoding='utf-8') as f:
            summaries.append(json.load(f).get('materials'))
    a, b = summaries
    if a is None or b is None:
        return None
    out = []
    for role in sorted(set(a) | set(b)):
        if role not in a or role not in b:
            out.append('%s: only in %s' % (role, 'a' if role in a else 'b'))
            continue
        if len(a[role]) != len(b[role]):
            out.append('%s: %d slots vs %d' % (role, len(a[role]), len(b[role])))
        for i, (x, y) in enumerate(zip(a[role], b[role])):
            where = '%s[%d]' % (role, i)
            sets = {k: (x.pop(k, []), y.pop(k, [])) for k in ('links', 'images')}
            _diff_tree(x, y, where, out)
            for k, (sx, sy) in sets.items():
                for item in sorted(set(sx) ^ set(sy)):
                    out.append('%s %r: only in %s' % (_at(where, k), item, 'a' if item in sx else 'b'))
    return out
