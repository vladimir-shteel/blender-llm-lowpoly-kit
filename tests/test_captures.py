"""Host tests of the capture path: the viewport state lpk.stages.view.set_view sets (the origins hidden,
the look-dev light off only where every material in view emits), lpk.stages.review._viewport putting
every such setting back, _shoot's Standard view transform in every shade, the atlas preview saved under
Standard, the setup check's view-transform item, and the
pose sheet with the bones a pose names that the rig lacks (no Blender needed: bpy, addon_utils and
mathutils are replaced by stand-ins).

python tests/test_captures.py"""
import contextlib
import ast
import importlib
import os
import sys
import tempfile
import types
from unittest import mock

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from blender_stand_ins import Vector as _Vector, stand_ins  # noqa: E402


@contextlib.contextmanager
def _blender_stand_ins():
    """The stand-ins of blender_stand_ins plus addon_utils, with lpk.core.builder replaced by the production
    colour conversion alone (Builder's geometry dependencies need Blender)."""
    with stand_ins(extra=('addon_utils',)):
        with open(os.path.join(ROOT, 'lpk', 'core', 'builder.py'), encoding='utf-8') as source:
            conversion = next(n for n in ast.parse(source.read()).body
                              if isinstance(n, ast.FunctionDef) and n.name == 'srgb_to_linear')
        builder = types.ModuleType('lpk.core.builder')
        exec(compile(ast.Module(body=[conversion], type_ignores=[]), '<colour conversion>', 'exec'), builder.__dict__)
        sys.modules['lpk.core.builder'] = builder
        yield


with _blender_stand_ins():
    review = importlib.import_module('lpk.stages.review')
    REVIEW_POSES = importlib.import_module('lpk.skeletons').poses('biped')
    view = importlib.import_module('lpk.stages.view')
    preview = importlib.import_module('lpk.stages.preview')
    setup_check = importlib.import_module('lpk.setup_check')
    pose = importlib.import_module('lpk.stages.pose')
    # What the functions under test import when they run: the stand-ins and lpk as imported here.
    LIVE = {k: sys.modules[k] for k in ('bpy', 'addon_utils', 'mathutils', 'lpk', 'lpk.stages', 'lpk.stages.view',
                                        'lpk.stages.pose', 'lpk.core.builder')}
bpy, addon_utils = LIVE['bpy'], LIVE['addon_utils']


# -- a scene of stand-ins ---------------------------------------------------------------------------------

def _socket(value=0.0, linked=False, source=None):
    return types.SimpleNamespace(default_value=value, is_linked=linked or source is not None,
                                 links=[types.SimpleNamespace(from_node=source)] if source is not None else [])


def _material(surface=None):
    """A material whose EEVEE output takes `surface` (a node, or None for an unlinked output)."""
    out = types.SimpleNamespace(bl_idname='ShaderNodeOutputMaterial', inputs={'Surface': _socket(source=surface)})
    return types.SimpleNamespace(node_tree=types.SimpleNamespace(get_output_node=lambda target: out))


def _emission(strength=1.0, linked=False):
    return types.SimpleNamespace(bl_idname='ShaderNodeEmission', inputs={'Strength': _socket(strength, linked)})


def _principled(strength=0.0, linked=False):
    return types.SimpleNamespace(bl_idname='ShaderNodeBsdfPrincipled',
                                 inputs={'Emission Strength': _socket(strength, linked)})


EMITTING = _material(_emission())                     # lpk.stages.preview's material
FINAL_EMISSION = _material(_principled(1.0))          # M.texture(material='emission')
FINAL_BASE = _material(_principled(0.0))              # M.texture(material='base')


def _mesh(name, *materials, visible=True):
    return types.SimpleNamespace(name=name, type='MESH', visible_get=lambda: visible,
                                 material_slots=[types.SimpleNamespace(material=m) for m in materials])


def _scene(objects=()):
    """bpy.context with one 3D Viewport in a state no capture sets, an AgX scene and `objects` in the view
    layer. Returns (shading, overlay, region_3d, scene)."""
    sh = types.SimpleNamespace(type='SOLID', light='STUDIO', color_type='OBJECT', show_object_outline=True,
                               background_type='THEME', background_color=(0.3, 0.3, 0.3), use_scene_world=True,
                               use_scene_lights=True, studiolight_intensity=2.5)
    ov = types.SimpleNamespace(show_floor=True, show_ortho_grid=True, show_cursor=True, show_object_origins=True,
                               show_axis_x=True, show_axis_y=True, show_wireframes=True, wireframe_threshold=0.5)
    r3 = types.SimpleNamespace(view_rotation=_Vector((1, 0, 0, 0)), view_perspective='PERSP',
                               view_location=_Vector((0, 0, 1)), view_distance=5.0)
    sp = types.SimpleNamespace(shading=sh, overlay=ov, region_3d=r3, lens=50.0)
    area = types.SimpleNamespace(type='VIEW_3D', spaces=types.SimpleNamespace(active=sp),
                                 regions=[types.SimpleNamespace(type='WINDOW')])
    scene = types.SimpleNamespace(
        view_settings=types.SimpleNamespace(view_transform='AgX', look='AgX - Punchy'),
        render=types.SimpleNamespace(film_transparent=False,
                                     image_settings=types.SimpleNamespace(file_format='JPEG', color_mode='RGB')))
    bpy.context = types.SimpleNamespace(screen=types.SimpleNamespace(areas=[area]), scene=scene,
                                        view_layer=types.SimpleNamespace(objects=list(objects)),
                                        selected_objects=[])
    return sh, ov, r3, scene


def _state(*spaces):
    return [dict(vars(s)) for s in spaces]


# -- set_view ---------------------------------------------------------------------------------------------

def test_emits_reads_the_shader_at_the_output():
    assert view.emits(EMITTING) and view.emits(FINAL_EMISSION)
    assert not view.emits(FINAL_BASE), "the 'base' final material shows black unlit"
    assert view.emits(_material(_principled(0.0, linked=True))), 'a linked strength may emit'
    assert not view.emits(_material(_emission(0.0)))
    assert not view.emits(_material(None)) and not view.emits(None)
    assert not view.emits(types.SimpleNamespace(node_tree=None))
    other = types.SimpleNamespace(bl_idname='ShaderNodeBsdfDiffuse', inputs={})
    assert not view.emits(_material(other))


def test_set_view_hides_the_origins_in_every_shade():
    for shade in ('color', 'tex', 'solid', 'material'):
        sh, ov, r3, _ = _scene()
        view.set_view('front', shade)
        assert ov.show_object_origins is False and ov.show_floor is False and ov.show_cursor is False, shade


def test_material_view_turns_the_light_off_only_when_everything_in_view_emits():
    sh, ov, r3, _ = _scene([_mesh('Body', EMITTING), _mesh('Body_Details', FINAL_EMISSION),
                            _mesh('Body_Source', FINAL_BASE, visible=False)])
    view.set_view('front', 'material')
    assert (sh.type, sh.color_type, sh.use_scene_world, sh.use_scene_lights) == ('MATERIAL', 'TEXTURE', False, False)
    assert sh.studiolight_intensity == 0.0, 'a hidden mesh does not count'
    sh, *_ = _scene([_mesh('Body', EMITTING), _mesh('Body_Gear', FINAL_BASE)])
    view.set_view('front', 'material')
    assert sh.studiolight_intensity == view.LOOKDEV_INTENSITY, 'a material that does not emit keeps the light'
    sh, *_ = _scene([_mesh('Body', EMITTING), _mesh('Bare')])
    view.set_view('front', 'material')
    assert sh.studiolight_intensity == view.LOOKDEV_INTENSITY, 'a mesh without a material shows a lit default'
    sh, *_ = _scene([_mesh('Body', FINAL_BASE)])
    view.set_view('front', 'tex')
    assert sh.studiolight_intensity == 2.5 and sh.use_scene_world, 'the light belongs to Material Preview only'


def test_viewport_puts_back_every_setting_a_view_changes():
    sh, ov, r3, scene = _scene([_mesh('Body', EMITTING)])
    before = _state(sh, ov, r3, scene.view_settings)
    with review._viewport():
        view.set_view('front', 'material', wire=False)
        scene.view_settings.view_transform = 'Standard'
        assert _state(sh, ov, r3) != before[:3]
    assert _state(sh, ov, r3, scene.view_settings) == before


# -- _shoot -----------------------------------------------------------------------------------------------

@contextlib.contextmanager
def _capturing(picture):
    """view.capture, review's load_image and save_image replaced: the capture records the scene's view
    transform and film, load returns `picture`, save records what it writes. Yields the records."""
    seen = {'captures': [], 'saved': []}
    saved = (view.capture, review.load_image, review.save_image)

    def capture(path, width):
        s = bpy.context.scene
        seen['captures'].append((s.view_settings.view_transform, s.view_settings.look, s.render.film_transparent,
                                 s.render.image_settings.file_format, s.render.image_settings.color_mode))
    view.capture = capture
    review.load_image = lambda path: picture.copy()
    review.save_image = lambda arr, path: seen['saved'].append((arr, path)) or path
    try:
        yield seen
    finally:
        view.capture, review.load_image, review.save_image = saved


def test_shoot_captures_every_shade_under_standard():
    for shade in ('color', 'tex', 'solid', 'material'):
        _, _, _, scene = _scene([_mesh('Body', EMITTING)])
        with _capturing(np.zeros((2, 2, 4), np.float32)) as seen:
            review._shoot('front', shade, (0, 0, 1), 2.0, 'shot.png', 100)
        assert seen['captures'] == [('Standard', 'None', False, 'JPEG', 'RGB')], (shade, seen)
        assert (scene.view_settings.view_transform, scene.view_settings.look) == ('AgX', 'AgX - Punchy'), shade
        assert seen['saved'] == [], 'a capture is saved as the viewport renders it'


# -- the atlas preview and the setup check -----------------------------------------------------------------

def test_the_preview_row_saves_the_atlas_under_standard():
    _, _, _, scene = _scene()
    transforms = []
    data = mock.MagicMock()
    data.images.__getitem__.return_value.save_render.side_effect = (
        lambda path: transforms.append((scene.view_settings.view_transform, scene.view_settings.look)))
    bpy.data = data
    try:
        with mock.patch.dict(sys.modules, LIVE):
            got = preview.preview_atlas('Body', 'Body_Atlas', 'Body_AtlasFile', 'Body_Preview',
                                        os.path.join(tempfile.mkdtemp(), 'Body_Atlas_preview.png'), 'toon')
    finally:
        del bpy.data
    assert transforms == [('Standard', 'None')], transforms
    assert (scene.view_settings.view_transform, scene.view_settings.look) == ('AgX', 'AgX - Punchy')
    assert got['material'] == 'Body_Preview' and got['preset'] == 'toon'


def test_the_setup_checks_write_test_leaves_no_folder_it_created():
    setup_check = importlib.import_module('lpk.setup_check')
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, 'Model', 'out')
        assert setup_check._write_test(out) == (True, None)
        assert os.listdir(tmp) == [], 'the project folder a write test names is not left behind'
        os.makedirs(out)
        with open(os.path.join(out, 'kept.txt'), 'w') as f:
            f.write('x')
        assert setup_check._write_test(out) == (True, None) and os.listdir(out) == ['kept.txt'], 'an existing folder stays'


def test_setup_check_reports_the_view_transform_without_requiring_it():
    _, _, _, scene = _scene()
    scene.unit_settings = types.SimpleNamespace(system='METRIC', scale_length=1.0, length_unit='METERS')
    bpy.app = types.SimpleNamespace(build_hash=b'abc', version=(5, 2, 0), version_string='5.2.0', background=False,
                                    tempdir=tempfile.mkdtemp())
    bpy.data = types.SimpleNamespace(filepath='', is_dirty=False, objects=[])
    addon_utils.check = lambda name: (True, True)
    rig = types.ModuleType('lpk.stages.rig')
    rig.available_backends = lambda: ['heat_proxy', 'distance']
    rig.vhd_exe = lambda: None
    try:
        with mock.patch.dict(sys.modules, dict(LIVE, **{'lpk.stages.rig': rig})):
            with mock.patch.object(LIVE['lpk.stages'], 'rig', rig, create=True):
                rep = setup_check.check()
    finally:
        del bpy.app, bpy.data
    item, = [i for i in rep['next'] if 'view transform' in i['issue']]
    assert item['required'] is False and 'AgX' in item['issue'], item
    assert rep['view_transform'] == 'AgX'
    assert [i['required'] for i in rep['next'] if i is not item] == [False], 'the add-on is the other optional item'


# -- the pose sheet ---------------------------------------------------------------------------------------

def _rig(*bones):
    return types.SimpleNamespace(name='Figure_Rig', type='ARMATURE', pose=types.SimpleNamespace(bones=[
        types.SimpleNamespace(name=b, rotation_mode='QUATERNION', rotation_euler=(9, 9, 9), location=(1, 1, 1))
        for b in bones]))


def test_set_pose_returns_the_names_the_rig_lacks():
    rig = _rig('UpperArm.L', 'UpperArm.R')
    bpy.data = types.SimpleNamespace(objects={'Figure_Rig': rig})
    bpy.context = types.SimpleNamespace(view_layer=types.SimpleNamespace(update=lambda: None))
    try:
        ignored = pose.set_pose('Figure_Rig', {'Index.L': (0, 0, -10), 'UpperArm.L': (0, 0, 90), 'Tail.1': (5, 0, 0)})
        assert ignored == ['Index.L', 'Tail.1'], 'in the pose\'s order'
        left, right = rig.pose.bones
        assert np.allclose(left.rotation_euler, (0, 0, np.pi / 2)) and left.location == (0, 0, 0)
        assert right.rotation_euler == [0, 0, 0] and right.rotation_mode == 'XYZ', 'a bone it does not name rests'
        assert pose.set_pose('Figure_Rig', None) == [] and left.rotation_euler == [0, 0, 0]
        pose.set_pose('Figure_Rig', {'UpperArm.R': {'loc': (0, 0.02, 0)}, 'UpperArm.L': {'rot': (10, 0, 0)}})
        assert right.location == (0.0, 0.02, 0.0) and right.rotation_euler == [0, 0, 0], 'an offset alone'
        assert np.allclose(left.rotation_euler, (np.radians(10), 0, 0)) and left.location == (0.0, 0.0, 0.0)
        for bad in ({'move': (0, 0, 1)}, {'loc': (0, 1)}, 'up'):
            try:
                pose.channels(bad)
            except ValueError:
                pass
            else:
                raise AssertionError('%r accepted' % (bad,))
    finally:
        del bpy.data


def test_pose_captures_set_each_pose_and_leave_out_the_poses_the_rig_cannot_turn():
    rig = _rig('Shoulder.L', 'Shoulder.R', 'UpperArm.L', 'UpperArm.R', 'UpperLeg.L', 'UpperLeg.R', 'LowerLeg.R')
    objects = {'Figure': types.SimpleNamespace(type='MESH'), 'Figure_Rig': rig}
    out = os.path.join(tempfile.mkdtemp(), 'review', 'rig')
    poses = dict(REVIEW_POSES, test_pose={'Tail.1': (0, 0, 30)})
    sheet = lambda **kw: review.pose_captures('Figure', 'Figure_Rig', kw.pop('out', out), kw.pop('poses', poses),
                                              **kw)
    failing = []
    posed, shots, held = [], [], []
    stand_in = types.ModuleType('lpk.stages.pose')
    stand_in.set_pose = lambda name, rotations=None: posed.append((name, rotations)) or []

    @contextlib.contextmanager
    def held_pose(name, rotations=None):
        held.append(('hold', name))
        try:
            yield []
        finally:
            held.append(('back', name))
    stand_in.held_pose = held_pose
    frames = [('front', (0, 0, 1), 2.0), ('side', (0, 0, 1), 2.0)]
    saved = (review.capture, review.body_views, review.load_image, review.save_image)

    def capture(out, tag, views, shade='color', keep=None, width=1000):
        shots.append((tag, shade, keep))
        if tag == 'shrug' and failing:
            raise RuntimeError('capture failed')
        return [os.path.join(out, '%s_%s.png' % (tag, v)) for v, _, _ in views]
    review.capture, review.body_views = capture, lambda name, views, eye=None: frames
    review.load_image = lambda path: np.ones((4, 3, 4), np.float32)
    review.save_image = lambda arr, path: path
    bpy.data = types.SimpleNamespace(objects=objects)
    try:
        with mock.patch.dict(sys.modules, dict(LIVE, **{'lpk.stages.pose': stand_in})), \
                mock.patch.object(LIVE['lpk.stages'], 'pose', stand_in, create=True):
            got = sheet(views=('front', 'side'))
            assert got['skipped'] == ['grip', 'test_pose'], 'no bone of theirs is in the rig'
            assert got['ignored'] == {'grip': list(REVIEW_POSES['grip']), 'test_pose': ['Tail.1']}, got['ignored']
            columns = [t for t, _, _ in shots]
            assert columns == ['side75', 'fwd70', 'shrug', 'stride', 'spread'], columns
            assert {(s, tuple(k)) for _, s, k in shots} == {('color', ('Figure',))}
            assert [p[1] for p in posed] == [REVIEW_POSES[t] for t in columns]
            assert held == [('hold', 'Figure_Rig'), ('back', 'Figure_Rig')], 'the pose the rig was found in comes back'
            assert got['sheet'].endswith(os.path.join('review', 'rig', 'poses.png')) and len(got['files']) == 10
            rig.pose.bones.append(types.SimpleNamespace(name='Index.L'))
            posed.clear()
            shots.clear()
            part = sheet(poses={'grip': REVIEW_POSES['grip']}, views=('front', 'side'))
            assert part['ignored'] == {'grip': ['Middle.L', 'Thumb.L', 'Index.R', 'Middle.R', 'Thumb.R']}
            assert part['skipped'] == [] and len(part['files']) == 2
            none = sheet(poses={'tail': {'Tail.1': (0, 0, 30)}})
            assert none == {'sheet': None, 'files': [], 'ignored': {'tail': ['Tail.1']}, 'skipped': ['tail']}
            failing.append(True)
            held.clear()
            try:
                sheet(poses={'shrug': REVIEW_POSES['shrug']}, out=tempfile.mkdtemp())
            except RuntimeError:
                pass
            else:
                raise AssertionError('the capture error was swallowed')
            assert held[-1] == ('back', 'Figure_Rig'), 'a failed capture still puts the found pose back'
            assert 'VIEWS' in str(_raises(ValueError, sheet, views=('front', 'nowhere')))
            del objects['Figure_Rig']
            assert 'rig' in str(_raises(RuntimeError, sheet))
    finally:
        review.capture, review.body_views, review.load_image, review.save_image = saved
        del bpy.data


def _raises(exc, fn, *args, **kw):
    try:
        fn(*args, **kw)
    except exc as e:
        return e
    raise AssertionError('%s not raised' % exc.__name__)


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            with mock.patch.dict(sys.modules, LIVE):
                fn()
            print('ok', name)
