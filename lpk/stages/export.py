"""Export of a built model (the mesh, with its armature when it has a rig) and its baked textures: export_fbx
(the FBX for Unity), export() by an export profile (lpk/profiles: FBX or binary glTF, bones renamed by role),
compare_import(), which re-imports an exported file and lists where it differs from the model, and
export_output(), an export in the rest pose with the final material followed by that comparison. A model
without a rig (rig_name None) goes out as its mesh alone: the profile's skeleton keys act on no bone. The FBX
bytes are made deterministic after writing (fbx_fixed_time, fbx_fixed_ids)."""
import os
import re
import struct
from contextlib import contextmanager, nullcontext
from pathlib import Path

import bpy
import numpy as np

from lpk import profiles as _profiles
from lpk.stages import pose, preview

# How far the re-imported file's size may differ from the model's along an axis, in metres, plus the
# share below. The size difference compare_import looks for is a unit or scale error, which changes a size by
# a factor (a centimetre or inch unit, a scale left unapplied); the float rounding of the axis and unit
# conversions moves it by about a millionth of it. A millimetre plus a thousandth of the size lies far
# above that rounding and far below any such factor.
SIZE_METRES = 1e-3
# The share of the model's size along the axis that compare_import adds to SIZE_METRES.
SIZE_SHARE = 1e-3
# The kinds of difference compare_import reports, in the order it looks for them.
DIFF_KINDS = ('influences', 'import', 'armatures', 'bones', 'parents', 'meshes', 'triangles', 'uv layers', 'images',
              'skin', 'size')


# The creation time written into an FBX header in place of the exporter's current local time, so that a
# re-export of the same scene gives the same bytes: (field, value) in the order the header holds them.
FBX_CREATION_TIME = (('Year', 2000), ('Month', 1), ('Day', 1), ('Hour', 0), ('Minute', 0), ('Second', 0),
                     ('Millisecond', 0))


def fbx_fixed_time(data):
    """The bytes of a binary FBX file with the fields of its header's CreationTimeStamp set to
    FBX_CREATION_TIME. Each field is a node holding one 32-bit integer property ('I'), rewritten in
    place: the length and every other byte stay as written. Raises ValueError when the header has no
    CreationTimeStamp or lacks one of its fields."""
    start = data.find(b'CreationTimeStamp')
    if start < 0:
        raise ValueError('the FBX file has no CreationTimeStamp in its header')
    out = bytearray(data)
    pos = start
    for name, value in FBX_CREATION_TIME:
        key = bytes([len(name)]) + name.encode('ascii') + b'I'
        i = out.find(key, pos, start + 1024)
        if i < 0:
            raise ValueError('the FBX header has no %s field in its CreationTimeStamp' % name)
        j = i + len(key)
        out[j:j + 4] = struct.pack('<i', value)
        pos = j + 4
    return bytes(out)


# The first bytes of a binary FBX file.
FBX_MAGIC = b'Kaydara FBX Binary  \x00'
# The length of a binary FBX file's header: FBX_MAGIC, two more bytes and the 32-bit version.
FBX_HEADER = 27
# The byte size of each scalar property type of a binary FBX node record.
FBX_SCALARS = {b'Y': 2, b'C': 1, b'I': 4, b'F': 4, b'D': 8, b'L': 8}
# The array property types: a count, an encoding and a byte length, then that many bytes.
FBX_ARRAYS = (b'f', b'd', b'l', b'i', b'b')
# The string property types: a byte length, then that many bytes.
FBX_STRINGS = (b'S', b'R')
# The top-level nodes whose children are objects: each child's first property is the object's id.
FBX_ID_SECTIONS = (b'Objects', b'Documents')


def fbx_records(data):
    """Every node record of a binary FBX file in file order, as (path, name, props): path is the tuple of
    the names of the nodes it lies in, props its properties as (type, offset of the value, value bytes),
    with None as an array's value. Raises ValueError when the data is not a binary FBX file or a property
    has a type outside the format."""
    if not data.startswith(FBX_MAGIC):
        raise ValueError('not a binary FBX file')
    # A node record starts with three offsets and its name's length: 64-bit offsets from version 7500 on.
    fmt, head = ('<QQQ', 25) if struct.unpack_from('<I', data, FBX_HEADER - 4)[0] >= 7500 else ('<III', 13)

    def nodes(pos, path):
        while True:
            stop, count, _ = struct.unpack_from(fmt, data, pos)
            if stop == 0:
                return
            size = data[pos + head - 1]
            name = data[pos + head:pos + head + size]
            p = pos + head + size
            props = []
            for _ in range(count):
                kind = data[p:p + 1]
                p += 1
                if kind in FBX_SCALARS:
                    props.append((kind, p, data[p:p + FBX_SCALARS[kind]]))
                    p += FBX_SCALARS[kind]
                elif kind in FBX_STRINGS:
                    n = struct.unpack_from('<I', data, p)[0]
                    props.append((kind, p + 4, data[p + 4:p + 4 + n]))
                    p += 4 + n
                elif kind in FBX_ARRAYS:
                    props.append((kind, p, None))
                    p += 12 + struct.unpack_from('<I', data, p + 8)[0]
                else:
                    raise ValueError('the FBX node %r at byte %d has a property of unknown type %r'
                                     % (name.decode('ascii', 'replace'), pos, kind))
            yield path, name, props
            if p < stop:
                yield from nodes(p, path + (name,))
            pos = stop

    yield from nodes(FBX_HEADER, ())


def fbx_fixed_ids(data):
    """The bytes of a binary FBX file with its object ids renumbered 1, 2, ... in the order the objects
    appear. The exporter derives an object's id from Python's string hash, which differs between Blender
    sessions, so one scene exported in two sessions differs by its ids. An object's id is the first property
    (a 64-bit integer, 'L') of a child of an FBX_ID_SECTIONS node; every 'L' property holding one of these
    ids (the connections, the bind pose's nodes) is rewritten in place, and every other byte stays as
    written. Raises ValueError as fbx_records does."""
    records = list(fbx_records(data))
    ids = {}
    for path, _, props in records:
        if len(path) == 1 and path[0] in FBX_ID_SECTIONS and props and props[0][0] == b'L':
            ids.setdefault(struct.unpack('<q', props[0][2])[0], len(ids) + 1)
    out = bytearray(data)
    for _, _, props in records:
        for kind, at, value in props:
            if kind == b'L' and struct.unpack('<q', value)[0] in ids:
                out[at:at + 8] = struct.pack('<q', ids[struct.unpack('<q', value)[0]])
    return bytes(out)


def export_fbx(obj_name, rig_name, out_dir, file_name, deform_only=True, bake_space_transform=True,
               primary_bone_axis='Y', secondary_bone_axis='X', restore_paths=False, settings=None):
    """Writes <out_dir>/<file_name>.fbx and every image used by the mesh's materials as PNG
    beside it. rig_name: the armature object, or None to write the mesh alone. The armature is exported
    in its rest pose, and stays in it afterwards: the pose is not put back. Only deform bones go out and no
    leaf bones are added, so Unity's Humanoid mapping sees exactly the authored skeleton.
    The images are re-pointed to their PNG copies before the export, because the FBX references
    each image by its file path (relative to the FBX). restore_paths=False leaves them pointing at
    the copies; True puts each image's previous file path and format back after the export, except
    images that had no file path (generated ones), whose only file is now the copy.
    settings: export_scene.fbx keyword arguments that override the ones this function passes (an
    export profile's 'exporter'); the file path and the selection stay this function's.
    Returns {'fbx': path, 'images': [png paths], 'bytes': file size}, plus 'paths_restored': count
    with restore_paths."""
    if settings and {'filepath', 'use_selection'} & set(settings):
        raise ValueError('export_fbx settings cannot set filepath or use_selection')
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ob = bpy.data.objects[obj_name]
    rig = bpy.data.objects[rig_name] if rig_name else None
    images = []
    for m in ob.data.materials:
        for n in m.node_tree.nodes:
            if n.type == 'TEX_IMAGE' and n.image and n.image not in images:
                images.append(n.image)
    previous = [(img, img.filepath_raw, img.file_format) for img in images] if restore_paths else []
    for img in images:
        img.filepath_raw = str(out / (img.name + '.png'))
        img.file_format = 'PNG'
        img.save()

    if rig is not None:
        for pb in rig.pose.bones:
            pb.matrix_basis.identity()
    shown = _show_only(ob, rig)
    path = out / (file_name + '.fbx')
    args = dict(
        filepath=str(path), use_selection=True, object_types={'ARMATURE', 'MESH'},
        apply_unit_scale=True, apply_scale_options='FBX_SCALE_ALL',
        axis_forward='-Z', axis_up='Y', bake_space_transform=bake_space_transform,
        mesh_smooth_type='FACE', use_mesh_modifiers=False,
        add_leaf_bones=False, primary_bone_axis=primary_bone_axis, secondary_bone_axis=secondary_bone_axis,
        use_armature_deform_only=deform_only, bake_anim=False,
        path_mode='RELATIVE', embed_textures=False)
    if settings:
        args.update(settings)
    try:
        with _window():
            bpy.ops.export_scene.fbx(**args)
    finally:
        for o, h in shown.items():
            o.hide_set(h)
    restored = 0
    for img, filepath, file_format in previous:
        if filepath:
            img.filepath_raw = filepath
            img.file_format = file_format
            restored += 1
    path.write_bytes(fbx_fixed_ids(fbx_fixed_time(path.read_bytes())))
    rep = {'fbx': str(path), 'images': [str(out / (i.name + '.png')) for i in images],
           'bytes': path.stat().st_size}
    if restore_paths:
        rep['paths_restored'] = restored
    return rep


# The bpy.data collections compare_import removes the import's new data blocks from.
_DATA = ('objects', 'collections', 'meshes', 'armatures', 'materials', 'images', 'textures', 'node_groups',
         'actions', 'cameras', 'lights', 'curves', 'worlds')


def _resolve(profile):
    """A profile dict, validated, from a profile dict, a shipped name or a JSON path (lpk.profiles.load).
    Raises ValueError naming the profile's problems."""
    if isinstance(profile, dict):
        problems = _profiles.validate(profile)
        if problems:
            raise ValueError('export profile %s: %s' % (profile.get('name'), '; '.join(problems)))
        return profile
    return _profiles.load(profile)


def _op_args(op, kwargs):
    """The keyword arguments this Blender's operator has, and the sorted names it lacks."""
    have = set(op.get_rna_type().properties.keys())
    return {k: v for k, v in kwargs.items() if k in have}, sorted(k for k in kwargs if k not in have)


def _rename_bones(rig, ob, renames):
    """Rename the armature's bones and the mesh's matching vertex groups through temporary names, so a
    swap of two names does not collide. Blender renames the groups of meshes deformed by the armature
    itself; the groups are renamed here only when it did not."""
    groups = [g.name for g in ob.vertex_groups]
    tmp = {old: '_lpk_rename_%d' % i for i, old in enumerate(renames)}
    for old, t in tmp.items():
        rig.data.bones[old].name = t
    for old, t in tmp.items():
        rig.data.bones[t].name = renames[old]
    if [g.name for g in ob.vertex_groups] == groups:
        for old, t in tmp.items():
            g = ob.vertex_groups.get(old)
            if g is not None:
                g.name = t
        for old, t in tmp.items():
            g = ob.vertex_groups.get(t)
            if g is not None:
                g.name = renames[old]


@contextmanager
def _window():
    """A context override onto the window that shows a 3D Viewport (lpk.stages.view.view3d_context): the
    exporters and importers read the selection from a window, which the context of a bridge call that has
    just loaded a file lacks. In background mode, where no window exists, the plain context."""
    from lpk.stages import view
    try:
        keywords = view.view3d_context()
    except RuntimeError:
        keywords = {}
    with bpy.context.temp_override(**keywords):
        yield


def _show_only(ob, rig):
    """Select and show ob and rig (None: no rig) alone, the rig active when there is one, else ob, for an
    exporter that writes the selection. Returns {object: its hidden state before}, for the caller to put
    back."""
    objs = [o for o in (ob, rig) if o is not None]
    hidden = {o: o.hide_get() for o in objs}
    vl = bpy.context.view_layer
    for o in vl.objects:
        o.select_set(False)
    for o in objs:
        o.hide_set(False)
        o.select_set(True)
    vl.objects.active = objs[-1]
    return hidden


@contextmanager
def _export_copy(ob, rig, renames):
    """Yields the objects to export: the model's own when nothing is renamed, else a temporary copy of
    the mesh and the armature (data included, animation dropped) with the bones renamed, carrying the
    originals' object and data names while the originals wait under '<name>.lpk_src', because the file
    names its nodes and meshes after them. The copies are deleted and the names put back on exit."""
    if not renames:
        yield ob, rig
        return
    names = (ob.name, ob.data.name, rig.name, rig.data.name)
    me, arm = ob.data.copy(), rig.data.copy()
    cob, crig = ob.copy(), rig.copy()
    cob.data, crig.data = me, arm
    try:
        for idb in (cob, crig, me, arm):
            if idb.animation_data:
                idb.animation_data_clear()
        coll = ob.users_collection[0]
        coll.objects.link(crig)
        coll.objects.link(cob)
        cob.parent = crig
        for m in cob.modifiers:
            if m.type == 'ARMATURE' and m.object == rig:
                m.object = crig
        _rename_bones(crig, cob, renames)
        ob.name, ob.data.name, rig.name, rig.data.name = (n + '.lpk_src' for n in names)
        cob.name, me.name, crig.name, arm.name = names
        yield cob, crig
    finally:
        bpy.data.objects.remove(cob, do_unlink=True)
        bpy.data.objects.remove(crig, do_unlink=True)
        bpy.context.view_layer.update()  # a removed object stays as None in view_layer.objects until an update
        bpy.data.meshes.remove(me)
        bpy.data.armatures.remove(arm)
        ob.name, ob.data.name, rig.name, rig.data.name = names


def _images(ob, linked=False):
    """Images of the mesh's Image Texture nodes in material order; linked=True keeps only nodes whose
    colour output is connected, the ones an exporter can carry."""
    out = []
    for m in ob.data.materials:
        if not (m and m.node_tree):
            continue
        for n in m.node_tree.nodes:
            if n.type == 'TEX_IMAGE' and n.image and n.image not in out:
                if not linked or any(link for s in n.outputs for link in s.links):
                    out.append(n.image)
    return out


def _export_glb(ob, rig, path, exporter):
    """ob and rig (None: the mesh alone), selected and shown for the call, written to path by the glTF
    exporter with the exporter arguments it has. Returns {'path', 'bytes': the file size, 'images': the names of the
    images the file embeds, 'ignored': the exporter arguments this Blender's exporter does not have}."""
    args, ignored = _op_args(bpy.ops.export_scene.gltf, exporter)
    hidden = _show_only(ob, rig)
    try:
        with _window():
            bpy.ops.export_scene.gltf(filepath=str(path), export_format='GLB', use_selection=True, **args)
    finally:
        for o, h in hidden.items():
            o.hide_set(h)
    return {'path': str(path), 'bytes': path.stat().st_size, 'images': [i.name for i in _images(ob)],
            'ignored': ignored}


def export(obj_name, rig_name, out_dir, file_name, profile='unity_humanoid', restore_paths=False):
    """Export the mesh and its armature (rig_name None: the mesh alone) by an export profile:
    <out_dir>/<file_name>.fbx through export_fbx with the profile's exporter arguments (images as PNG files
    beside it), or <out_dir>/<file_name>.glb through the glTF exporter (images embedded, rest pose, no
    modifiers applied). Bones the profile renames by role are renamed on a temporary copy of the mesh and the
    armature only (see _export_copy); the model keeps its names. The selection and the active object are put
    back afterwards. With unity_humanoid this is exactly export_fbx's export.
    profile: a shipped name, a JSON path or a profile dict. restore_paths: export_fbx's (FBX only).
    Returns {'profile', 'format', 'path', 'bytes', 'images', 'renamed': {old: new}}: 'images' are the
    PNG paths beside an FBX, or the names of the images a .glb embeds, which also gets 'ignored':
    exporter arguments this Blender's exporter does not have; an FBX written with restore_paths gets
    export_fbx's 'paths_restored'. compare_import(path, ...) re-imports the file and compares it with the
    model."""
    p = _resolve(profile)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ob = bpy.data.objects[obj_name]
    rig = bpy.data.objects[rig_name] if rig_name else None
    renames = _profiles.bone_renames([b.name for b in rig.data.bones], p) if rig is not None else {}
    vl = bpy.context.view_layer
    selected = {o.name for o in vl.objects if o.select_get()}
    active = vl.objects.active
    try:
        with _export_copy(ob, rig, renames) as (eob, erig):
            if p['format'] == 'fbx':
                r = export_fbx(eob.name, erig.name if erig else None, out_dir, file_name,
                               restore_paths=restore_paths, settings=p['exporter'])
                rep = {'path': r['fbx'], 'bytes': r['bytes'], 'images': r['images']}
                if 'paths_restored' in r:
                    rep['paths_restored'] = r['paths_restored']
            else:
                rep = _export_glb(eob, erig, out / (file_name + '.glb'), p['exporter'])
    finally:
        for o in vl.objects:
            o.select_set(o.name in selected)
        vl.objects.active = active
    return dict(rep, profile=p['name'], format=p['format'], renamed=renames)


def _norm_image(name):
    """An image name without a file extension or Blender's .001 suffix: importers name images after
    their files, and a name already taken gets a suffix."""
    name = re.sub(r'\.[0-9]{3}$', '', name)
    name = re.sub(r'\.(png|jpe?g|webp|tga|tiff?|exr|bmp)$', '', name, flags=re.IGNORECASE)
    return re.sub(r'\.[0-9]{3}$', '', name)


def _tris(me):
    return sum(len(p.vertices) - 2 for p in me.polygons)


def _extent(objs):
    """World-space size (x, y, z) of the meshes' vertices, modifiers not applied."""
    pts = []
    for o in objs:
        n = len(o.data.vertices)
        co = np.empty(n * 3, np.float32)
        o.data.vertices.foreach_get('co', co)
        m = np.array(o.matrix_world, np.float64)
        pts.append(co.reshape(n, 3).astype(np.float64) @ m[:3, :3].T + m[:3, 3])
    pts = np.concatenate(pts) if pts else np.zeros((0, 3))
    return tuple(float(x) for x in (pts.max(0) - pts.min(0))) if len(pts) else (0.0, 0.0, 0.0)


def _profile_for(path, profile):
    """The profile `profile` resolves to (_resolve), or for None the shipped default of the file's format:
    glb_generic for .glb and .gltf, unity_humanoid otherwise."""
    if profile is not None:
        return _resolve(profile)
    ext = os.path.splitext(str(path))[1].lower()
    return _profiles.load('glb_generic' if ext in ('.glb', '.gltf') else 'unity_humanoid')


def _import(path, p):
    ext = os.path.splitext(str(path))[1].lower()
    if ext == '.fbx':
        op = bpy.ops.import_scene.fbx
        ex = p['exporter']
        args = dict(use_anim=False, use_image_search=False, use_custom_props=False,
                    ignore_leaf_bones=p['leaf_bones'], mtl_name_collision_mode='MAKE_UNIQUE',
                    primary_bone_axis=ex.get('primary_bone_axis', 'Y'),
                    secondary_bone_axis=ex.get('secondary_bone_axis', 'X'))
    elif ext in ('.glb', '.gltf'):
        op = bpy.ops.import_scene.gltf
        args = dict(import_pack_images=True, disable_bone_shape=True, import_scene_extras=False)
    else:
        raise ValueError('compare_import reads .fbx, .glb or .gltf, not %s' % path)
    with _window():
        op(filepath=str(path), **_op_args(op, args)[0])


def compare_import(path, obj_name, rig_name, profile=None):
    """Re-import an exported file into a scratch collection and compare it with the source objects:
    bone names (after the profile's renames), parents and count, the mesh object count, triangle count,
    UV layer count, image names, the world-space size (both importers undo the export's axis
    conversion, so sizes compare directly), and that the mesh is still skinned; and the model's bone
    influences per vertex against the profile's influence_limit. rig_name None: a model without a rig,
    whose file holds no armature and no bone and whose mesh is not skinned. Everything the import made is
    deleted afterwards; the selection, the active object and the active collection are put back.
    profile: the profile the file was written with (a dict, shipped name or JSON path); None takes
    unity_humanoid for .fbx and glb_generic for .glb and .gltf.
    The expected bones are the deform bones and their parents with deform_only, else all; source
    images are those of Image Texture nodes whose output is connected (exporters carry no others);
    image names compare without file extension and .001 suffixes; sizes differ when they are further
    apart than SIZE_METRES plus SIZE_SHARE of the model's.
    Returns {'diffs': [{'kind': one of DIFF_KINDS, 'text': the difference}] in DIFF_KINDS order, empty when
    the file matches the model, 'profile': its name, 'path', 'bones': imported bone count, 'triangles':
    imported triangle count, 'influences': the most bones weighting one vertex of the model}. An import
    that fails gives one 'import' difference and counts of 0."""
    p = _profile_for(path, profile)
    ob = bpy.data.objects[obj_name]
    rig = bpy.data.objects[rig_name] if rig_name else None
    bones = list(rig.data.bones) if rig is not None else []
    renames = _profiles.bone_renames([b.name for b in bones], p)
    keep = set()
    for b in bones:
        if b.use_deform or not p['deform_only']:
            while b is not None and b.name not in keep:
                keep.add(b.name)
                b = b.parent
    want = {renames.get(b.name, b.name): (renames.get(b.parent.name, b.parent.name) if b.parent else None)
            for b in bones if b.name in keep}
    src_tris, src_uv = _tris(ob.data), len(ob.data.uv_layers)
    src_images = {_norm_image(i.name) for i in _images(ob, linked=True)}
    src_size = _extent([ob])
    influences = max((sum(1 for g in v.groups if g.weight > 0) for v in ob.data.vertices), default=0)

    diffs = []

    def differ(kind, texts):
        diffs.extend({'kind': kind, 'text': t} for t in texts)

    def report():
        return {'diffs': diffs, 'profile': p['name'], 'path': str(path), 'bones': len(got), 'triangles': tris,
                'influences': influences}
    if influences > p['influence_limit']:
        differ('influences', ['influences per vertex: %d > limit %d' % (influences, p['influence_limit'])])
    vl, scene = bpy.context.view_layer, bpy.context.scene
    selected = {o.name for o in vl.objects if o.select_get()}
    active, active_coll = vl.objects.active, vl.active_layer_collection
    before = {a: {i.as_pointer() for i in getattr(bpy.data, a)} for a in _DATA if hasattr(bpy.data, a)}
    scratch = bpy.data.collections.new('lpk_reimport')
    scene.collection.children.link(scratch)
    got, tris = {}, 0
    try:
        lc = vl.layer_collection.children.get(scratch.name)
        if lc is not None:
            vl.active_layer_collection = lc
        try:
            _import(path, p)
        except RuntimeError as e:
            differ('import', ['import failed: %s' % str(e)[-300:]])
            return report()
        vl.update()
        new = [o for o in bpy.data.objects if o.as_pointer() not in before['objects']]
        arms = [o for o in new if o.type == 'ARMATURE']
        meshes = [o for o in new if o.type == 'MESH']
        if len(arms) != (rig is not None):
            differ('armatures', ['armatures: %d != %d' % (rig is not None, len(arms))])
        for a in arms:
            for b in a.data.bones:
                got[b.name] = b.parent.name if b.parent else None
        if len(got) != len(want):
            differ('bones', ['bones: %d != %d' % (len(want), len(got))])
        differ('bones', ['bone missing: %s' % n for n in sorted(set(want) - set(got))])
        differ('bones', ['bone extra: %s' % n for n in sorted(set(got) - set(want))])
        differ('parents', ['parent of %s: %s != %s' % (n, want[n], got[n]) for n in sorted(set(want) & set(got))
                           if want[n] != got[n]])
        if len(meshes) != 1:
            differ('meshes', ['mesh objects: 1 != %d' % len(meshes)])
        tris = sum(_tris(o.data) for o in meshes)
        if tris != src_tris:
            differ('triangles', ['triangles: %d != %d' % (src_tris, tris)])
        uv = max((len(o.data.uv_layers) for o in meshes), default=0)
        if uv != src_uv:
            differ('uv layers', ['uv layers: %d != %d' % (src_uv, uv)])
        images = {_norm_image(i.name) for o in meshes for i in _images(o)}
        differ('images', ['image missing: %s' % n for n in sorted(src_images - images)])
        differ('images', ['image extra: %s' % n for n in sorted(images - src_images)])
        for o in meshes if rig is not None else ():
            deformed = (any(m.type == 'ARMATURE' and m.object in arms for m in o.modifiers)
                        or (o.parent in arms and o.parent_type == 'ARMATURE'))
            if not (len(o.vertex_groups) and deformed):
                differ('skin', ['mesh %s is not skinned to the imported armature' % o.name])
        size = _extent(meshes)
        for axis, a, b in zip('xyz', src_size, size):
            if abs(a - b) > SIZE_METRES + SIZE_SHARE * abs(a):
                differ('size', ['size %s: %.4f != %.4f m' % (axis, a, b)])
    finally:
        for a in _DATA:
            if a not in before:
                continue
            coll = getattr(bpy.data, a)
            for i in [i for i in coll if i.as_pointer() not in before[a]]:
                if a == 'objects':
                    coll.remove(i, do_unlink=True)
                else:
                    coll.remove(i)
        vl.active_layer_collection = active_coll
        for o in vl.objects:
            o.select_set(o.name in selected)
        vl.objects.active = active
    return report()


def export_output(obj_name, rig_name, out_dir, file_name, profile):
    """One export of the body `obj_name` and its rig `rig_name` (None: a model without a rig) by `profile` (a
    profile dict, shipped name or JSON path) to <out_dir>/<file_name> plus the profile's extension (export),
    re-imported and compared with the model (compare_import). For the call only, the rig stands in its rest
    pose (lpk.stages.pose.held_pose) and the body's slots show its mesh materials, the bake's final material
    (lpk.stages.preview.mesh_materials); the pose and display link it found come back afterwards, also after
    an error. Images saved beside an FBX get their earlier file paths back (export's restore_paths), so the
    bake's atlas image keeps its own file. Returns export's report plus 'reimport': compare_import's."""
    p = _resolve(profile)
    ob = bpy.data.objects[obj_name]
    with pose.held_pose(rig_name) if rig_name else nullcontext(), preview.mesh_materials(ob):
        rep = export(obj_name, rig_name, out_dir, file_name, profile=p, restore_paths=True)
        rep['reimport'] = compare_import(rep['path'], obj_name, rig_name, profile=p)
    return rep
