"""Host tests (no Blender) of the export profiles, the skeleton templates and the pure parts of rig.py.

rig.py imports bpy, so the functions under test are read from their source with ast and,
where they are pure, executed with a stand-in for mathutils.Vector. Run with pytest, or directly:
python tests/test_profiles.py"""
import ast
import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lpk import profiles, skeletons  # noqa: E402

RIG = ROOT / 'lpk' / 'stages' / 'rig.py'


class _Raises:
    def __init__(self, exc):
        self.exc = exc

    def __enter__(self):
        return self

    def __exit__(self, kind, value, tb):
        assert kind is not None and issubclass(kind, self.exc), 'expected %s' % self.exc.__name__
        return True


def _functions(path, *names, **globs):
    """Execute the named top-level functions of a module's source in a namespace with `globs`."""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    mod = ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names],
                     type_ignores=[])
    ns = dict(globs)
    exec(compile(mod, str(path), 'exec'), ns)
    return [ns[n] for n in names]


def test_every_profile_loads_and_validates():
    shipped = profiles.names()
    assert {'fbx_generic', 'glb_generic', 'unity_humanoid'} <= set(shipped)
    for name in shipped:
        p = profiles.load(name)
        assert p['name'] == name
        for key, kind in profiles.REQUIRED.items():
            assert isinstance(p[key], kind), (name, key)
        assert profiles.validate(p) == [], name
        assert p['skeleton'] in skeletons.names()


def test_fbx_generic_names_bones_by_role():
    p, u = profiles.load('fbx_generic'), profiles.load('unity_humanoid')
    assert p['format'] == 'fbx' and p['leaf_bones'] is False
    assert p['axes'] == u['axes'] and p['exporter'] == u['exporter']
    assert p['bone_map'] == skeletons.names_by_role(p['skeleton'])
    assert profiles.bone_renames([b['name'] for b in skeletons.load('biped')['bones']], p) == {}


def test_glb_generic():
    p = profiles.load('glb_generic')
    ex = p['exporter']
    assert (p['format'], p['textures'], p['deform_only']) == ('glb', 'embedded', True)
    assert ex['export_yup'] is True and ex['export_animations'] is False and ex['export_def_bones'] is True
    assert 'export_format' not in ex and 'filepath' not in ex
    assert ex['export_vertex_color'] == 'NONE' and 'vertex colours' in p['description'], (
        'the atlas is the look: no flat palette stream and no forced white one')
    for name in ('fbx_generic', 'unity_humanoid'):
        assert not any('color' in k for k in profiles.load(name)['exporter']), name


def test_biped_bones_have_one_role_each_and_parents_before_children():
    t = skeletons.load('biped')
    assert len({b['role'] for b in t['bones']}) == len(t['bones'])
    seen = set()
    for b in t['bones']:
        assert b['parent'] is None or b['parent'] in seen, b['name']
        seen.add(b['name'])


def test_roles():
    assert skeletons.role_of('Hips') == 'hips'
    assert skeletons.role_of('Shoulder.R') == 'clavicle.R'
    assert skeletons.role_of('Thumb.L') == 'thumb.L'
    assert skeletons.role_of('Tail.3') == 'tail.3'
    assert skeletons.role_of('Tail.12') == 'tail.12'
    assert skeletons.role_of('Tail.0') is None
    assert skeletons.role_of('Ear.L') is None
    by_role = skeletons.names_by_role('biped')
    assert by_role['upper_arm.L'] == 'UpperArm.L' and by_role['toes.R'] == 'Toes.R'
    with _Raises(ValueError):
        skeletons.load('no_such_template')


def test_bone_renames_and_validation():
    p = copy.deepcopy(profiles.load('fbx_generic'))
    p['bone_map'].update({'hips': 'pelvis', 'tail.7': 'tail_07'})
    names = [b['name'] for b in skeletons.load('biped')['bones']] + ['Tail.7', 'Ear.L']
    assert profiles.bone_renames(names, p) == {'Hips': 'pelvis', 'Tail.7': 'tail_07'}
    assert profiles.validate(p) == []
    p['bone_map']['clavicle.L'] = 'Shoulder.R'
    assert profiles.validate(p)
    with _Raises(ValueError):
        profiles.bone_renames(names, p)
    q = copy.deepcopy(profiles.load('unity_humanoid'))
    q['axes'] = {'forward': 'Y', 'up': 'Z'}
    assert any('axes' in s for s in profiles.validate(q))
    q = copy.deepcopy(profiles.load('glb_generic'))
    q['exporter']['filepath'] = 'x.glb'
    q['bone_map'] = {'wing.L': 'Wing'}
    problems = profiles.validate(q)
    assert any('filepath' in s for s in problems) and any('wing.L' in s for s in problems)
    with _Raises(ValueError):
        profiles.load('no_such_profile')


def test_model_supplied_profiles_carry_their_schema_and_shipped_ones_load_as_shipped():
    import json
    import tempfile
    shipped = json.loads(Path(profiles.path_of('glb_generic')).read_text(encoding='utf-8'))
    assert 'schema' not in shipped and profiles.load('glb_generic') == shipped, 'the shipped files carry no schema'
    assert all(profiles.shipped(n) for n in profiles.names())
    assert not any(profiles.shipped(s) for s in ('own.json', 'profiles/own', 'profiles\\own'))
    own = dict(copy.deepcopy(shipped), name='own', influence_limit=2)
    own['exporter']['export_influence_nb'] = 2
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'profiles' / 'own.json'
        path.parent.mkdir()
        path.write_text(json.dumps(dict({'schema': profiles.SCHEMA}, **own)), encoding='utf-8')
        assert profiles.load(str(path)) == own, 'returned without its schema key'
        path.write_text(json.dumps(own), encoding='utf-8')
        try:
            profiles.load(str(path))
        except ValueError as e:
            assert 'no schema' in str(e) and '"schema": "lpk.profile/1"' in str(e), str(e)
        else:
            raise AssertionError('a model-supplied profile without its schema loads')
        for other in ('lpk.profile/2', 'lpk.views/1'):
            path.write_text(json.dumps(dict({'schema': other}, **own)), encoding='utf-8')
            try:
                profiles.load(str(path))
            except ValueError as e:
                assert other in str(e) and 'lpk.profile/1' in str(e), str(e)
            else:
                raise AssertionError('a profile with the schema %s loads' % other)
        path.write_text(json.dumps(dict({'schema': profiles.SCHEMA}, **dict(own, influence_limit=0))),
                        encoding='utf-8')
        with _Raises(ValueError):
            profiles.load(str(path))


def test_vhd_binary_per_platform():
    vhd_rel, = _functions(RIG, '_vhd_rel')
    assert vhd_rel('Windows', 'AMD64') == ('Windows', 'x64', 'vhd.exe')
    assert vhd_rel('Windows', 'ARM64') == ('Windows', 'arm64', 'vhd.exe')
    assert vhd_rel('Windows', 'x86') == ('Windows', 'x86', 'vhd.exe')
    assert vhd_rel('Linux', 'x86_64') == ('Linux', 'x64', 'vhd')
    assert vhd_rel('Linux', 'aarch64') == ('Linux', 'arm64', 'vhd')
    assert vhd_rel('Linux', 'i686') is None
    assert vhd_rel('Darwin', 'arm64') == ('Darwin', 'vhd')
    assert vhd_rel('Darwin', 'x86_64') == ('Darwin', 'vhd')
    assert vhd_rel('FreeBSD', 'amd64') is None


if __name__ == '__main__':
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print('ok    ' + name)
            except Exception as e:  # noqa: BLE001
                failed += 1
                print('FAIL  %s: %r' % (name, e))
    sys.exit(1 if failed else 0)
