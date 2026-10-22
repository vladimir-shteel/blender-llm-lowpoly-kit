"""Setup check of the Blender session that runs lpk: lpk.setup_check.check() from an MCP call."""
import os
import platform
import sys

MIN_BLENDER = (5, 1, 0)


def _write_test(folder):
    """Write and delete a probe file in `folder`, creating the folder and its missing parents for the test and
    removing what it created afterwards, so that a folder the test names before it is used is not left
    behind. Returns (ok, error or None)."""
    folder = os.path.abspath(folder)
    created, at = [], folder
    while not os.path.exists(at) and os.path.dirname(at) != at:
        created.append(at)
        at = os.path.dirname(at)
    try:
        os.makedirs(folder, exist_ok=True)
        probe = os.path.join(folder, '.lpk_write_test')
        with open(probe, 'w', encoding='utf-8') as f:
            f.write('ok')
        os.remove(probe)
        return True, None
    except OSError as e:
        return False, str(e)
    finally:
        for made in created:
            try:
                os.rmdir(made)
            except OSError:
                pass


def check(out_dir=None):
    """What lpk needs from this Blender session, checked: lpk's version and folder, Blender's version and
    build hash (5.1 or newer), Python and numpy, background mode, the 3D Viewports of the current screen
    (captures and the edit-mode, bake and UV operators run in one), Cycles (the atlas bakes with it), the scene's unit system,
    unit scale and view transform, the open .blend and its unsaved changes, the Voxel Heat Diffuse
    Skinning binary and the weights backend weights(backend='auto') would pick, Blender's temporary
    folder (vhd weights write there) and, with out_dir, a write test there.
    out_dir: a folder to test for writing, or None; a missing folder and its missing parents are created for
    the test and removed again.
    Returns a JSON-serialisable dict; 'next' lists anything missing or likely to cause trouble, each
    {'issue': what is wrong, 'why': what it breaks, 'fix': what to do, 'required': True unless the
    session works without it (the Voxel Heat Diffuse Skinning add-on; a view transform other than
    Standard, since lpk's captures and atlas preview set Standard for themselves)}, in plain words (empty
    when the session is ready)."""
    import addon_utils
    import bpy
    import numpy as np

    import lpk
    from lpk.stages import rig

    build_hash = bpy.app.build_hash
    if isinstance(build_hash, bytes):
        build_hash = build_hash.decode(errors='replace')
    version = tuple(bpy.app.version)
    screen = getattr(bpy.context, 'screen', None)
    scene = bpy.context.scene
    units, view = scene.unit_settings, scene.view_settings
    backends = rig.available_backends()
    temp_ok, temp_err = _write_test(bpy.app.tempdir)
    rep = {
        'lpk': getattr(lpk, '__version__', 'dev'),
        'kit': os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'blender': bpy.app.version_string,
        'build_hash': str(build_hash),
        'blender_ok': version >= MIN_BLENDER,
        'python': sys.version.split()[0],
        'numpy': np.__version__,
        'platform': platform.platform(),
        'machine': platform.machine(),
        'background': bool(bpy.app.background),
        'view3d_areas': sum(1 for a in screen.areas if a.type == 'VIEW_3D') if screen else 0,
        'cycles': bool(addon_utils.check('cycles')[1]),
        'unit_system': units.system,
        'unit_scale': float(units.scale_length),
        'length_unit': units.length_unit,
        'view_transform': view.view_transform,
        'look': view.look,
        'blend_file': bpy.data.filepath or None,
        'is_dirty': bool(bpy.data.is_dirty),
        'vhd': rig.vhd_exe(),
        'weights_auto': backends[0],
        'weights_available': backends,
        'tempdir': bpy.app.tempdir,
        'tempdir_writable': temp_ok,
    }
    if out_dir is not None:
        ok, err = _write_test(out_dir)
        rep['out_dir'] = {'path': os.path.abspath(out_dir), 'writable': ok, 'error': err}

    fix = []

    def need(issue, why, how, required=True):
        fix.append({'issue': issue, 'why': why, 'fix': how, 'required': required})
    if not rep['blender_ok']:
        need('Blender %s is older than %d.%d.' % (rep['blender'], MIN_BLENDER[0], MIN_BLENDER[1]),
             'lpk uses the Python API of Blender %d.%d.' % MIN_BLENDER[:2],
             'Use Blender %d.%d or newer.' % MIN_BLENDER[:2])
    if rep['background']:
        need('Blender runs in background mode.',
             'Viewport captures and the edit-mode, bake and UV operators need a 3D Viewport.',
             'Start Blender with its user interface.')
    elif not rep['view3d_areas']:
        need('The current workspace has no 3D Viewport.',
             'Viewport captures and the edit-mode, bake and UV operators run in its context.',
             'Open a 3D Viewport in the current workspace.')
    if not rep['cycles']:
        need('The Cycles add-on is off.', 'The colour atlas is baked with Cycles.',
             'Enable Cycles in Edit > Preferences > Add-ons.')
    if abs(rep['unit_scale'] - 1.0) > 1e-9:
        need('The scene unit scale is %g.' % rep['unit_scale'],
             'lpk models in metres and the FBX export applies the unit scale.',
             'Set the scene unit scale to 1.0 in Scene Properties > Units.')
    if rep['view_transform'] != 'Standard':
        need('The scene view transform is %s (optional).' % rep['view_transform'],
             "The viewport and your own renders are tone-mapped; lpk's captures "
             'and the atlas preview set Standard for themselves.',
             'Set the view transform to Standard to see the atlas colours exactly.', required=False)
    if not rep['blend_file'] and any(o.type not in ('CAMERA', 'LIGHT') for o in bpy.data.objects):
        need('The open file is unsaved and has objects.',
             "The kit creates and replaces objects named after the model; other objects may share its names.",
             "Open the model's file or start a new one.")
    if rep['vhd'] is None:
        need('The Voxel Heat Diffuse Skinning add-on or its binary is missing (optional).',
             "Without it weights(backend='auto') uses %s, not voxel heat weights." % rep['weights_auto'],
             'Install and enable the add-on for voxel heat weights.', required=False)
    if not temp_ok:
        need("Blender's temporary folder %s is not writable (%s)." % (rep['tempdir'], temp_err),
             'vhd weights write their files there.', 'Set another one in Preferences > File Paths.')
    if out_dir is not None and not rep['out_dir']['writable']:
        need('Cannot write to %s: %s.' % (rep['out_dir']['path'], rep['out_dir']['error']),
             'The kit writes its captures, atlas and exports there.', 'Pick a writable folder.')
    rep['next'] = fix
    return rep
