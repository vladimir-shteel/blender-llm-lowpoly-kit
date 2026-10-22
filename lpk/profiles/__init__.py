"""Export profiles: the profiles shipped as lpk/profiles/<name>.json, and model-supplied profiles, JSON files
of the same shape that carry "schema": "lpk.profile/1" as an extra key (SCHEMA; load refuses one without it,
or with another value, before it validates the keys).

Keys:
  name, description
  format           'fbx' | 'glb'
  skeleton         the skeleton template (lpk/skeletons) that gives each bone its role
  bone_map         {role: name in the file}; roles not in it keep the model's bone names ({} keeps all)
  deform_only      only deform bones (and their parents) go out
  leaf_bones       the exporter's extra end bones
  influence_limit  the target's bone influences per vertex; the re-import comparison reports a model whose
                   weights exceed it
  axes             {'forward', 'up'}: the file axes Blender's +Y and +Z become (the FBX exporter's
                   axis_forward / axis_up; the glTF exporter's fixed conversion is -Z / Y)
  textures         'files' (images saved beside the file, relative paths) | 'embedded'
  exporter         the exporter operator's keyword arguments (export_scene.fbx or export_scene.gltf),
                   without the file path and selection, which the export sets
The summary keys and the exporter arguments must agree; validate() lists where they do not.
Pure Python, no bpy."""
import json
import os
import re

from lpk import skeletons

_DIR = os.path.dirname(os.path.abspath(__file__))
FORMATS = ('fbx', 'glb')
TEXTURES = ('files', 'embedded')
AXES = ('X', 'Y', 'Z', '-X', '-Y', '-Z')
REQUIRED = {'name': str, 'description': str, 'format': str, 'skeleton': str, 'bone_map': dict, 'deform_only': bool,
            'leaf_bones': bool, 'influence_limit': int, 'axes': dict, 'textures': str, 'exporter': dict}
RESERVED = {'fbx': ('filepath', 'check_existing', 'use_selection', 'object_types'),
            'glb': ('filepath', 'check_existing', 'use_selection', 'export_format')}
# summary key -> exporter argument that must equal it
AGREE = {'fbx': (('deform_only', 'use_armature_deform_only'), ('leaf_bones', 'add_leaf_bones')),
         'glb': (('deform_only', 'export_def_bones'), ('leaf_bones', 'export_leaf_bone'),
                 ('influence_limit', 'export_influence_nb'))}
# The schema key and value a model-supplied profile carries; the shipped profiles are the kit's own data and
# carry none.
SCHEMA_KEY = 'schema'
SCHEMA = 'lpk.profile/1'


def names():
    """The profile names shipped in lpk/profiles, sorted."""
    return sorted(f[:-5] for f in os.listdir(_DIR) if f.endswith('.json'))


def shipped(name_or_path):
    """Whether a profile reference names a shipped profile: a name without '.json' and without a directory
    separator (a slash or a backslash). Any other reference is the path of a model-supplied profile."""
    return not (name_or_path.endswith('.json') or any(c in name_or_path for c in ('/', '\\', os.sep)))


def path_of(name_or_path):
    """The JSON file of a shipped profile name, or the given path, absolute, for a model-supplied profile
    (shipped)."""
    return os.path.join(_DIR, name_or_path + '.json') if shipped(name_or_path) else os.path.abspath(name_or_path)


def _is_role(role, template):
    if role in skeletons.names_by_role(template):
        return True
    return any(re.fullmatch(re.escape(c['role_prefix']) + r'[1-9][0-9]*', role)
               for c in skeletons.load(template).get('chains', ()))


def validate(p):
    """Problems of a profile dict as a list of strings; empty when it is usable."""
    out = []
    for key, kind in REQUIRED.items():
        if key not in p:
            out.append('missing key %r' % key)
        elif not isinstance(p[key], kind) or (kind is int and isinstance(p[key], bool)):
            out.append('%r must be %s' % (key, kind.__name__))
    if out:
        return out
    fmt = p['format']
    if fmt not in FORMATS:
        return out + ['format %r: use one of %s' % (fmt, ', '.join(FORMATS))]
    if p['skeleton'] not in skeletons.names():
        out.append('skeleton %r: templates are %s' % (p['skeleton'], ', '.join(skeletons.names())))
    else:
        for role, name in p['bone_map'].items():
            if not _is_role(role, p['skeleton']):
                out.append('bone_map: %r is not a role of %s' % (role, p['skeleton']))
            if not isinstance(name, str) or not name:
                out.append('bone_map: %r must map to a bone name' % role)
        targets = [n for n in p['bone_map'].values() if isinstance(n, str)]
        for n in sorted({n for n in targets if targets.count(n) > 1}):
            out.append('bone_map: %r is the name of more than one role' % n)
    if p['influence_limit'] < 1:
        out.append('influence_limit must be at least 1')
    ax = p['axes']
    if ax.get('forward') not in AXES or ax.get('up') not in AXES or ax['forward'][-1] == ax['up'][-1]:
        out.append('axes: forward and up must be two different axes of %s' % ', '.join(AXES))
    if p['textures'] not in TEXTURES:
        out.append('textures %r: use one of %s' % (p['textures'], ', '.join(TEXTURES)))
    ex = p['exporter']
    for key in RESERVED[fmt]:
        if key in ex:
            out.append('exporter: %r is set by the export, not the profile' % key)
    for key, arg in AGREE[fmt]:
        if arg in ex and ex[arg] != p[key]:
            out.append('%s is %r but exporter %s is %r' % (key, p[key], arg, ex[arg]))
    if fmt == 'fbx':
        if (ex.get('axis_forward'), ex.get('axis_up')) != (ax.get('forward'), ax.get('up')):
            out.append('axes do not match exporter axis_forward / axis_up')
        if ex.get('embed_textures', False) != (p['textures'] == 'embedded'):
            out.append('textures %r does not match exporter embed_textures' % p['textures'])
    else:
        if not ex.get('export_yup', True) or (ax.get('forward'), ax.get('up')) != ('-Z', 'Y'):
            out.append('glb axes are the exporter\'s +Y up conversion: export_yup true, axes -Z / Y')
        if p['textures'] != 'embedded':
            out.append('a .glb embeds its images: textures must be \'embedded\'')
    return out


def load(name_or_path):
    """A profile, validated: a shipped profile by its name (names()), read as the kit ships it, or a
    model-supplied profile by its JSON path (shipped, path_of), which must carry SCHEMA under SCHEMA_KEY and is
    returned without that key. Raises ValueError for a name or path with no file, for a model-supplied file
    that is not a JSON object carrying SCHEMA, and naming the problems of a profile validate() refuses."""
    path = path_of(name_or_path)
    if not os.path.isfile(path):
        raise ValueError('no export profile %r (%s); shipped profiles: %s' % (name_or_path, path, ', '.join(names())))
    with open(path, encoding='utf-8') as f:
        p = json.load(f)
    if not shipped(name_or_path):
        found = p.get(SCHEMA_KEY) if isinstance(p, dict) else None
        if found != SCHEMA:
            raise ValueError('export profile %s: %s; a model-supplied profile carries "%s": "%s" (a copy of a '
                             'shipped profile adds it)' % (path, 'schema %r' % (found,) if found is not None
                                                           else 'no schema', SCHEMA_KEY, SCHEMA))
        p = {k: v for k, v in p.items() if k != SCHEMA_KEY}
    problems = validate(p)
    if problems:
        raise ValueError('export profile %s: %s' % (path, '; '.join(problems)))
    return p


def bone_renames(bone_names, profile):
    """{old: new} for the bones the profile renames: a bone whose role (in the profile's skeleton) is in
    bone_map takes the mapped name. Bones without a role or with an unmapped role keep their names.
    Raises ValueError when two bones would end up with one name."""
    out = {}
    for n in bone_names:
        role = skeletons.role_of(n, profile['skeleton'])
        new = profile['bone_map'].get(role) if role else None
        if new and new != n:
            out[n] = new
    final = [out.get(n, n) for n in bone_names]
    clash = sorted({n for n in final if final.count(n) > 1})
    if clash:
        raise ValueError('profile %s renames bones onto existing names: %s' % (profile['name'], ', '.join(clash)))
    return out
