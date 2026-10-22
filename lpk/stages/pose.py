"""The pose kernel: Euler rotations (degrees, bone-local XYZ) per bone, None restores the rest pose
(set_pose); and the scoped pose of a call that poses the rig only while it runs (held_pose), as the
export does in the rest pose. The pose is display state: a tool that poses the rig for its own work puts
the pose it found back."""
from contextlib import contextmanager

import bpy, math

# The pose-bone channels held_pose keeps and puts back.
CHANNELS = ('rotation_mode', 'location', 'rotation_quaternion', 'rotation_euler', 'rotation_axis_angle', 'scale')


def set_pose(rig_name, rotations=None):
    """Pose the armature `rig_name`: rotations {bone name: (x, y, z) Euler degrees, bone-local XYZ}, as
    in lpk.stages.review.POSES and a model's TEST_POSE. Every bone it does not name, and every bone when
    rotations is None, goes back to the rest pose (no rotation, no offset). Returns the names in
    `rotations` the rig has no bone for, in their order: they turn nothing ([] when every name is a
    bone)."""
    rig = bpy.data.objects[rig_name]
    for pb in rig.pose.bones:
        pb.rotation_mode = 'XYZ'
        r = (rotations or {}).get(pb.name, (0, 0, 0))
        pb.rotation_euler = [math.radians(x) for x in r]
        pb.location = (0, 0, 0)
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
