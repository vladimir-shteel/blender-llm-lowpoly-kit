"""Reference views as image empties beside the model, at the model's scale: the drawing a part is
compared with stands next to it in the viewport."""
import math

import bpy

# The model axis an image's x runs along in each plane (its y always runs along Z): a front or back view
# spans X and Z, a side view Y and Z.
PLANES = {'front': 0, 'side': 1}


def rotation(plane, sign):
    """The Euler rotation (radians) of an image empty whose image x runs along +axis (sign 1) or -axis
    (sign -1) of the plane's axis (PLANES) and whose y runs up Z; the image faces the viewer who sees its
    x to the right."""
    base = {(0, 1): 0.0, (0, -1): math.pi, (1, 1): math.pi / 2, (1, -1): -math.pi / 2}[PLANES[plane], sign]
    return (math.pi / 2, 0.0, base)


def place(name, image_path, collection, bottom_left, top_right, plane='front', shift=(0.0, 0.0, 0.0)):
    """The image at `image_path` as the image empty `name` in the collection `collection` (created when
    missing), in place of any object of that name: its lower-left pixel corner at `bottom_left` and its
    upper-right one at `top_right`, model points in metres (where the drawing's corners land through the
    view's calibration, so a view drawn from the back or the right comes out turned to match), moved by
    `shift` (m) so the drawing stands beside the model. plane: a key of PLANES. The image is drawn in the
    viewport only, never rendered or selected. Raises ValueError for an unknown plane or corners that span
    no area in it. Returns {'object': name, 'size': the image's larger side in metres, 'corner': its
    lower-left corner after the shift}."""
    if plane not in PLANES:
        raise ValueError('reference plane %r: use one of %s' % (plane, ', '.join(PLANES)))
    u = PLANES[plane]
    width, height = top_right[u] - bottom_left[u], top_right[2] - bottom_left[2]
    if width == 0 or height <= 0:
        raise ValueError('reference %s: its corners %r and %r span no area in the %s plane'
                         % (name, bottom_left, top_right, plane))
    coll = bpy.data.collections.get(collection) or bpy.data.collections.new(collection)
    if coll.name not in bpy.context.scene.collection.children:
        bpy.context.scene.collection.children.link(coll)
    old = bpy.data.objects.get(name)
    if old is not None:
        bpy.data.objects.remove(old, do_unlink=True)
    ob = bpy.data.objects.new(name, None)
    ob.empty_display_type = 'IMAGE'
    ob.data = bpy.data.images.load(image_path, check_existing=True)
    ob.empty_display_size = max(abs(width), height)
    ob.empty_image_offset = (0.0, 0.0)
    ob.use_empty_image_alpha = True
    ob.color[3] = 0.85
    corner = tuple(b + s for b, s in zip(bottom_left, shift))
    ob.location = corner
    ob.rotation_euler = rotation(plane, 1 if width > 0 else -1)
    ob.hide_render = True
    ob.hide_select = True
    coll.objects.link(ob)
    return {'object': name, 'size': round(max(abs(width), height), 4), 'corner': tuple(round(c, 4) for c in corner)}
