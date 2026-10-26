"""The pose kernel: per bone an Euler rotation (degrees, bone-local XYZ) and optionally an offset (metres,
bone-local), None restores the rest pose (set_pose); and the scoped pose of a call that poses the rig only
while it runs (held_pose), as the export does in the rest pose. The pose is display state: a tool that
poses the rig for its own work puts the pose it found back."""
from contextlib import contextmanager

import bpy, math

# The pose-bone channels held_pose keeps and puts back.
CHANNELS = ('rotation_mode', 'location', 'rotation_quaternion', 'rotation_euler', 'rotation_axis_angle', 'scale')


def channels(value):
    """The rotation (x, y, z) in degrees and the offset (x, y, z) in metres one pose entry gives: an entry is
    (x, y, z) Euler degrees, bone-local XYZ, or {'rot': (x, y, z) degrees, 'loc': (x, y, z) metres}, either
    key optional, the offset along the bone's own rest axes (a slide pulled back, a magazine dropped, a
    piston extended). Raises ValueError for any other entry."""
    if isinstance(value, dict):
        unknown = set(value) - {'rot', 'loc'}
        if unknown:
            raise ValueError('pose entry %r: keys are rot (degrees) and loc (metres), not %s'
                             % (value, ', '.join(sorted(map(str, unknown)))))
        rot, loc = value.get('rot', (0, 0, 0)), value.get('loc', (0, 0, 0))
    else:
        rot, loc = value, (0, 0, 0)
    try:
        rot, loc = tuple(float(c) for c in rot), tuple(float(c) for c in loc)
    except (TypeError, ValueError):
        raise ValueError('pose entry %r: give (x, y, z) degrees or {rot, loc}' % (value,)) from None
    if len(rot) != 3 or len(loc) != 3:
        raise ValueError('pose entry %r: rot and loc take three numbers each' % (value,))
    return rot, loc


def set_pose(rig_name, rotations=None):
    """Pose the armature `rig_name`: rotations {bone name: an entry channels() reads}, as in a skeleton
    template's review poses (lpk.skeletons.poses), a model's POSES and its TEST_POSE. Every bone it does
    not name, and every bone when rotations is None, goes back to the rest pose (no rotation, no offset).
    Returns the names in `rotations` the rig has no bone for, in their order: they turn nothing ([] when
    every name is a bone)."""
    rig = bpy.data.objects[rig_name]
    for pb in rig.pose.bones:
        pb.rotation_mode = 'XYZ'
        r, loc = channels((rotations or {}).get(pb.name, (0, 0, 0)))
        pb.rotation_euler = [math.radians(x) for x in r]
        pb.location = loc
    bpy.context.view_layer.update()
    bones = {pb.name for pb in rig.pose.bones}
    return [n for n in (rotations or {}) if n not in bones]


@contextmanager
def held_pose(rig_name, rotations=None):
    """Pose the armature `rig_name` for the block only: on entry every pose bone's channels (CHANNELS) are
    kept and the rig takes set_pose(rig_name, rotations), the rest pose for None; on exit, also after an
    error, every bone gets its kept channels back and the view layer is updated. Yields set_pose's list of
    the names `rotations` gives that the rig has no bone for."""
    rig = bpy.data.objects[rig_name]
    kept = [(pb, {c: _copy(getattr(pb, c)) for c in CHANNELS}) for pb in rig.pose.bones]
    try:
        yield set_pose(rig_name, rotations)
    finally:
        for pb, channels in kept:
            for c in CHANNELS:
                setattr(pb, c, channels[c])
        bpy.context.view_layer.update()


def _copy(value):
    """A channel's value detached from the pose bone: a string as it is, a vector as a tuple."""
    return value if isinstance(value, str) else tuple(value)
