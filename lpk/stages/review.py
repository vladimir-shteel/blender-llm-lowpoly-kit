"""Review captures, review poses and the measurements of the build against a drawing. Captures go through
the viewport (lpk.stages.view) and restore the user's view afterwards; contact sheets and overlays are
composed from the captures by lpk.stages.imaging.

Poses are Blender bone-local Euler degrees, the skeleton template's review poses (lpk.skeletons.poses) or a
model's own.
join_metrics gives the numbers of how a pose deforms each join zone; the pose captures show it.

The measurements against a drawing: outline_diff (the build's outline against the drawing's ink in one
view), concept_fit (the yaw and pitch of a turned concept) and play_size (the model at its on-screen
height). They report
numbers and pixel regions; what a difference means is the human's call. Their image arithmetic is numpy
(silhouette_report, fit_silhouette, landmark_depths and pitch_limit run on the host as well); only the
readers of the scene and the captures need Blender.

The measurements take plain arguments: the views object (lpk.core.views.Views), a view name, a fit
(view_fit, calib_fit or concept_fit's {'yaw', 'pitch', 's', 'ox', 'oy'}), object names and output paths."""
import contextlib
import math
import os

import bpy
import numpy as np
from mathutils import Euler, Vector

from lpk.core.views import SIDE_FACINGS, CalibrationError
from lpk.stages import checks, imaging, numerical, view
from lpk.stages.view import load_image, save_image

FIT_PER_M = 2.4 / 1.8     # view distance per metre of framed height: the viewport fits a 1.8 m figure at 2.4
MARGIN = 1.1              # room round the framed height
MIN_HEIGHT = 0.2          # metres: a part built alone (an eye, a skull) is framed no closer than this
# Pixels an edge of the build may read off the drawing's before silhouette_report lists it as a band: each
# outline holds an edge to its pixel (the build's at pixel centres, the drawing's where its ink is), so one
# true edge can read a pixel apart in the two.
EDGE_PX = 1
# Pixels a width may read off the drawn one before silhouette_report lists it: a width spans two edges,
# each held to EDGE_PX.
EXTENT_PX = 2 * EDGE_PX
# Pixels of a view a pitch moves a point's row by at pitch_limit: one pixel, the precision a landmark is
# read with.
PITCH_SHIFT_PX = 1.0
# fit_silhouette's search, a speed choice: the rows its coarse pass shrinks the figure to; the fine pass
# runs at the drawing's own pixels, every degree round the best coarse fit.
FIT_ROWS = 200
FIT_YAW_STEP = 5          # degrees between the yaws of fit_silhouette's coarse pass
FIT_PITCH_STEP = 2        # degrees between the pitches of fit_silhouette's coarse pass
# Matrix values pass through Blender's float storage; this guards representation noise, not a pose.
REST_MATRIX_ATOL = 1e-7


def capture(out_dir, tag, views, shade='color', keep=None, origin=(0, 0, 0), width=1000, fit=None):
    """One PNG per view: (view name, location relative to `origin`, distance) -> <out_dir>/<tag>_<view>.png,
    each under the Standard view transform (_shoot). shade: view.set_view's. keep: names of the only
    meshes and armatures to show (None shows everything).
    fit: a fit of view_fit, calib_fit or concept_fit ({'yaw', 'pitch', ...}): every view is then shown
    orthographic at the fit's yaw and pitch (view.rotation) instead of its VIEWS rotation, and its name
    only names the file, e.g. the drawing's view the fit belongs to. The fit's scale and offset are not
    used: the location and distance frame the capture. Returns the paths."""
    os.makedirs(out_dir, exist_ok=True)
    files = []
    with _viewport(), _hidden(keep):
        for v, loc, dist in views:
            f = os.path.join(out_dir, '%s_%s.png' % (tag, v))
            _shoot(v if fit is None else view.rotation(fit['yaw'], fit['pitch']), shade, Vector(origin) + Vector(loc),
                   dist, f, width)
            files.append(f)
    return files


@contextlib.contextmanager
def _viewport():
    """A block that may change the 3D viewport's view, shading, look-dev light and overlays
    and the scene's view transform: all of them hold their values from before it again after it. Yields
    (region_3d, the viewport's window region)."""
    area = view.view3d_context()['area']
    sp = area.spaces.active; r3 = sp.region_3d; sh = sp.shading; ov = sp.overlay
    saved = dict(rot=r3.view_rotation.copy(), persp=r3.view_perspective, loc=r3.view_location.copy(),
                 dist=r3.view_distance, type=sh.type, light=sh.light, ct=sh.color_type,
                 outline=sh.show_object_outline, floor=(ov.show_floor, ov.show_ortho_grid, ov.show_cursor),
                 wire=ov.show_wireframes, axis=(ov.show_axis_x, ov.show_axis_y), threshold=ov.wireframe_threshold,
                 origins=ov.show_object_origins,
                 lookdev=(sh.use_scene_world, sh.use_scene_lights, sh.studiolight_intensity))
    scn = bpy.context.scene
    vt = (scn.view_settings.view_transform, scn.view_settings.look)
    try:
        yield r3, next(r for r in area.regions if r.type == 'WINDOW')
    finally:
        scn.view_settings.view_transform, scn.view_settings.look = vt
        r3.view_rotation = saved['rot']; r3.view_perspective = saved['persp']; r3.view_location = saved['loc']
        r3.view_distance = saved['dist']
        sh.type = saved['type']; sh.light = saved['light']; sh.color_type = saved['ct']
        sh.show_object_outline = saved['outline']; ov.show_wireframes = saved['wire']
        ov.show_floor, ov.show_ortho_grid, ov.show_cursor = saved['floor']
        ov.show_axis_x, ov.show_axis_y = saved['axis']; ov.wireframe_threshold = saved['threshold']
        ov.show_object_origins = saved['origins']
        sh.use_scene_world, sh.use_scene_lights, sh.studiolight_intensity = saved['lookdev']


@contextlib.contextmanager
def _hidden(keep):
    """A block in which every object not named in keep is hidden (keep None hides nothing), lights and
    cameras included, whose overlay lines would cross the capture; they show again after it."""
    hidden = []
    if keep is not None:
        bpy.context.view_layer.update()          # a rebuild just replaced objects
        for o in list(bpy.context.view_layer.objects):
            if o and o.name not in keep and not o.hide_get():
                o.hide_set(True); hidden.append(o)
    try:
        yield
    finally:
        for o in hidden:
            o.hide_set(False)


def _shoot(rot, shade, loc, dist, path, width, measure=None):
    """One capture to `path` of the view `rot` (a VIEWS name or a rotation, as view.set_view takes it),
    inside _viewport, under the Standard view transform in every shade (view.standard_view: AgX greys the
    whites of each). measure: a function called with the view set, before the capture; returns its value
    (None without one)."""
    view.set_view(rot, shade, loc, dist)
    with view.standard_view():
        got = measure() if measure is not None else None
        view.capture(path, width)
    return got


def framing(obj_name, views=('front', 'side', 'q34', 'back')):
    """One view distance that frames a mesh object from its bounds in each of `views` (lpk.stages.view.VIEWS
    names): {'centre': [x, y, z], the centre of the world bounding box of its mesh vertices (the rest
    shape: a pose does not move the frame), 'height': the box's height in metres, 'width': the widest
    the box spans across the screen in those views (its x and y extents seen at each view's turn about
    Z), 'distance': FIT_PER_M * MARGIN times the larger of height and width, no less than MIN_HEIGHT}.
    FIT_PER_M fits a length to the viewport's height, so a model wider than tall keeps room at the
    sides of a landscape viewport. Raises RuntimeError for an object without vertices."""
    ob = bpy.data.objects[obj_name]
    mw = ob.matrix_world
    co = [mw @ v.co for v in ob.data.vertices]
    if not co:
        raise RuntimeError('the object %r has no vertices' % ob.name)
    lo = Vector([min(p[i] for p in co) for i in range(3)])
    hi = Vector([max(p[i] for p in co) for i in range(3)])
    ext = hi - lo
    width = max((abs(ext.x * math.cos(t)) + abs(ext.y * math.sin(t))
                 for t in (math.radians(view.VIEWS[v][2]) for v in views)), default=0.0)
    return {'centre': list((lo + hi) / 2), 'height': ext.z, 'width': width,
            'distance': FIT_PER_M * max(ext.z, width, MIN_HEIGHT) * MARGIN}


def body_views(obj_name, views=('front', 'side', 'q34', 'back')):
    """capture's views of a model framed on its body object (framing over the same views): [(view,
    centre, distance)] for the lpk.stages.view.VIEWS names in `views`."""
    f = framing(obj_name, views)
    return [(v, tuple(f['centre']), f['distance']) for v in views]


def _turn(yaw, pitch):
    return Euler((math.radians(pitch), 0.0, math.radians(yaw)), 'ZXY').to_matrix()


def view_fit(points, pixels, yaws=range(-90, 91), pitches=range(-20, 21, 2), yaw_range=None):
    """The orthographic view of the model that best fits points marked on a reference image (an
    overlay, `project`): points in model space and their pixels, three or more, spread over the
    part. Searches the yaw (about Z, degrees; + turns the model's front toward image right, its right
    side toward the viewer) and the pitch (degrees; + looks down from above), and solves the scale and
    offset by least squares: a model point turned by the yaw, then the pitch, to q lands on pixel
    (ox + s * q.x, oy - s * q.z). Returns {'yaw', 'pitch', 's', 'ox', 'oy', 'err': pixel error per
    point, 'at_range_edge', 'pitch_step': degrees between the searched pitches, the resolution of the
    pitch (0 when one pitch is searched)}; a large error on one point is a mismarked pixel or a part out
    of place.
    at_range_edge is True when the best yaw is the smallest or largest searched one and no searched yaw
    lies within one step past it round the turn (yaw_range=(-180, 180) has no edge): a better fit may
    lie outside the search. A profile over the default yaws sits on the edge at -90 or 90; calib_fit
    gives a calibrated profile exactly.
    yaw_range: (first, last) whole degrees, both included, searched in 1-degree steps instead of
    `yaws`; (-180, 180) reaches back views, which the default -90..90 cannot fit."""
    if yaw_range is not None:
        yaws = range(int(yaw_range[0]), int(yaw_range[1]) + 1)
    yaws = list(yaws)
    best = None
    for yaw in yaws:
        for pitch in pitches:
            R = _turn(yaw, pitch)
            q = [R @ Vector(p) for p in points]
            mx = sum(v.x for v in q) / len(q); mz = sum(v.z for v in q) / len(q)
            mu = sum(u for u, _ in pixels) / len(q); mv = sum(v for _, v in pixels) / len(q)
            num = sum((v.x - mx) * (u - mu) - (v.z - mz) * (w - mv) for v, (u, w) in zip(q, pixels))
            den = sum((v.x - mx) ** 2 + (v.z - mz) ** 2 for v in q)
            s = num / den
            ox, oy = mu - s * mx, mv + s * mz
            err = [math.hypot(ox + s * v.x - u, oy - s * v.z - w) for v, (u, w) in zip(q, pixels)]
            rms = math.sqrt(sum(e * e for e in err) / len(err))
            if best is None or rms < best[0]:
                best = (rms, dict(yaw=yaw, pitch=pitch, s=s, ox=ox, oy=oy, err=[round(e, 1) for e in err]))
    fit = best[1]
    fit['at_range_edge'] = _at_range_edge(fit['yaw'], yaws)
    fit['pitch_step'] = _step(pitches)
    return fit


def _step(values):
    """The smallest gap between the distinct values searched, 0 for a single one."""
    vs = sorted(set(values))
    return min((b - a for a, b in zip(vs, vs[1:])), default=0)


def _at_range_edge(yaw, yaws):
    """view_fit's at_range_edge for the best yaw among the searched yaws (degrees)."""
    ys = sorted(set(yaws))
    if len(ys) == 1:
        return True
    if yaw == ys[-1]:
        step, past = ys[-1] - ys[-2], lambda y: (y - yaw) % 360
    elif yaw == ys[0]:
        step, past = ys[1] - ys[0], lambda y: (yaw - y) % 360
    else:
        return False
    return not any(0 < past(y) <= step + 1e-9 for y in ys)


def calib_fit(cal, mid_px=None):
    """view_fit's dict for a calibrated view, built from its calibration instead of fitted: cal is a
    lpk.core.views calibration of any mode (Views.calib(name)), and the result {'yaw', 'pitch': 0, 's',
    'ox', 'oy', 'err': []} projects exactly as the calibration measures. cal.facing picks the yaw:

    - 'left' or 'right', a side view: -90 for a model facing image left, its left side (+X) toward the
      viewer as lpk.stages.view.VIEWS['side'] shows it; 90 for one facing image right. The columns are
      depth as cal.side_y reads them, so s = 1 / cal.m(1), ox = cal.zero_px, oy = s * cal.z(0), and
      mid_px is not used. A side view without zero_px raises CalibrationError.
    - 'back': 180 about the midline, so the model's left (+X) lands left of it; cal.model() reads
      every view that is not a side view as a front, so its x is mirrored on a back view.
    - 'turned' (a three-quarter concept): raises CalibrationError. Its columns mix width and depth, so no
      calibration projects it: fit it by its outline with concept_fit or by measured points with
      view_fit.
    - 'front' or none: 0, a front view about the midline.
    - any other value: raises CalibrationError, never read as a front.

    mid_px: a front or back view's midline column; None takes cal.model()'s own midline, which is the
    view's mid_px except for a 'rows' calibration, which takes the image centre: pass a 'rows' view's
    mid_px, Views.view(name).get('mid_px', cal.w / 2)."""
    facing = getattr(cal, 'facing', None)
    if facing not in (None, 'front', 'back', 'turned') + SIDE_FACINGS:
        raise CalibrationError("calib_fit: facing must be front, back, %s or turned, got %r"
                               % (', '.join(SIDE_FACINGS), facing))
    if facing == 'turned':
        raise CalibrationError("calib_fit: a turned view has no calibrated projection, its columns mixing width "
                               'and depth: fit it with concept_fit or view_fit')
    if facing in SIDE_FACINGS:
        if cal.zero_px is None:
            raise CalibrationError('calib_fit: a side view facing %r needs zero_px, the column of model y = 0 '
                                   'in its pixels' % facing)
        s = 1 / cal.m(1)
        return dict(yaw=-90 if facing == 'left' else 90, pitch=0, s=s, ox=cal.zero_px, oy=s * cal.z(0), err=[])
    x0 = 0 if mid_px is None else mid_px
    (ax, _, az), (bx, _, _) = cal.model(x0, 0, 0, mid_px), cal.model(x0 + 100, 100, 0, mid_px)
    s = 100 / (bx - ax)
    return dict(yaw=180 if facing == 'back' else 0, pitch=0, s=s, ox=x0 - s * ax, oy=s * az, err=[])


def project(names, fit, palette, out, zmin=None, marks=(), exclude_parts=(), include_parts=()):
    """The faces of the named mesh objects that face the viewer, projected by a view_fit into the
    reference image's pixels, as JSON for imaging.overlay: the build over the drawing, which shows
    a shape off where the landmark numbers match (eye liners that meet at the bridge, an ear sunk into
    the skull). Objects after the first (bake sources) are drawn over it. palette: the
    character's {name: rgb}; marks: pixels to cross (the fit's points). Returns the face count.
    include_parts optionally restricts projection to those face parts before rasterisation; it needs the
    objects' part layer.
    exclude_parts: part names whose faces are left out, on every object that has them (its 'parts'
    property and 'part' attribute); a face belongs to the part most of its vertices carry, its first
    vertex breaking a tie (lpk.stages.checks.face_parts). Leave out limbs whose drawn pose differs
    from the build's: they cover the body they are compared against."""
    import json
    R = _turn(fit['yaw'], fit['pitch'])
    keys = list(bpy.data.objects[names[0]]['palette'])
    faces = []
    for k, name in enumerate(names):
        ob = bpy.data.objects[name]; me = ob.data; M = ob.matrix_world
        idx = me.attributes['pal'].data
        drop = _part_filter(ob, exclude_parts)
        outside = (_part_filter(ob, [part for part in ob.get('parts', ()) if part not in include_parts])
                   if include_parts else None)
        if include_parts and (not ob.get('parts') or 'part' not in ob.data.attributes):
            raise ValueError('include_parts needs the objects\' part layer')
        for p in me.polygons:
            c = M @ p.center
            if (R @ (M.to_3x3() @ p.normal)).y > -0.05 or (zmin is not None and c.z < zmin):
                continue
            if (drop is not None and drop(p.vertices)) or (outside is not None and outside(p.vertices)):
                continue
            q = [R @ (M @ me.vertices[i].co) for i in p.vertices]
            faces.append(((R @ c).y - k, keys[idx[p.index].value],
                          [[round(fit['ox'] + fit['s'] * v.x, 1), round(fit['oy'] - fit['s'] * v.z, 1)] for v in q]))
    json.dump({'faces': faces, 'pal': {k_: list(v) for k_, v in palette.items()}, 'marks': [list(m) for m in marks]},
              open(out, 'w'))
    return len(faces)


def _part_filter(ob, exclude_parts):
    """None when nothing of `ob` is excluded, else a test of a polygon's vertex ids: True when the
    part most of them carry (the first vertex breaking a tie) is one of exclude_parts."""
    if not exclude_parts or 'parts' not in ob or 'part' not in ob.data.attributes:
        return None
    parts = list(ob['parts'])
    ids = {parts.index(p) for p in exclude_parts if p in parts}
    if not ids:
        return None
    from collections import Counter
    pa = [a.value for a in ob.data.attributes['part'].data]
    return lambda verts: Counter(pa[i] for i in verts).most_common(1)[0][0] in ids


def isolate(obj_name, part, out_name='PartView', offset=(0, 0, 3.0), collection=None):
    """A posed part cut out of the evaluated mesh into its own object (with UVs, the materials, the faces'
    material indices and the `Col` corner colours the 'color' shade shows), the faces all of whose vertices
    carry the part, centred at `offset`: a hand or a foot in place hides behind the body. collection: the
    name of the collection the object goes into (created and linked to the scene when missing, as
    lpk.core.builder.finish does), e.g. the model's own; None links it to the scene's master collection.
    Returns the object."""
    ob = bpy.data.objects[obj_name]
    ev = ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
    me = ev.to_mesh()
    parts = list(ob['parts']); pid = parts.index(part)
    pa = [a.value for a in ob.data.attributes['part'].data]
    keep = [p for p in me.polygons if all(pa[i] == pid for i in p.vertices)]
    vids = sorted({i for p in keep for i in p.vertices})
    remap = {i: k for k, i in enumerate(vids)}
    co = [ob.matrix_world @ me.vertices[i].co for i in vids]
    c = sum(co, Vector()) / len(co)
    uvl = me.uv_layers.active
    uvs = [[tuple(uvl.data[li].uv) for li in p.loop_indices] for p in keep] if uvl else None
    faces = [tuple(remap[i] for i in p.vertices) for p in keep]
    slots = [p.material_index for p in keep]
    col = me.color_attributes.get('Col')
    cols = ([[tuple(col.data[li].color) for li in p.loop_indices] for p in keep]
            if col is not None and col.domain == 'CORNER' else None)
    ev.to_mesh_clear()
    old = bpy.data.objects.get(out_name)
    if old:
        bpy.data.objects.remove(old, do_unlink=True)
        bpy.context.view_layer.update()  # a removed object stays as None in view_layer.objects until an update
    m = bpy.data.meshes.new(out_name)
    m.from_pydata([tuple(p - c + Vector(offset)) for p in co], [], faces)
    if uvs:
        lay = m.uv_layers.new(name='UVMap')
        for p, fu in zip(m.polygons, uvs):
            for li, uv in zip(p.loop_indices, fu):
                lay.data[li].uv = uv
        for material in ob.data.materials:
            m.materials.append(material)
        for p, slot in zip(m.polygons, slots):
            p.material_index = slot
    if cols:
        lay = m.color_attributes.new('Col', 'FLOAT_COLOR', 'CORNER')
        for p, fc in zip(m.polygons, cols):
            for li, c in zip(p.loop_indices, fc):
                lay.data[li].color = c
        m.color_attributes.active_color = lay
    o = bpy.data.objects.new(out_name, m)
    if collection is None:
        bpy.context.scene.collection.objects.link(o)
    else:
        coll = bpy.data.collections.get(collection) or bpy.data.collections.new(collection)
        if coll.name not in bpy.context.scene.collection.children:
            bpy.context.scene.collection.children.link(coll)
        coll.objects.link(o)
    return o


def _evaluated(ob):
    ev = ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
    me = ev.to_mesh()
    co = [ob.matrix_world @ v.co for v in me.vertices]
    ev.to_mesh_clear()
    return co


def _area(co, poly):
    """The area of a polygon of vertex positions co, fanned from its first corner (square metres)."""
    p = [co[i] for i in poly.vertices]
    return sum((p[k] - p[0]).cross(p[k + 1] - p[0]).length / 2 for k in range(1, len(p) - 1))


def join_metrics(obj_name, rig_name, pose, pairs, rings=2):
    """How a pose deforms each join zone of a rigged mesh, against the rest pose.

    obj_name: the skinned mesh object; rig_name: its armature; pose: {bone: pose entry}
    (lpk.stages.pose.channels); pairs: [{'parent', 'child', 'caps'}] join pairs (parent and child part
    names, caps as lpk.stages.rig.smooth_zones takes them); rings: the edge rings round each loop the zone
    takes (lpk.stages.rig.join_zones). The rig holds the pose it was found in again afterwards
    (lpk.stages.pose.held_pose).

    Returns {'<parent>/<child>': {'stretch': the largest edge length ratio posed over rest in the zone (1.0 or
    more), 'squash': the smallest (1.0 or less), 'area': the smallest face area ratio posed over rest,
    'loop_cm': how far the parent's hole loop vertices move, the largest in centimetres}}, in the order of
    pairs. A ratio says where a zone deforms most, never whether it looks right: look at the pose captures."""
    from lpk.stages import pose as pose_stage
    from lpk.stages import rig as rig_stage
    ob = bpy.data.objects[obj_name]
    me = ob.data
    zones = rig_stage.join_zones(ob, [(p['parent'], p['child'], p.get('caps')) for p in pairs], rings)
    with pose_stage.held_pose(rig_name, None):
        rest = _evaluated(ob)
        pose_stage.set_pose(rig_name, pose)
        posed = _evaluated(ob)
    out = {}
    for p, (zone, loop, _) in zip(pairs, zones):
        st, sq = 1.0, 1.0
        for e in me.edges:
            a, b = e.vertices
            if a in zone and b in zone:
                r = (posed[a] - posed[b]).length / max((rest[a] - rest[b]).length, 1e-6)
                st, sq = max(st, r), min(sq, r)
        ar = min((_area(posed, f) / max(_area(rest, f), 1e-9) for f in me.polygons
                  if all(i in zone for i in f.vertices)), default=1.0)
        drift = max(((posed[i] - rest[i]).length for i in sorted(loop)), default=0.0)
        out['%s/%s' % (p['parent'], p['child'])] = {'stretch': round(st, 2), 'squash': round(sq, 2),
                                                    'area': round(ar, 2), 'loop_cm': round(drift * 100, 1)}
    return out


def pose_captures(body, rig, out, poses, *, views=('front', 'q34', 'side'), width=1000):
    """The pose captures of a rigged body on one sheet: each pose set on the rig (lpk.stages.pose.set_pose),
    the body alone captured in each of `views` (body_views: framed on the rest shape, so a posed part can
    leave the frame) in the 'color' shade, the rig holding the pose it was found in again
    afterwards, also when a capture fails (lpk.stages.pose.held_pose). The sheet puts a pose in each column
    and a view in each row, every capture cut to its figure on one floor line (imaging.sheet(crop=True)), so
    the figures stay large when the sheet is read downscaled.

    body: the name of the body object, which names nothing else; rig: the name of its armature object; out:
    the folder of the captures, named <pose>_<view>.png, and of the sheet, poses.png; poses: {name: {bone:
    pose entry}} (lpk.stages.pose.channels), in column order; views: lpk.stages.view.VIEWS
    names; width: the captures' width in pixels.

    A bone a pose names that the rig lacks turns nothing, so the pose shows less than it names: those names
    are returned per pose, and a pose none of whose bones the rig has is left out, since its column would
    repeat the rest pose (the finger poses on a hand without finger bones).

    Returns {'sheet': the sheet's path (None when every pose was left out), 'files': the captures, pose by
    pose and view by view, 'ignored': {pose: [the bones it names that the rig lacks]} for the poses that name
    any, 'skipped': [the poses left out]}. Raises ValueError for views outside VIEWS; RuntimeError when the
    scene holds no mesh `body` or no armature `rig`."""
    from lpk.stages import pose as pose_stage
    views = (views,) if isinstance(views, str) else tuple(views)
    bad = [v for v in views if v not in view.VIEWS]
    if bad or not views:
        raise ValueError('views %s: use names of lpk.stages.view.VIEWS (%s)' % (bad or '()', ', '.join(view.VIEWS)))
    ob, arm = bpy.data.objects.get(body), bpy.data.objects.get(rig)
    if ob is None or ob.type != 'MESH':
        raise RuntimeError('no built object %r in the scene' % body)
    if arm is None or arm.type != 'ARMATURE':
        raise RuntimeError('no rig %r in the scene' % rig)
    out_dir = os.path.abspath(out)
    frames = body_views(body, views)
    bones = {pb.name for pb in arm.pose.bones}
    shots, files, ignored, skipped = [], [], {}, []
    with pose_stage.held_pose(rig):
        for tag, rotations in poses.items():
            missing = [b for b in rotations if b not in bones]
            if missing:
                ignored[tag] = missing
            if missing and len(missing) == len(rotations):
                skipped.append(tag)
                continue
            pose_stage.set_pose(rig, rotations)
            files += capture(out_dir, tag, frames, shade='color', keep=[body], width=width)
            shots.append(tag)
    sheet = None
    if shots:
        n = len(frames)
        order = [k * n + v for v in range(n) for k in range(len(shots))]
        labels = ['%s %s' % (tag, v) for tag in shots for v, _, _ in frames]
        sheet = save_image(imaging.sheet([load_image(files[i]) for i in order], len(shots),
                                              labels=[labels[i] for i in order], crop=True),
                                os.path.join(out_dir, 'poses.png'))
    return {'sheet': sheet, 'files': files, 'ignored': ignored, 'skipped': skipped}


# -- the build against a drawing and at its play size ----------------------------------------------------


def outline_diff(views, view, fit, objects, *, exclude_parts=(), target=None, picture=None):
    """The build's outline against the drawing's in one view, through a fit: where the build leaves the
    drawing, row by row, and each part's width against the drawn one, as pixel numbers.

    views: the reference views (lpk.core.views.Views). view: a views.json view; the ink of its image
    (imaging.read_ink) is the drawing, its ignore regions (lpk.core.views.Views.ignore) left unread. fit:
    a fit of view_fit, calib_fit or concept_fit ({'yaw', 'pitch', 's', 'ox', 'oy'}), which puts the build
    in the view's pixels. objects: the names of the mesh objects whose outline is compared (the body, the
    shape the export carries, or the blocks when no body is built). exclude_parts: part names left out of
    the build's outline (a limb drawn in another pose); the drawing keeps its ink there unless an ignore
    region of the view covers it, so without one the rows where such a part makes the drawn edge read as
    offsets. target: None reads the drawing's ink; or (H, W) bools of the view, the figure's own pixels
    when the ink holds more than the figure (labels, a neighbour cut by the crop), read with no compression
    noise. picture: the path of the PNG picture to write; None writes none.

    The build's outline is every face of the objects projected through the fit, each pixel carrying the
    part of the nearest face (lpk.stages.checks.face_parts gives a face its part). The pixels of an ignore
    region are read on neither side, and an outline's run that ends on a region has no edge there
    (silhouette_report's 'cuts'). The picture shows both outlines: grey where both cover a pixel, red where
    only the build does, blue where only the drawing does, the regions hatched. The geometry is the raw
    rest mesh: active shape keys, a posed armature and shape-changing viewport modifiers raise rather than
    being compared as rest geometry. Perspective drawings are not modelled.

    Returns silhouette_report's dict plus {'view', 'image': the drawing's path, 'picture': the picture's
    path or None, 'objects', 'excluded': the parts left out, 'unknown_excluded': those of exclude_parts on
    none of the objects, 'ignored': the view's ignore regions {name: reason}, 'fit': {'yaw', 'pitch', 's',
    'ox', 'oy'}, 'mpp': metres per pixel at the fit (1 / s), 'metrics': numerical.metrics of the two
    outlines}; a drawing whose ink imaging.read_ink refuses gives silhouette_report's place {'size', 'why'}
    without 'metrics'. Raises ValueError for views None, a view they do not hold, an ignore field
    lpk.core.views.Views.ignore refuses, a fit without a number for each of yaw, pitch, s, ox and oy, a
    target of another size than the view, no object, and an object that is no mesh in the scene or
    carries no part layer."""
    views = _checked(views, view)
    fit = _fit_of(fit)
    path = views.image(view)
    names = _names(objects)
    co, tris, tri_part, parts = _geometry(names)
    excluded = (exclude_parts,) if isinstance(exclude_parts, str) else tuple(exclude_parts)
    if target is None:
        ink, regions, labels, why = _ink(views, view)
    else:
        ink, regions, labels, why = _target(views, view, target)
    saved = None
    if ink is None:
        report = {'size': list(views.size(view)), 'why': why}
    else:
        keep = ~np.isin(tri_part, [parts.index(p) for p in excluded if p in parts])
        build = np.where(ink['ignored'], -1, _paint(co, tris[keep], tri_part[keep], fit, ink['mask'].shape))
        figure = ink['mask']
        report = silhouette_report(build, figure, parts, fit_px(fit), ink['noise_px'], labels, list(regions))
        report['metrics'] = numerical.metrics(build, figure, unread=labels > 0, names=parts)
        if picture is not None:
            saved = save_image(imaging.outline_picture(build >= 0, figure, labels > 0), _folder_of(picture))
    report.update({'view': view, 'image': path, 'picture': saved, 'objects': names, 'excluded': list(excluded),
                   'unknown_excluded': [p for p in excluded if p not in parts], 'ignored': regions,
                   'fit': {k: fit[k] for k in ('yaw', 'pitch', 's', 'ox', 'oy')}, 'mpp': 1.0 / fit['s']})
    return report


def silhouette_report(build, figure, names, fit_px=0.0, noise_px=0, ignored=None, regions=()):
    """Where a build's outline leaves a drawing's, in one view's pixels (numpy).

    build: (H, W) ints, the part index (into names) of the build's face over each pixel, -1 where none
    is; figure: (H, W) bools, the drawing's ink of the figure; fit_px: the fit's own error in pixels
    (fit_px), and noise_px: how far the drawing's compression noise reaches from it (imaging.read_ink),
    which the band floors add to the outlines' precision. ignored: None, or (H, W) ints, 0 where a pixel
    is read and k where the k-th of `regions` (the names of the view's ignore regions,
    imaging.region_labels) covers it: neither outline is read there. Offsets are whole pixels, positive
    where the build reaches past the drawing and negative where it stops short.

    Each row is read run by run: a run of pixels either outline covers, where both cover some pixel, is
    one piece of the figure seen in both, and its first and last columns are compared outline with
    outline (its left and right edges); pixels inside it that only one outline covers (a gap between a
    limb and the body that the other outline closes), and runs that only one outline covers, belong to
    that outline alone. So a part is compared with the part it overlaps, never with another one beside it.

    Returns {'size': [W, H]; 'fit_px'; 'noise_px'; 'floor': {'edge': EDGE_PX + noise_px + fit_px,
    'width': EXTENT_PX + 2 * (noise_px + fit_px)}, the precision of an edge and of a width in pixels;
    'height_px': the drawing's height in rows; 'top': {'offset': the drawing's top row minus the build's,
    'region', 'cut'}, and 'bottom': {'offset': the build's bottom row minus the drawing's, 'region', 'cut'},
    region the pixels [x0, y0, x1, y1] (x1 and y1 exclusive) between the two rows, cut the name of an ignore
    region over the top or under the bottom (no edge there) or None; 'edges': [[row, column, left, right]]
    for every run where both outlines cover a pixel, column its first, left the drawing's first column in it
    minus the build's, right the build's last minus the drawing's (None at an end beside an ignore region);
    'bands': each edge followed down the rows while its offset keeps one sign ('side' 'left' or 'right'),
    kept when the offset passes the edge floor in one of its rows, and each 8-connected piece of pixels
    only one outline covers, on the rows inside both outlines ('side' 'build_only' or 'drawing_only'), kept
    when it is both taller and wider than the edge floor and touches no ignore region; each band {'side', 'rows': [first, last], 'offset': the offset of largest size (the row count for
    a one-sided band), 'mean': the mean offset (None one-sided), 'width': the widest run of a one-sided band
    in pixels (None otherwise), 'part': the build's part at that edge, or under the band, in most of its
    rows or pixels (None where the build has none), 'region': the pixels the band spans, 'area': the pixels
    between the two outlines over the band (the sum of its offsets' sizes; for a one-sided band its pixel
    count), 'relative': the area over the drawing's ink across the band's rows (half of it for a left or
    right edge, whose offset is one side's), 'share': the band's row count over 'height_px'}; 'parts':
    {part: {'scale': its width in the build over the drawn one, 'build_px', 'drawn_px': the two widths,
    'rows': the rows measured, 'region': the pixels of both spans}, {'scale': None} for a part not
    measured, or for a width that is not the part's alone {'scale': None, 'shared': the other parts,
    'rows': [first, last] measured, 'region'}} for every part the build shows; 'cuts': {region name:
    {'rows': [first, last], 'region': the pixels [x0, y0, x1, y1] of the outline next to it}} for the
    ignore regions an outline ends on, where it may go on unseen; 'top' and 'bottom' also carry 'relative'
    and 'share' as a band does: the rows past the other outline's end are covered by one outline only, so
    'relative' is 1 (0 without an offset) and 'share' is the offset over 'height_px'}; or {'size', 'why'}
    when there is nothing to compare.

    A part's width is taken over the rows where it alone makes a run of the build's outline, both ends
    its own, and that run alone meets a run of the drawing, which meets no other run of the build: the
    build's span over those runs against the drawing's span over theirs. A part scaled about its centre
    reads its factor; one posed, turned or placed otherwise than drawn reads as a scale too, and one
    that never makes such a run is not measured. The drawing has no parts, so its span is the part's
    only where no other part shares the drawn piece: when the drawing's ink past the part's own run on
    a measured row goes on, through ink no part of the build covers, to touch another part of the build
    (ears, hair or a ruff drawn beside a head and built shorter or apart), the width is not read, and
    'shared' names those parts. A part the drawing joins to this one that the build does not show yet
    is not seen."""
    build = np.asarray(build)
    H, W = build.shape
    lab = np.zeros((H, W), np.int32) if ignored is None else np.asarray(ignored)
    U = lab > 0
    build = np.where(U, -1, build)
    F = np.asarray(figure, bool) & ~U
    B = build >= 0
    out = {'size': [W, H]}
    if not B.any():
        out['why'] = 'the build covers no pixel of the view at this fit'
        return out
    if not (B & F).any():
        out['why'] = "the build overlaps none of the drawing's ink at this fit"
        return out
    edge_floor = EDGE_PX + noise_px + fit_px
    out['fit_px'] = round(float(fit_px), 2)
    out['noise_px'] = noise_px
    out['floor'] = {'edge': round(edge_floor, 2), 'width': round(EXTENT_PX + 2 * (noise_px + fit_px), 2)}
    hb, hf = B.any(axis=1), F.any(axis=1)
    bl, br, fl, fr = _first(B), _last(B), _first(F), _last(F)
    rb, rf = np.flatnonzero(hb), np.flatnonzero(hf)
    lo = np.minimum(np.where(hb, bl, W), np.where(hf, fl, W))
    hi = np.maximum(np.where(hb, br, -1), np.where(hf, fr, -1))

    def between(r0, r1):
        r0, r1 = min(r0, r1), max(r0, r1)
        return [int(lo[r0:r1 + 1].min()), int(r0), int(hi[r0:r1 + 1].max()) + 1, int(r1) + 1]

    cuts = {}

    def cut(k, row, x0, x1):
        c = cuts.setdefault(int(k), [row, row, x0, x1])
        c[0], c[1], c[2], c[3] = min(c[0], row), max(c[1], row), min(c[2], x0), max(c[3], x1)

    def over(M, row, step):
        """The region over (step -1) or under (step 1) the pixels of outline M on `row`, None without one."""
        r = row + step
        if not 0 <= r < H:
            return None
        cols = np.flatnonzero(M[row] & U[r])
        if not cols.size:
            return None
        cut(lab[r, cols[0]], row, int(cols[0]), int(cols[-1]) + 1)
        return regions[lab[r, cols[0]] - 1]

    tall = int(rf[-1] - rf[0] + 1)
    out['height_px'] = tall
    ends = {'top': int(rf[0] - rb[0]), 'bottom': int(rb[-1] - rf[-1])}
    out['top'] = {'offset': ends['top'], 'region': between(rf[0], rb[0]),
                  'cut': over(F, rf[0], -1) or over(B, rb[0], -1)}
    out['bottom'] = {'offset': ends['bottom'], 'region': between(rf[-1], rb[-1]),
                     'cut': over(F, rf[-1], 1) or over(B, rb[-1], 1)}
    for side, n in ends.items():
        out[side].update(relative=1.0 if n else 0.0, share=round(abs(n) / tall, 3))
    first_in, last_in = max(rb[0], rf[0]), min(rb[-1], rf[-1])
    pieces = _outline_pieces(build, F, U)
    for p in pieces:
        for at in p['cut']:
            cut(lab[p['row'], at], p['row'], *p['span'])
    out['edges'] = [[p['row'], p['span'][0], p['left'], p['right']] for p in pieces if p['matched']]
    bands = []
    for side in ('left', 'right'):
        for track in _edge_tracks(pieces, side):
            for seg in _sign_runs(track, side):
                offs = np.array([p[side] for p in seg])
                if np.abs(offs).max() <= edge_floor:
                    continue
                k = 'b' + side[0]
                cols = [p[k] for p in seg] + [p['f' + side[0]] for p in seg]
                bands.append({'side': side, 'rows': [seg[0]['row'], seg[-1]['row']],
                              'offset': int(offs[np.argmax(np.abs(offs))]), 'mean': round(float(offs.mean()), 2),
                              'width': None, 'part': _most([build[p['row'], p[k]] for p in seg], names),
                              'region': [int(min(cols)), seg[0]['row'], int(max(cols)) + 1, seg[-1]['row'] + 1],
                              'area': int(np.abs(offs).sum())})
    for side, key in (('build_only', 'b_only'), ('drawing_only', 'f_only')):
        only = [(p['row'], s, e) for p in pieces if first_in <= p['row'] <= last_in for s, e in p[key]]
        mask = np.zeros((H, W), bool)
        for row, s, e in only:
            mask[row, s:e] = True
        labels, _ = imaging.components(mask)
        blobs = {}
        for row, s, e in only:
            blobs.setdefault(int(labels[row, s]), []).append((row, s, e))
        nearby = imaging.grown(U) if U.any() else None
        for k in sorted(blobs):
            blob = blobs[k]
            r0, r1 = blob[0][0], blob[-1][0]
            width = max(e - s for _, s, e in blob)
            box = [min(s for _, s, _ in blob), r0, max(e for _, _, e in blob), r1 + 1]
            if nearby is not None:
                gx0, gy0, gx1, gy1 = max(box[0] - 1, 0), max(r0 - 1, 0), min(box[2] + 1, W), min(r1 + 2, H)
                pix = labels[gy0:gy1, gx0:gx1] == k
                if (pix & nearby[gy0:gy1, gx0:gx1]).any():
                    for t in np.unique(lab[gy0:gy1, gx0:gx1][imaging.grown(pix) & U[gy0:gy1, gx0:gx1]]):
                        cut(t, r0, box[0], box[2])
                        cut(t, r1, box[0], box[2])
                    continue
            if r1 - r0 + 1 <= edge_floor or width <= edge_floor:
                continue
            under = np.concatenate([build[r, s:e] for r, s, e in blob]) if side == 'build_only' else ()
            bands.append({'side': side, 'rows': [r0, r1], 'offset': r1 - r0 + 1, 'mean': None,
                          'width': int(width), 'part': _most(under, names) if side == 'build_only' else None,
                          'region': box, 'area': int(sum(e - s for _, s, e in blob))})
    drawn = F.sum(axis=1)
    for b in bands:
        r0, r1 = b['rows']
        across = float(drawn[r0:r1 + 1].sum()) / (2.0 if b['side'] in ('left', 'right') else 1.0)
        b['relative'] = round(b['area'] / max(across, 1.0), 3)
        b['share'] = round((r1 - r0 + 1) / tall, 3)
    out['bands'] = bands
    out['parts'] = _part_widths(build, pieces, names, F)
    out['cuts'] = {regions[k - 1]: {'rows': [c[0], c[1]], 'region': [c[2], c[0], c[3], c[1] + 1]}
                   for k, c in sorted(cuts.items())}
    return _plain(out)


def _outline_pieces(build, F, unread=None):
    """The runs of the two outlines row by row (silhouette_report): one dict per run of pixels either
    outline covers, in row order and then column order: {'row', 'span': [first column, end column
    (exclusive)], 'matched': whether both outlines cover a pixel of it, 'cut': the columns past its ends
    that `unread` ((H, W) bools, the ignore regions' pixels) leaves unread, 'b_runs', 'f_runs': [[start,
    end]] the runs of the build and of the drawing in it, 'b_only', 'f_only': [[start, end]] the runs
    of pixels only the build or only the drawing covers that are not one of its edges, and on a matched
    run 'left', 'right' (silhouette_report's 'edges', None at an end beside an unread pixel), 'bl', 'br',
    'fl', 'fr': the first and last columns of the build and of the drawing in it}."""
    B = np.asarray(build) >= 0
    H, W = B.shape
    rows, starts, ends = imaging.runs(B | F)
    pieces = []
    for r, s, e in zip(rows.tolist(), starts.tolist(), ends.tolist()):
        b, f = B[r, s:e], F[r, s:e]
        p = {'row': r, 'span': [s, e], 'b_runs': _line_runs(b, s), 'f_runs': _line_runs(f, s)}
        p['cut'] = [] if unread is None else [c for c in (s - 1, e) if 0 <= c < W and unread[r, c]]
        both = np.flatnonzero(b & f)
        p['matched'] = bool(len(both))
        if p['matched']:
            ib, jf = np.flatnonzero(b), np.flatnonzero(f)
            p.update(bl=s + int(ib[0]), br=s + int(ib[-1]), fl=s + int(jf[0]), fr=s + int(jf[-1]))
            p['left'] = None if s - 1 in p['cut'] else p['fl'] - p['bl']
            p['right'] = None if e in p['cut'] else p['br'] - p['fr']
            a, z = int(both[0]), int(both[-1]) + 1
            p['b_only'] = _line_runs(b[a:z] & ~f[a:z], s + a)
            p['f_only'] = _line_runs(f[a:z] & ~b[a:z], s + a)
        else:
            p['b_only'], p['f_only'] = p['b_runs'], p['f_runs']
        pieces.append(p)
    return pieces


def _line_runs(line, offset=0):
    """[[start, end]] of the runs of True in a 1-D bool array, end exclusive, shifted by offset."""
    d = np.diff(np.concatenate([[0], np.asarray(line, np.int8), [0]]))
    return [[offset + int(a), offset + int(b)] for a, b in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1))]


def _edge_tracks(pieces, side):
    """The matched runs of _outline_pieces linked down the rows into one track per edge of `side`
    ('left' or 'right'): a run continues the track of the run above it that it touches (8-connected),
    the left edge that of the leftmost such run when it is that run's leftmost touching run below, the
    right edge likewise from the right; any other run starts a track. Returns [[piece, ...]] in row
    order within each track."""
    by_row = {}
    for p in pieces:
        if p['matched']:
            by_row.setdefault(p['row'], []).append(p)
    pick = min if side == 'left' else max
    end = 0 if side == 'left' else 1
    tracks, prev, prev_tracks = [], [], []
    for r in sorted(by_row):
        cur = by_row[r]
        if not prev or prev[0]['row'] != r - 1:
            prev, prev_tracks = [], []
        cur_tracks = []
        for c in cur:
            above = [i for i, q in enumerate(prev) if _touch(q, c)]
            i = pick(above, key=lambda i: prev[i]['span'][end]) if above else None
            below = [d for d in cur if _touch(prev[i], d)] if i is not None else []
            if below and pick(below, key=lambda d: d['span'][end]) is c:
                t = prev_tracks[i]
            else:
                t = len(tracks)
                tracks.append([])
            tracks[t].append(c)
            cur_tracks.append(t)
        prev, prev_tracks = cur, cur_tracks
    return tracks


def _touch(a, b):
    """Whether two runs of _outline_pieces in neighbouring rows touch, corners included."""
    return a['span'][0] <= b['span'][1] and b['span'][0] <= a['span'][1]


def _sign_runs(track, side):
    """A track's runs of consecutive pieces whose `side` offset keeps one sign, zero offsets and ends with
    no edge (None) ending a run."""
    out = []
    for p in track:
        sg = 0 if p[side] is None else int(np.sign(p[side]))
        if sg and out and out[-1][-1]['row'] == p['row'] - 1 and int(np.sign(out[-1][-1][side])) == sg:
            out[-1].append(p)
        elif sg:
            out.append([p])
    return out


def _part_widths(build, pieces, names, figure=None):
    """silhouette_report's 'parts', over the matched runs of _outline_pieces; with the figure (the
    drawing's pixels read), a width whose drawn piece other parts share (_sharing) is not read."""
    B = np.asarray(build)
    acc = {}
    for p in pieces:
        if not p['matched'] or p['cut'] or len(p['b_runs']) != 1 or len(p['f_runs']) != 1:
            continue
        (s0, e0), (a, b) = p['b_runs'][0], p['f_runs'][0]
        r = p['row']
        k = int(B[r, s0])
        if k != int(B[r, e0 - 1]):
            continue
        if k not in acc:
            acc[k] = [s0, e0, a, b, 0, r, r, []]
        g = acc[k]
        g[0], g[1], g[2], g[3] = min(g[0], s0), max(g[1], e0), min(g[2], a), max(g[3], b)
        g[4] += 1
        g[6] = r
        if a < s0:
            g[7].append((r, a, s0))
        if e0 < b:
            g[7].append((r, e0, b))
    out = {}
    touch = None
    for k in np.unique(B[B >= 0]).tolist():
        name = names[k]
        if k in acc:
            x0, x1, a, b, n, r0, r1, past = acc[k]
            region = [min(x0, a), r0, max(x1, b), r1 + 1]
            if figure is not None and past and touch is None:
                touch = _touching(B, figure)
            shared = sorted(names[q] for q in _sharing(touch, past, k)) if touch is not None else []
            if shared:
                out[name] = {'scale': None, 'shared': shared, 'rows': [r0, r1], 'region': region}
                continue
            out[name] = {'scale': round((x1 - x0) / (b - a), 3), 'build_px': x1 - x0, 'drawn_px': b - a, 'rows': n,
                         'region': region}
        else:
            out[name] = {'scale': None}
    return out


def _touching(B, F):
    """(labels, {label: the build's part indices it touches}) of the drawing's ink no part of the build
    covers (F where B is -1), in 8-connected pieces: the parts each piece touches, corners included."""
    D = F & (B < 0)
    labels, _ = imaging.components(D)
    touch = {}
    for q in np.unique(B[B >= 0]).tolist():
        for lab in np.unique(labels[imaging.grown(B == q) & D]).tolist():
            touch.setdefault(lab, set()).add(q)
    return labels, touch


def _sharing(touch, past, k):
    """The part indices other than k whose outline shares part k's drawn piece (silhouette_report's width
    rule): those the drawing's ink past k's own runs (past: [(row, first, end column)]) touches through
    ink the build leaves uncovered (_touching's pieces). A part inside k's own run (a nose inside the
    head's front) is never past it, so it shares nothing."""
    labels, parts = touch
    hit = {int(lab) for r, a, b in past for lab in np.unique(labels[r, a:b]).tolist()}
    return {q for lab in hit for q in parts.get(lab, ())} - {k}


def fit_px(fit):
    """The pixel error a fit carries of its own: the root mean square of its points' errors ('err', as
    view_fit gives them), 0.0 for a fit without marked points (calib_fit's and concept_fit's, whose
    'err' is empty)."""
    err = [float(e) for e in (fit or {}).get('err') or ()]
    return math.sqrt(sum(e * e for e in err) / len(err)) if err else 0.0


def concept_fit(views, view, objects, *, exclude_parts=(), yaw_range=(-90, 90), pitch_range=(-20, 20),
                origin=(0, 0, 0)):
    """The yaw and pitch a turned concept is drawn at, fitted against the blocks or the build by the
    outline (fit_silhouette), and how far that pitch moves each landmark's row.

    views: the reference views (lpk.core.views.Views); view: the concept's view. objects: the names of the
    mesh objects fitted (the blocks, or the body once built). origin: the model's location in metres
    (world), the vertical axis the crown and the soles stand on. exclude_parts: parts left out of the fit
    (a limb drawn in another pose); the view's ignore regions (lpk.core.views.Views.ignore) leave their
    pixels out of the drawing and of the score, so a part left out on both sides, its drawn ink in a
    region, does not pull the fit. yaw_range, pitch_range: fit_silhouette's. A view with a metric
    calibration gives the fit its scale and sole row; one without fits them to the figure's rows
    (fit_silhouette). Either places the whole model, every vertex of the objects (fit_silhouette's anchor),
    so the parts kept stand at their height on it.

    Seen from above or below at pitch p, a point at depth d (metres along the view after the yaw, + away
    from the viewer) moves up the drawing by d * sin(p) against a point on the vertical axis through the
    model's location: s * d * sin(p) pixels at the fit's scale s. pitch_limit is the pitch at which that
    shift reaches PITCH_SHIFT_PX for the figure's depth (its farthest vertex from the axis along the view).
    A landmark's depth is that of the nearest face under its pixel at the fit (landmark_depths). A pitch
    fitted by the outline also takes up whatever the build and the drawing differ in (a pose, a
    proportion): compare the fit's 'mismatch' with its 'level_mismatch'.

    Returns {'view', 'image': the concept's path, 'objects', 'excluded', 'ignored': the view's ignore
    regions {name: reason}, 'fit': fit_silhouette's dict (it projects as view_fit's), 'pitch_limit':
    degrees, 'depth': metres, 'landmarks': landmark_depths' {name: {'px', 'depth', 'hit', 'off_px'}} with
    'shift_px', s * its depth * sin(pitch)}. Raises ValueError for views None, a view they do not hold, an
    ignore field lpk.core.views.Views.ignore refuses, a drawing whose ink imaging.read_ink refuses, an
    empty range, no object, and the fits fit_silhouette refuses."""
    views = _checked(views, view)
    names = _names(objects)
    co, tris, tri_part, parts = _geometry(names)
    excluded = (exclude_parts,) if isinstance(exclude_parts, str) else tuple(exclude_parts)
    anchor = np.unique(tris)
    tris = tris[~np.isin(tri_part, [parts.index(p) for p in excluded if p in parts])]
    try:
        cal = views.calib(view)
        s, feet = 1.0 / cal.mpp, cal.feet_px
    except CalibrationError:
        s = feet = None
    if int(yaw_range[1]) < int(yaw_range[0]) or int(pitch_range[1]) < int(pitch_range[0]):
        raise ValueError('concept_fit: empty range (yaw %r, pitch %r)' % (yaw_range, pitch_range))
    ink, regions, _, why = _ink(views, view)
    if ink is None:
        raise ValueError('concept_fit: %s' % why)
    fit = fit_silhouette(co, tris, ink['mask'], s, feet, yaw_range, pitch_range, ink['ignored'], anchor)
    origin = np.asarray(origin, np.float64)
    depth = float(np.abs(((co[np.unique(tris)] - origin) @ _turn_array(fit['yaw'], 0).T)[:, 1]).max())
    sp = math.sin(math.radians(fit['pitch']))
    marks = {n: dict(d, shift_px=round(fit['s'] * d['depth'] * sp, 2))
             for n, d in landmark_depths(co, tris, fit, views.landmarks(view), origin).items()}
    return {'view': view, 'image': views.image(view), 'objects': names, 'excluded': list(excluded),
            'ignored': regions, 'fit': fit, 'pitch_limit': round(pitch_limit(fit['s'], depth), 3),
            'depth': round(depth, 4), 'landmarks': marks}


def fit_silhouette(co, tris, ink, s=None, feet_px=None, yaw_range=(-90, 90), pitch_range=(-20, 20),
                   ignored=None, anchor=None):
    """The orthographic view of a mesh whose outline best covers a drawing's figure, in view_fit's yaw
    and pitch convention, found from the outline instead of marked points (numpy).

    co: (N, 3) vertex positions in metres; tris: (T, 3) vertex ids, the triangles whose outline is fitted;
    ink: (H, W) bools, the drawing's ink (imaging.ink_mask), whose largest 8-connected piece is the
    figure. s, feet_px: a metric calibration's pixels per metre and sole row, which hold the scale at s
    and the anchor's lowest point after the turn on row feet_px; None stretches the anchor's height
    after the turn over the figure's rows, its top on the figure's top. anchor: the vertex ids whose
    height places the mesh on the drawing, None for those of tris. Pass the whole model's when tris
    leave parts out (a limb drawn in another pose, or everything but a head drawn turned apart): the
    parts kept then stand at their height on the model, where the sole row and the figure's height
    put the whole model, instead of their own lowest point dropping onto the sole row. At each yaw and
    pitch the outline's centre column is put on the figure's, and the candidate is scored by the share
    of the figure's pixels the outline misses or overdraws.
    ignored: None, or (H, W) bools, the pixels of the view's ignore regions: read on neither side, they
    are left out of the figure, of the outline, of the centring and of the score. yaw_range,
    pitch_range: (first, last) whole degrees, both included. A coarse pass runs every
    FIT_YAW_STEP and FIT_PITCH_STEP degrees on the figure shrunk to about FIT_ROWS rows, then a fine one
    every degree round the best at the drawing's own pixels.

    Returns {'yaw', 'pitch', 's', 'ox', 'oy': view_fit's projection, 'err': [] (no marked points),
    'mismatch': the share of the figure's pixels the outline misses or overdraws, 'mismatch_mirrored':
    the share at the opposite yaw and the same pitch, so how much the drawing tells the turn from its
    mirror (None when the outline leaves the picture there), 'at_range_edge': view_fit's, over
    yaw_range, 'pitch_at_range_edge': whether the pitch is an end of pitch_range, 'pitch_step': the
    fine pass's step, 1 degree, the resolution of the pitch, 'level_yaw', 'level_mismatch': the best
    fit with a level camera, searched over yaw_range the same way (the fit's own when its pitch is 0;
    None when a level outline covers no pixel of the drawing)}.

    A front three-quarter and the back three-quarter at 180 degrees minus its yaw, with the pitch's sign
    turned, give one outline for a mirror-symmetric body: search the back with yaw_range. A figure the
    mesh does not stand for (another pose, a part or a prop the mesh lacks) pulls the fit; the mismatch
    says how well it covers. Raises ValueError for a drawing without ink, a mesh without triangles, an
    empty anchor, an empty range, a mesh that covers no pixel of the drawing at any yaw and pitch, and,
    without a calibration, a figure touched by an ignore region (a pixel of it among a figure pixel's
    eight neighbours; regions that overlap or touch count as one) that reaches above the figure's top
    row or below its bottom row: the region may hide the crown or the soles, so the figure's rows give
    no height to stretch over. A figure that ends on the picture's border is fitted as it is drawn."""
    co = np.asarray(co, np.float64).reshape(-1, 3)
    tris = np.asarray(tris, np.int64).reshape(-1, 3)
    (y0, y1), (p0, p1) = [(int(a), int(b)) for a, b in (yaw_range, pitch_range)]
    if not len(tris):
        raise ValueError('fit_silhouette: the mesh has no triangles')
    if y1 < y0 or p1 < p0:
        raise ValueError('fit_silhouette: empty range (yaw %r, pitch %r)' % (yaw_range, pitch_range))
    unread = np.zeros(np.shape(ink), bool) if ignored is None else np.asarray(ignored, bool)
    lab, sizes = imaging.components(np.asarray(ink, bool) & ~unread)
    if len(sizes) < 2:
        raise ValueError('fit_silhouette: the drawing has no ink')
    fig = lab == 1 + int(np.argmax(sizes[1:]))
    used = np.unique(tris)
    anchor = used if anchor is None else np.unique(np.asarray(anchor, np.int64).ravel())
    if not len(anchor):
        raise ValueError('fit_silhouette: the anchor holds no vertex')
    rows = np.flatnonzero(fig.any(axis=1))
    top, bottom = int(rows[0]), int(rows[-1])
    if s is None and unread.any():
        regions, _ = imaging.components(unread)
        touching = np.unique(regions[imaging.grown(fig) & unread])
        reach = np.flatnonzero(np.isin(regions, touching).any(axis=1))
        cut = [end for end, past in (('above its top', len(reach) and reach[0] < top),
                                     ('below its bottom', len(reach) and reach[-1] > bottom)) if past]
        if cut:
            raise ValueError("fit_silhouette: without a calibration the figure's rows give the scale, but an ignore "
                             'region touching the figure reaches %s row, where it may hide the figure going on'
                             % ' and '.join(cut))
    k = max(1, int(math.ceil(fig.shape[0] / FIT_ROWS)))
    levels = {1: fig, k: _shrink(fig, k)}
    if not levels[k].any():                  # a figure too thin to keep a pixel shrunk: search it unshrunk
        k = 1
        levels = {1: fig}
    hidden = {lv: unread if lv == 1 else _shrink(unread, lv) for lv in levels}
    centres = {lv: _centre_col(mk) for lv, mk in levels.items()}

    def score(yaw, pitch, lv):
        mask = levels[lv]
        q = co @ _turn_array(yaw, pitch).T
        qz = q[anchor, 2]
        if s is None:
            sc = (bottom - top + 1) / max(float(qz.max() - qz.min()), 1e-12)
            oy = top - 0.5 + sc * float(qz.max())
        else:
            sc, oy = float(s), float(feet_px) + float(s) * float(qz.min())
        cover = lambda ox: checks.cover(np.stack([(ox + 0.5) / lv - 0.5 + sc / lv * q[:, 0],
                                            (oy + 0.5) / lv - 0.5 - sc / lv * q[:, 2]], axis=1)[tris], mask.shape)
        ox = centres[1] - sc * float(q[used, 0].mean())
        raw = cover(ox)
        cov = raw & ~hidden[lv]
        if not cov.any():
            return math.inf, None
        dx = centres[lv] - _centre_col(cov)
        if lv > 1:
            dx = int(round(dx))
            cov = _shift_cols(raw, dx) & ~hidden[lv]
        else:
            cov = cover(ox + dx) & ~hidden[lv]
        return np.count_nonzero(cov ^ mask) / np.count_nonzero(mask), {'yaw': yaw, 'pitch': pitch, 's': sc,
                                                                       'ox': ox + dx * lv, 'oy': oy}

    def best(yaws, pitches, lv):
        found = (math.inf, None)
        for yaw in yaws:
            for pitch in pitches:
                got = score(yaw, pitch, lv)
                if got[0] < found[0]:
                    found = got
        return found

    def search(p0, p1):
        """(mismatch, fit) of the coarse pass over the whole range and the fine one round its best;
        (inf, None) from the coarse pass when nothing covers the drawing, (inf, {}) from the fine one."""
        _, coarse = best(_steps(y0, y1, FIT_YAW_STEP), _steps(p0, p1, FIT_PITCH_STEP), k)
        if coarse is None:
            return math.inf, None
        by, bp = coarse['yaw'], coarse['pitch']
        err, found = best(range(max(y0, by - FIT_YAW_STEP + 1), min(y1, by + FIT_YAW_STEP - 1) + 1),
                          range(max(p0, bp - FIT_PITCH_STEP), min(p1, bp + FIT_PITCH_STEP) + 1), 1)
        return err, {} if found is None else found

    err, fit = search(p0, p1)
    if fit is None:
        raise ValueError('fit_silhouette: the mesh covers no pixel of the drawing at any yaw and pitch')
    if not fit:
        raise ValueError('fit_silhouette: the mesh covers no pixel of the drawing round its coarse fit')
    fit['err'] = []
    fit['mismatch'] = round(float(err), 4)
    mirrored = score(-fit['yaw'], fit['pitch'], 1)[0]
    fit['mismatch_mirrored'] = round(float(mirrored), 4) if math.isfinite(mirrored) else None
    fit['at_range_edge'] = _at_range_edge(fit['yaw'], range(y0, y1 + 1))
    fit['pitch_at_range_edge'] = fit['pitch'] in (p0, p1) and p0 != p1
    fit['pitch_step'] = 1 if p1 > p0 else 0
    level_err, level = (err, fit) if fit['pitch'] == 0 else search(0, 0)
    fit['level_yaw'] = level['yaw'] if level else None
    fit['level_mismatch'] = round(float(level_err), 4) if level else None
    return fit


def landmark_depths(co, tris, fit, marks, origin=(0, 0, 0)):
    """Each landmark's depth under its pixel at a fit (numpy): {name: {'px': [x, y], 'depth': metres
    along the view after the fit's yaw (before its pitch) from the vertical axis through origin, + away
    from the viewer, 'hit': whether a face lies under the pixel, 'off_px': 0, or without a hit the pixel
    distance to the nearest vertex, whose depth it takes}}, in the order of marks. co, tris: as
    fit_silhouette's; marks: {name: [x, y]}, the view's landmarks; origin: the model's location, where
    its soles stand. The face nearest the viewer under the pixel gives the depth."""
    co = np.asarray(co, np.float64).reshape(-1, 3)
    T = np.asarray(tris, np.int64).reshape(-1, 3)
    q = co @ _turn_array(fit['yaw'], fit['pitch']).T
    d0 = ((co - np.asarray(origin, np.float64)) @ _turn_array(fit['yaw'], 0).T)[:, 1]
    u, v = fit['ox'] + fit['s'] * q[:, 0], fit['oy'] - fit['s'] * q[:, 2]
    ax, ay, bx, by, cx, cy = u[T[:, 0]], v[T[:, 0]], u[T[:, 1]], v[T[:, 1]], u[T[:, 2]], v[T[:, 2]]
    area = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
    ok = np.abs(area) > 1e-12
    area = np.where(ok, area, 1.0)
    used = np.unique(T)
    out = {}
    for name, (x, y) in marks.items():
        w0 = ((bx - x) * (cy - y) - (by - y) * (cx - x)) / area
        w1 = ((cx - x) * (ay - y) - (cy - y) * (ax - x)) / area
        w2 = 1.0 - w0 - w1
        hit = np.flatnonzero(ok & (w0 >= -1e-9) & (w1 >= -1e-9) & (w2 >= -1e-9))
        if len(hit):
            W = np.stack([w0[hit], w1[hit], w2[hit]], axis=1)
            j = int(np.argmin((W * q[T[hit], 1]).sum(axis=1)))
            depth, off = float((W[j] * d0[T[hit[j]]]).sum()), 0.0
        else:
            dist = np.hypot(u[used] - x, v[used] - y)
            i = int(np.argmin(dist))
            depth, off = float(d0[used[i]]), float(dist[i])
        out[name] = {'px': [x, y], 'depth': round(depth, 4), 'hit': bool(len(hit)), 'off_px': round(off, 1)}
    return out


def pitch_limit(s, depth):
    """Degrees: the pitch at which a point `depth` metres along the view from the vertical axis moves
    PITCH_SHIFT_PX pixels against it in a view of s pixels per metre, s * depth * sin(pitch) =
    PITCH_SHIFT_PX; 90 when even a level-to-vertical turn moves it less."""
    k = s * depth
    return 90.0 if k <= PITCH_SHIFT_PX else math.degrees(math.asin(PITCH_SHIFT_PX / k))


def play_size(body, read_px, *, views=('front', 'side', 'q34'), objects=None, shade='color', width=1000, out=None,
              images=True):
    """The model at its play size: captures box-downscaled to the on-screen height, the metres one screen
    pixel holds there, and how far each part of the body stands out in screen pixels. Whether a part reads
    at that size is the human's judgement, on the sheet.

    body: the name of the body object, which names the files too. read_px: the height in screen pixels
    the model stands at in play. views: lpk.stages.view.VIEWS names, framed on the body as body_views
    frames them; objects: the names of the objects shown, None the body alone; shade, width: as for
    capture. images=False measures the relief without viewport captures or PNGs. out: the output
    folder of the captures and the sheet, needed with images=True.

    Each capture is scaled by read_px over the body's height on it (its vertices through the viewport's
    projection), with imaging.scale's box filter, and saved at that size; the sheet shows the
    downscaled captures blown up again by one whole factor, nearest neighbour, so each screen pixel
    shows as a block. The metres per screen pixel are the body's height over read_px. A part's relief
    is the largest distance from one of its vertices to the nearest face of the body's other parts:
    how far a detail stands proud of what it sits on, or how far a limb reaches out of the body.

    Returns {'read_px', 'height': the body's height in metres, 'mpp': metres per screen pixel,
    'captures': [paths], 'files': [the downscaled captures' paths], 'sheet' (None when no view holds
    the body's height), 'figure_px': {view: the body's height in capture pixels; fewer than read_px means
    the capture is too small to downscale}, 'skipped': [views whose capture holds no height of the body,
    left out], 'relief': {part: {'m', 'px'}} (None for a part with no other part to stand out of)}.
    Raises ValueError for a read_px that is not a positive number, for views outside VIEWS and for
    images=True without out; RuntimeError when the body is not in the scene."""
    if not (isinstance(read_px, (int, float)) and not isinstance(read_px, bool) and math.isfinite(read_px)
            and read_px > 0):
        raise ValueError('read_px %r: the height in screen pixels, a positive number' % (read_px,))
    views = (views,) if isinstance(views, str) else tuple(views)
    bad = [v for v in views if v not in view.VIEWS]
    if bad or not views:
        raise ValueError('views %s: use names of lpk.stages.view.VIEWS (%s)' % (bad or '()', ', '.join(view.VIEWS)))
    if images and out is None:
        raise ValueError('play_size: images=True needs out, the folder of the captures and the sheet')
    ob = bpy.data.objects.get(body)
    if ob is None or ob.type != 'MESH':
        raise RuntimeError('no built object %r in the scene' % body)
    names = list(objects) if objects else [body]
    co = _world(body)
    frame = framing(body, views)
    captures, heights, files, small, labels, skipped = [], {}, [], [], [], []
    sheet = None
    if images:
        out_dir = os.path.abspath(out)
        os.makedirs(out_dir, exist_ok=True)
        with _viewport() as (r3, region), _hidden(names):
            for v in views:
                f = os.path.join(out_dir, '%s_%s.png' % (body, v))
                heights[v] = _shoot(v, shade, Vector(frame['centre']), frame['distance'], f, width,
                                    measure=lambda: _screen_height(r3, region, width, co))
                captures.append(f)
        for v, f in zip(views, captures):
            if not heights[v] > 0:
                skipped.append(v)
                continue
            arr = imaging.scale(load_image(f), read_px / heights[v])
            small.append(arr)
            labels.append('%s %g px' % (v, read_px))
            files.append(save_image(arr, os.path.join(out_dir, '%s_read_%s.png' % (body, v))))
        zoom = max(1, int(min(heights[v] for v in views if heights[v] > 0) // read_px)) if small else 1
        sheet = save_image(imaging.sheet([imaging.scale(a, zoom) if zoom > 1 else a for a in small],
                                              len(small), labels=labels),
                                os.path.join(out_dir, '%s_read_sheet.png' % body)) if small else None
    height = frame['height']
    relief = _relief(body)
    mpp = height / read_px
    return {'read_px': read_px, 'height': round(height, 4), 'mpp': round(mpp, 6), 'captures': captures, 'files': files,
            'sheet': sheet, 'figure_px': {v: round(h, 1) for v, h in heights.items()}, 'skipped': skipped,
            'relief': {p: None if r is None else {'m': round(r, 4), 'px': round(r / mpp, 2)}
                       for p, r in relief.items()}}


# -- helpers of the measurements -------------------------------------------------------------------------


def _ink(views, name):
    """(imaging.read_ink's dict of view `name`'s picture with its ignore regions left unread, the regions
    {name: reason} (lpk.core.views.Views.ignore), their labels (imaging.region_labels), None), or (None,
    the regions, None, why) when read_ink refuses the picture (imaging.InkMaskError, a ValueError: no
    clean background, lone pixels)."""
    regions = views.ignore(name)
    reasons = {n: r['why'] for n, r in regions.items()}
    try:
        arr = load_image(views.image(name))
        labels = imaging.region_labels(arr.shape, [r['px'] for r in regions.values()])
        return imaging.read_ink(arr, ignore=labels > 0), reasons, labels, None
    except ValueError as e:
        return None, reasons, None, "the drawing's ink cannot be told from its background: %s" % e


def _target(views, name, target):
    """_ink's tuple for a figure given as a mask: (H, W) bools of view `name`, its ignore regions left
    unread, with no compression noise. Raises ValueError for a mask of another size than the view."""
    regions = views.ignore(name)
    W, H = views.size(name)
    mask = np.asarray(target, bool)
    if mask.shape != (H, W):
        raise ValueError('target of shape %r: the view is %d x %d pixels' % (mask.shape, W, H))
    labels = imaging.region_labels((H, W), [r['px'] for r in regions.values()])
    unread = labels > 0
    return ({'mask': mask & ~unread, 'ignored': unread, 'noise_px': 0}, {n: r['why'] for n, r in regions.items()},
            labels, None)


def _checked(views, name):
    """views after checking that they hold view `name`; raises ValueError otherwise, and for views None."""
    if views is None:
        raise ValueError('view %r: no views.json holds the reference views' % name)
    if name not in views.names:
        raise ValueError('view %r is not in views.json; views: %s' % (name, ', '.join(views.names)))
    return views


def _names(objects):
    """The object names a measurement reads: `objects` as a list (one name alone taken as such); raises
    ValueError for none."""
    names = [objects] if isinstance(objects, str) else list(objects or ())
    if not names:
        raise ValueError('objects: the names of the mesh objects to compare, at least one')
    return names


def _folder_of(path):
    """path, absolute, after making its folder."""
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def _fit_of(fit):
    """fit after checking it carries a number for each key of a projection; raises ValueError otherwise."""
    bad = [k for k in ('yaw', 'pitch', 's', 'ox', 'oy') if not isinstance((fit or {}).get(k), (int, float))
           or isinstance(fit.get(k), bool) or not math.isfinite(fit[k])]
    if bad:
        raise ValueError('fit %r: needs a number for each of yaw, pitch, s, ox and oy (view_fit, calib_fit or '
                         'concept_fit give one); missing or not a number: %s' % (fit, ', '.join(bad)))
    return fit


def _plain(x):
    """x with numpy numbers and arrays as Python numbers and lists, tuples as lists and dict keys as
    strings, recursively: the JSON types a report takes."""
    if isinstance(x, dict):
        return {str(k): _plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_plain(v) for v in x]
    if not isinstance(x, (str, bytes)):
        if hasattr(x, 'tolist'):
            return _plain(x.tolist())
        if hasattr(x, 'item'):
            return x.item()
    return x


def _world(name):
    """(N, 3) world positions of a mesh object's vertices."""
    ob = bpy.data.objects[name]
    co = np.empty(len(ob.data.vertices) * 3, np.float64)
    ob.data.vertices.foreach_get('co', co)
    M = np.array(ob.matrix_world, np.float64)
    return co.reshape(-1, 3) @ M[:3, :3].T + M[:3, 3]


def _raw_rest_problem(ob):
    """Why the raw ob.data does not hold the visible rest mesh, or None. An identity or rest armature is
    fine; active relative keys, absolute-key interpolation, a posed or B-bone deformation and
    shape-changing viewport modifiers change the visible surface away from the raw mesh."""
    keys = getattr(ob.data, 'shape_keys', None)
    if keys is not None:
        blocks = list(keys.key_blocks)
        if len(blocks) > 1:
            if not getattr(keys, 'use_relative', True):
                return 'absolute shape-key interpolation is not supported'
            if getattr(ob, 'show_only_shape_key', False) and getattr(ob, 'active_shape_key_index', 0):
                return 'the displayed active shape key is not the raw basis'
            if any(not getattr(k, 'mute', False) and abs(k.value) > 0 for k in blocks[1:]):
                return 'an active shape key deforms the raw basis'
    for mod in getattr(ob, 'modifiers', ()):
        if not getattr(mod, 'show_viewport', True):
            continue
        if mod.type in ('NORMAL_EDIT', 'WEIGHTED_NORMAL'):
            continue
        if mod.type != 'ARMATURE':
            return 'active viewport modifier %r (%s) is not supported' % (mod.name, mod.type)
        arm = mod.object
        if arm is None or getattr(arm.data, 'pose_position', 'POSE') == 'REST':
            continue
        for bone in arm.pose.bones:
            if getattr(bone.bone, 'bbone_segments', 1) > 1:
                return 'posed B-bone evaluation is not supported; use explicit armature rest display'
            if not np.allclose(np.asarray(bone.matrix), np.asarray(bone.bone.matrix_local),
                               rtol=0, atol=REST_MATRIX_ATOL):
                return 'armature %r has a non-rest evaluated bone pose (%s)' % (arm.name, bone.name)
    return None


def _geometry(names):
    """(world vertex positions (N, 3), triangles (T, 3), each triangle's part index, part names) of the
    named mesh objects together, a part name on several objects one part, in order of first appearance.
    The raw rest mesh only: raises ValueError for a missing mesh or part layer and for a visible
    deformation (_raw_rest_problem); nothing is reset to obtain the rest shape."""
    layer = getattr(getattr(bpy, 'context', None), 'view_layer', None)
    if layer is not None:
        layer.update()  # Pose channels/drivers changed earlier in this call must reach their matrices.
    cos, tris, tparts, parts = [], [], [], []
    n = 0
    for name in names:
        ob = bpy.data.objects.get(name)
        if ob is None or ob.type != 'MESH':
            raise ValueError('%r is no mesh object in the scene' % name)
        if 'parts' not in ob or 'part' not in ob.data.attributes:
            raise ValueError("%r carries no 'part' layer and 'parts' list" % name)
        problem = _raw_rest_problem(ob)
        if problem:
            raise ValueError('%s: %s; the comparison reads the raw rest mesh: return the object to its rest pose '
                             'and basis shape first' % (name, problem))
        _, co, vpart, t, own = checks.read_mesh(name)
        for p in own:
            if p not in parts:
                parts.append(p)
        ids = np.asarray([parts.index(p) for p in own], np.int64)
        cos.append(co)
        tris.append(np.asarray(t, np.int64) + n)
        tparts.append(ids[checks.face_parts(vpart, t)] if len(t) else np.zeros(0, np.int64))
        n += len(co)
    return np.concatenate(cos), np.concatenate(tris), np.concatenate(tparts), parts


def _relief(obj_name):
    """{part: the largest distance in metres from one of its vertices to the nearest face of the other
    parts, or None when the object has no other part} of a mesh object's parts (play_size)."""
    from mathutils.bvhtree import BVHTree
    _, co, vpart, tris, names = checks.read_mesh(obj_name)
    fp = checks.face_parts(vpart, tris)
    verts = [tuple(p) for p in co.tolist()]
    out = {}
    for pid, name in enumerate(names):
        mine = np.flatnonzero(vpart == pid).tolist()
        if not mine:
            continue
        rest = tris[fp != pid]
        if not len(rest):
            out[name] = None
            continue
        tree = BVHTree.FromPolygons(verts, rest.tolist())
        far = 0.0
        for i in mine:
            hit = tree.find_nearest(verts[i])
            if hit[0] is not None:
                far = max(far, hit[3])
        out[name] = far
    return out


def _screen_height(r3, region, width, co):
    """The height in pixels of a capture of `width` (view.capture keeps the viewport's aspect) that the
    world points co span through the viewport's projection."""
    r3.update()
    P = np.array(r3.perspective_matrix, np.float64)
    h = np.concatenate([co, np.ones((len(co), 1))], axis=1) @ P.T
    y = h[:, 1] / h[:, 3]
    return float((y.max() - y.min()) / 2 * round(width * region.height / region.width))


def _turn_array(yaw, pitch):
    """_turn as a numpy array: the pitch about X after the yaw about Z (degrees)."""
    a, b = math.radians(yaw), math.radians(pitch)
    ca, sa, cb, sb = math.cos(a), math.sin(a), math.cos(b), math.sin(b)
    return np.array([[1, 0, 0], [0, cb, -sb], [0, sb, cb]]) @ np.array([[ca, -sa, 0], [sa, ca, 0], [0, 0, 1]])


def _paint(co, tris, tri_part, fit, shape, triangle_ids=False):
    """Rasterize orthographic triangles with interpolated per-pixel depth (smaller Y is nearer).
    Pixel centres are whole source-image coordinates, edges include a 1e-9 pixel tolerance,
    degenerate faces cover nothing. Exact depth ties keep the first input triangle, so the result follows
    the object and face order. Returns part ids (-1 background); triangle_ids=True also returns indices
    into the supplied triangle array."""
    q = np.asarray(co, np.float64) @ _turn_array(fit['yaw'], fit['pitch']).T
    uv = np.column_stack((fit['ox'] + fit['s']*q[:,0], fit['oy'] - fit['s']*q[:,2]))
    out = np.full(shape, -1, np.int32)
    owner = np.full(shape, -1, np.int64)
    depth = np.full(shape, np.inf)
    for index, (tri, part) in enumerate(zip(np.asarray(tris, np.int64).reshape(-1,3), tri_part)):
        t = uv[tri]
        u, v = t[1]-t[0], t[2]-t[0]
        area = u[0]*v[1]-u[1]*v[0]
        if abs(area) < 1e-18:
            continue
        lo = np.maximum(np.ceil(t.min(axis=0)-1e-9), 0).astype(int)
        hi = np.minimum(np.floor(t.max(axis=0)+1e-9), [shape[1]-1,shape[0]-1]).astype(int)
        if (lo > hi).any():
            continue
        yy, xx = np.mgrid[lo[1]:hi[1]+1,lo[0]:hi[0]+1]
        xy = np.stack((xx,yy),axis=-1)
        weights = []
        for k in range(3):
            a, b = t[(k+1)%3], t[(k+2)%3]
            weights.append(((b[0]-a[0])*(xy[...,1]-a[1])-(b[1]-a[1])*(xy[...,0]-a[0]))/area)
        z = sum(w*q[tri[k],1] for k,w in enumerate(weights))
        sl = np.s_[lo[1]:hi[1]+1,lo[0]:hi[0]+1]
        # Match cover's edge tolerance in pixels, independent of triangle size.
        inside = np.ones(xx.shape, bool)
        for k,w in enumerate(weights):
            edge_length = np.linalg.norm(t[(k+2)%3]-t[(k+1)%3])
            inside &= w*abs(area) >= -1e-9*edge_length
        visible = inside & (z < depth[sl])
        depth[sl][visible], out[sl][visible], owner[sl][visible] = z[visible], part, index
    return (out, owner) if triangle_ids else out


def _first(M):
    """Per row of a (H, W) mask: its first True column, -1 for a row without one."""
    return np.where(M.any(axis=1), M.argmax(axis=1), -1)


def _last(M):
    """Per row of a (H, W) mask: its last True column, -1 for a row without one."""
    return np.where(M.any(axis=1), M.shape[1] - 1 - M[:, ::-1].argmax(axis=1), -1)


def _most(ids, names):
    """The name of the part index most of ids (>= 0) hold, the lowest index on a tie; None without one."""
    ids = np.asarray(ids)
    ids = ids[ids >= 0]
    return names[int(np.bincount(ids).argmax())] if len(ids) else None


def _centre_col(mask):
    """The mean column of a mask's True pixels."""
    return float(np.nonzero(mask)[1].mean())


def _shift_cols(mask, d):
    """mask moved d whole columns right (left for a negative d), the columns it leaves empty."""
    if d == 0:
        return mask
    out = np.zeros_like(mask)
    if abs(d) < mask.shape[1]:
        if d > 0:
            out[:, d:] = mask[:, :-d]
        else:
            out[:, :d] = mask[:, -d:]
    return out


def _shrink(mask, k):
    """A mask k times smaller each way: a pixel is True when at least half of its k x k block is (the
    blocks past the edge padded False)."""
    H, W = mask.shape
    h, w = -(-H // k), -(-W // k)
    pad = np.zeros((h * k, w * k), bool)
    pad[:H, :W] = mask
    return pad.reshape(h, k, w, k).mean(axis=(1, 3)) >= 0.5


def _steps(first, last, step):
    """first, first + step, ... up to last, with last always included."""
    out = list(range(first, last + 1, step))
    if out[-1] != last:
        out.append(last)
    return out
