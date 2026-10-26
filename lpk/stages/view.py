"""Viewport framing for review screenshots (no operators: region_3d is set directly), viewport captures,
and the PNG input and output of lpk.stages.imaging's arrays through Blender (load_image, save_image)."""
import contextlib
import math
import os

import bpy
import numpy as np
from mathutils import Euler, Vector

from lpk.stages import imaging

# Viewport rotations, Euler XYZ degrees. A view (a, 0, c) turns the model as lpk.stages.review.view_fit's
# yaw -c and pitch 90 - a do, perspective aside: 'side' shows the model's left side (+X) with its front
# toward image left, yaw -90; 'q34' its right front, yaw 35.
VIEWS = {'front': (90, 0, 0), 'back': (90, 0, 180), 'side': (90, 0, 90), 'q34': (80, 0, -35), 'q34_r': (80, 0, 35),
         'q34_back': (75, 0, 150), 'top': (0, 0, 0), 'eye': (90, 0, 180)}
ORTHO = {'front', 'back', 'side', 'top'}
# 'eye' looks forward (-Y) from the model's own eye in perspective, as a first-person camera does: its framing
# comes from the model's EYE (lpk.stages.review.body_views), not from the body's bounds.
# The look-dev light's intensity set_view gives a lit 'material' view: Blender's own default, so a lit
# capture does not depend on the intensity an earlier view left behind.
LOOKDEV_INTENSITY = 1.0


def window_context():
    """The temp_override keywords {'window', 'screen'} of the context's window, else of the first window of
    the window manager: the context has no window in a bridge call that has just loaded a file. Operators
    that parent, set a mode or read the selection need a window but no area. Raises RuntimeError when
    Blender has no window."""
    ctx = bpy.context
    manager = getattr(ctx, 'window_manager', None)
    window = getattr(ctx, 'window', None) or next(iter(manager.windows if manager else ()), None)
    if window is None:
        raise RuntimeError('Blender has no window: the operation needs a window of its window manager')
    return {'window': window, 'screen': window.screen}


def view3d_context():
    """The temp_override keywords {'window', 'screen', 'area', 'region'} of a 3D Viewport and its main
    region: the context's screen first, then every window of the window manager, because the context has
    no screen in a bridge call that has just loaded a file. Background mode (blender -b) keeps the screens of
    the open file, so it finds the area there; captures still fail there, for want of an OpenGL render.
    Raises RuntimeError when no screen holds a 3D Viewport (a workspace without one)."""
    ctx = bpy.context
    screen = getattr(ctx, 'screen', None)
    pairs = [(getattr(ctx, 'window', None), screen)] if screen else []
    manager = getattr(ctx, 'window_manager', None)
    pairs += [(w, w.screen) for w in (manager.windows if manager else ())]
    for window, screen in pairs:
        for area in (screen.areas if screen else ()):
            if area.type == 'VIEW_3D':
                region = next((r for r in area.regions if r.type == 'WINDOW'), None)
                if region is not None:
                    found = {'window': window, 'screen': screen, 'area': area, 'region': region}
                    return {k: v for k, v in found.items() if v is not None}
    raise RuntimeError('no screen holds a 3D Viewport: the edit-mode, bake, UV and viewport operations of the '
                       'kit take its area; open a 3D Viewport in the current workspace')


def rotation(yaw, pitch):
    """The viewport rotation (Euler XYZ degrees, as in VIEWS) that turns the model as a fit of
    lpk.stages.review.view_fit with this yaw and pitch (degrees) does: (90 - pitch, 0, -yaw). set_view
    shows such a rotation orthographic, as the fit projects."""
    return (90.0 - pitch, 0.0, -yaw)


def set_view(view='q34', shade='color', loc=(0, 0.3, 0.92), dist=2.6, wire=False, lens=None):
    """view: a VIEWS name, shown orthographic when ORTHO holds it, or a rotation (a, b, c), Euler XYZ
    degrees as in VIEWS, always shown orthographic (rotation() gives a fit's).
    shade: 'color' = vertex colours with studio light (the blocks and the build's palette colours),
    'tex' = textures with flat light (what an unlit runtime shader shows),
    'solid' = material colours with studio light,
    'material' = the material's node output in Material Preview (preview.preview_atlas), without the
    scene's world and lights. The look-dev light is off when every material of the visible meshes emits
    (emits: the preview's material, PAINT.material 'emission'), so they show their colours unlit as
    the unlit runtime target does; a material that does not emit ('base') shows black unlit, so any such
    material keeps the light on at LOOKDEV_INTENSITY, and its colours are then the look-dev light's
    ('tex' shows such an atlas unlit). Every shade reads through the scene's view transform: AgX greys
    the whites (lpk.stages.review's captures set Standard for themselves, standard_view).
    The floor, the grid of the orthographic views, the 3D cursor and the object origins are hidden, so a
    capture shows the model alone on its background, as lpk.stages.imaging.ink_mask and figure_box read
    a picture. The background is the viewport's own. lens: the viewport's focal length in millimetres for a
    perspective view, None to keep the viewport's own."""
    area = view3d_context()['area']
    sp = area.spaces.active
    r3 = sp.region_3d
    if isinstance(view, str):
        rot, ortho = VIEWS[view], view in ORTHO
    else:
        rot, ortho = tuple(view), True
    r3.view_rotation = Euler([math.radians(x) for x in rot], 'XYZ').to_quaternion()
    r3.view_perspective = 'ORTHO' if ortho else 'PERSP'
    r3.view_location = Vector(loc)
    r3.view_distance = dist
    if lens is not None:
        sp.lens = lens
    sh = sp.shading
    sh.type = 'SOLID'
    sh.light = 'FLAT' if shade in ('tex', 'material') else 'STUDIO'
    sh.color_type = {'color': 'VERTEX', 'tex': 'TEXTURE', 'solid': 'MATERIAL', 'material': 'TEXTURE'}[shade]
    if shade == 'material':
        sh.type = 'MATERIAL'
        sh.use_scene_world = sh.use_scene_lights = False
        sh.studiolight_intensity = 0.0 if all(emits(m) for m in _materials_in_view()) else LOOKDEV_INTENSITY
    sh.show_object_outline = False
    ov = sp.overlay
    ov.show_floor = ov.show_ortho_grid = ov.show_cursor = ov.show_object_origins = False
    ov.show_axis_x = ov.show_axis_y = False
    ov.show_wireframes = wire
    ov.wireframe_threshold = 1.0
    for o in bpy.context.selected_objects:
        o.select_set(False)


def emits(material):
    """Whether `material` shows colour without light: the surface its EEVEE output takes comes from an
    Emission shader or a Principled BSDF whose emission strength is linked or above zero. The preview's
    material and the final material PAINT.material 'emission' emit; the 'base' one, None (a mesh or
    a slot without a material), a material without nodes and any other shader at the output do not."""
    nt = getattr(material, 'node_tree', None)
    out = nt.get_output_node('EEVEE') if nt is not None else None
    if out is None or not out.inputs['Surface'].is_linked:
        return False
    node = out.inputs['Surface'].links[0].from_node
    key = {'ShaderNodeEmission': 'Strength', 'ShaderNodeBsdfPrincipled': 'Emission Strength'}.get(node.bl_idname)
    if key is None:
        return False
    strength = node.inputs[key]
    return strength.is_linked or strength.default_value > 0


def _materials_in_view():
    """The materials the visible meshes of the view layer show, each once in object and slot order, None
    for a mesh or a slot without one (Material Preview shows it in its default, lit material)."""
    out = []
    for o in bpy.context.view_layer.objects:
        if o.type == 'MESH' and o.visible_get():
            for m in [s.material for s in o.material_slots] or [None]:
                if m not in out:
                    out.append(m)
    return out


@contextlib.contextmanager
def standard_view():
    """A block in which the scene's view transform is Standard with no look, so captures and renders
    saved through the render settings hold the colours as they are: AgX and Filmic grey the whites. The
    transform and the look from before it hold again after it."""
    vs = bpy.context.scene.view_settings
    kept = (vs.view_transform, vs.look)
    vs.view_transform, vs.look = 'Standard', 'None'
    try:
        yield
    finally:
        vs.view_transform, vs.look = kept


def capture(filepath, width=1000):
    """Viewport render to a PNG. Use when MCP area/window screenshots come back black
    (Blender window minimised or covered): the OpenGL viewport render does not need the
    window on screen. The image keeps the viewport's aspect ratio; any other ratio crops the
    view off-centre."""
    sc = bpy.context.scene
    viewport = view3d_context()
    region = viewport['region']
    resolution = (width, round(width * region.height / region.width))
    prev = (sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage, sc.render.filepath)
    sc.render.resolution_x, sc.render.resolution_y = resolution
    sc.render.resolution_percentage = 100
    sc.render.filepath = filepath
    try:
        with bpy.context.temp_override(**viewport):
            bpy.ops.render.opengl(write_still=True, view_context=True)
    finally:
        sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage, sc.render.filepath = prev


def load_image(path):
    """A PNG (or any image Blender reads) as lpk.stages.imaging's float32 RGBA array (H, W, 4), top
    row first.

    path: the image file. 8-bit images come back as their stored values / 255, exactly. Images Blender
    keeps in a float buffer (16-bit PNG, EXR) are stored scene-linear with premultiplied alpha; they are
    un-premultiplied and, unless their colour space is non-colour data, encoded back to sRGB, so they
    match their 8-bit look to within rounding. The temporary image datablock is removed again."""
    img = bpy.data.images.load(os.path.abspath(path), check_existing=False)
    try:
        w, h = img.size
        if not w or not h:
            raise OSError('Blender could not read the image %s' % path)
        ch = img.channels
        buf = np.empty(w * h * ch, np.float32)
        img.pixels.foreach_get(buf)
        is_float = img.is_float
        cs = img.colorspace_settings
        is_data = getattr(cs, 'is_data', cs.name == 'Non-Color')
    finally:
        bpy.data.images.remove(img)
    a = imaging.rgba(np.flipud(buf.reshape(h, w, ch))).copy()
    if is_float:
        al = a[..., 3:4]
        a[..., :3] = np.where(al > 0, a[..., :3] / np.maximum(al, 1e-12), 0.0)
        if not is_data:
            c = np.clip(a[..., :3], 0.0, 1.0)
            a[..., :3] = np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)
    return a


def save_image(arr, path):
    """Write an array as an 8-bit RGBA PNG and return the absolute path.

    arr: (H, W, 4) top row first (grey, RGB and uint8 arrays are accepted); values are clipped to 0..1 and
    rounded to the nearest of the 256 levels, with no colour-space conversion: what load_image
    returned is written back unchanged. The image goes through a temporary byte-buffer datablock that is
    removed after saving."""
    a = np.clip(imaging.rgba(arr), 0.0, 1.0)
    h, w = a.shape[:2]
    path = os.path.abspath(path)
    img = bpy.data.images.new('.lpk_imaging_save', w, h, alpha=True, float_buffer=False)
    try:
        img.pixels.foreach_set(np.ascontiguousarray(np.flipud(a), np.float32).ravel())
        img.filepath_raw = path
        img.file_format = 'PNG'
        img.save()
    finally:
        bpy.data.images.remove(img)
    return path

