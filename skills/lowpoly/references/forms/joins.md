# Limbs and joins

Limbs are lofts along their joint paths (`limbs.limb`, `shapes.path_rings`). Whether a limb is welded out
of the trunk or a separate shell is chosen with the human at the blockout
([style](../style.md#limbs-welded-or-separate-shells)); this card builds both.

Heads, hands, feet, ears and hair are separate shells set into their parents, their open ends hidden
inside, on either construction.

## The welded body, in order

`build_mesh(P)` builds a welded body in this order; the order is part of the output:

1. `b = Builder(PALETTE, vert_layers=(joins.LAYER,))`: the hole loops are tagged in that layer, which the
   rig's join smoothing reads.
2. `torso.trunk`, then `joins.armholes` and `joins.leg_holes` on its rings and the trunk's `edits.apply`
   ([torso-clothing.md](torso-clothing.md#the-trunk-as-one-surface)).
3. Per side, `joins.weld_limb` for the arm from its hole, and `joins.weld_leg` for the leg from its hole, each
   followed by its part's `edits.apply`. `b.mirror_part` copies a part but cannot weld it: each side welds into
   its own hole.
4. `shapes.ridge_flip` over each join's vertices with the trunk as the only parent, after the last weld and
   before anything is cast or projected onto the body.

```python
from mathutils import Vector

from lpk.core import edits
from lpk.core.shapes import ridge_flip
from lpk.forms import joins

SIDES = (('L', 1.0), ('R', -1.0))


def build_limbs(b, P, arm_holes, leg_holes, data):
    seams = {}
    for side, sx in SIDES:
        path, profile, d, out = arm_path(P, sx)            # model-module helpers over the A-pose frame
        k = joins.weld_limb(b, 'arm.' + side, arm_holes[side], path, profile[0], profile[1], profile[2:], None,
                            Vector((0.0, 1.0, 0.0)), 'skin', 'shirt', d, out)
        edits.apply(b, P, 'arm.' + side, data)
        seams['arm.' + side] = k['verts']
        path, profile = leg_path(P, sx)
        _, verts = joins.weld_leg(b, 'leg.' + side, leg_holes[side], path, profile, None, Vector((sx, 0.0, 0.0)),
                                  'trousers', 'trousers', follow=P['hem_follow'])
        edits.apply(b, P, 'leg.' + side, data)
        seams['leg.' + side] = verts
    for part in seams:                                     # after the last weld, before any cast onto the body
        ridge_flip(b, [v for v in seams[part] if v.is_valid], ['trunk'])
```

The model module then lists the joins for the rig, `JOINS = [('trunk', 'arm.{s}', {'UpperArm.{s}': 0.10}),
('trunk', 'leg.{s}', {})]`, the caps keeping a parent's loop from following the limb too far.

## The armhole and its size

Cut the armholes between a pair of adjacent trunk rings over `torso.ARMHOLE_COLS`; the sleeve takes the hole's
size. Choose the pair so the hole sits at the anatomical shoulder, its bottom at the drawn armpit, not under it:
a hole reaching below the armpit welds the sleeve down the body's side. `armholes` cuts the hole with its inner
edges (deleting the faces alone would leave wire edges across it). `lpk.stages.checks.armhole_report(<body>)`
gives every hole loop's extents, keyed by the limb grown from it: compare left with right and with the drawn
armpit.

### An arm welded down the body's side

A weld down the body's side is valid topology: every count stays quiet while the arm reads as glued on.
Measure it: `armhole_report`'s hole much taller than the arm is thick, `limb_separation` with `z_range` from
the drawn armpit down touching where the front drawing shows background, and `outline_diff`'s front and side
bands under the armpit (a sleeve meeting the body far down with no volume of its own, a poncho). The poses
show it too (a deep armpit, the body's side following a raised arm); a comparison with the drawn arms
hanging agrees with the defect. Ask the human on every welded body to look in Blender, front, side and
three-quarter, whether the arm leaves the body where the drawing shows.

## Weld the arm: socket, corners, bridge

`weld_limb` grows the sleeve out of the armhole from a tilted socket section and bridges the rest of the
hole from the torso's own vertices; its docstring gives the socket, the welded corners and the bridge. A peak
on the shoulder (an `outline_diff` band at the shoulder rows of the front or back view) is a shoulder ring below the socket's top: raise that ring, or narrow the
socket with `socket_r`. Pass the returned `'verts'` to `ridge_flip`.

## Leg holes and the crotch

`leg_holes` splits the trunk's bottom ring into two leg holes round a crotch seam at `seam_z` (their size in
its docstring). Start its `tilt` from `LEG_TILT` and change a key only where `outline_diff`'s front, back and side
bands show the seam off the drawing at the hip or the seat; the values are metres, unscaled, sized for the height
range its docstring gives, and a figure far from it scales them in its own `build_mesh`. `seam_z` is where the seam shows, which need not be the drawn crotch (a seam there can read too low): the
human's call, looking in Blender from the front and the back. Make the pelvis's lower rings as wide as the trousers and nearly
square (`trunk`'s `boxes`), or its outer corners come out thinner than the thighs.

`weld_leg`'s `follow` starts the leg on the hole's own outline moved down the leg, the profile's shape from the
next ring: a first ring with an outline of its own sits off the hole and breaks a tight hem's line.

## `ridge_flip` after the welds

Moving a hole's corners onto the limb stretches the torso's ring edges across the join, and those fold a dent
between limb and body (the back of the shoulder). `ridge_flip` rotates each valley-folding edge into its other
diagonal where that lowers the summed valley. Pass the parent part only: rotating the limb's tube too can crease
the thigh or deepen the armpit. A rotation moves the surface, so a mark projected before it lies under the new
ridge and bakes a hole: run it before any cast onto the body. A rotated triangle takes the colour of the old one
under its centre. Have the human check the shoulder from three-quarter back in Blender.

## Separate-shell limbs

Per side, `limbs.limb` (or `shapes.profile_loft`, `shapes.point_loft`, a primitive or a local form) along
the arm frame or the leg's path, its first ring buried inside the parent by a negative arc length in the
profile; `shapes.snap_ring` lands that ring on the parent's surface when it must sit on it (pass `b=` so a miss
is counted), `shapes.hug_rings` lays rings just proud of the parent (a sleeve running up over the shoulder to
the collar). For a mirrored pair build the left side and copy it with `b.mirror_part`. The torso is any closed
loft at the model's density. No hole and no `ridge_flip`. A snapped or hugged root shares no vertex with its
parent, so a moving limb can open intersections at it: have the human look at each root from below and behind in
Blender, at rest and in the test pose (`pose_test`); the pose sheet (`run.poses`) has no view from below.

## The A-pose arm frame

`limbs.arm_frame(P, sx, ang)` gives the shoulder, elbow and wrist, `d` down the arm and `out` away from the body
(the back of the hand), from `P['sh_x']`, `P['sh_z']`, `P['upper_arm']`, `P['forearm']` and the A-pose angle
measured off the drawing; `sx` is the side's sign. Keep the frame in one model-module helper that the build and
`bones(P)` both read (the worked example's `arm_axes` and `arm_sections`): bones computed from another frame
drift off the mesh's bends.

## Which radius runs along which axis

`ra` runs along `ref` projected off the path and `rb` across it (`b = t x a`). On a horizontal path with
`ref = Z`, `ra` is the height: a sole given its width as `ra` builds a tall slab. On a leg with `ref = X`, `a` is
+X on both legs, so the inner side is `ra_neg` on the left leg and `ra` on the right.

## Limbs a garment or gear hides

Start a limb whose root a loose garment hides inside the garment with a flat cap instead of a weld; end a limb
inside the gear that encloses it with a flat cap and drop the rings it hides. Nothing hidden needs to be one
surface, and hidden rings cost triangles. Check from below and behind for a showing open end.

## Checking a join

- `lpk.core.shapes.join_report(bpy.data.objects[<body>], 'trunk', ['arm.L', 'arm.R'], locate=True)` counts wire,
  non-manifold and open edges, child vertices under the parent's surface and parent/child face intersections
  that share no vertex; `locate` adds their vertex and face ids. Trust the intersections first. Open edges
  belong only at the designed open ends (a neck top inside the head, a limb end inside a hand); a hole loop is
  never one. Never lower an intersection count by moving a seam: change the shape that intersects.
- `run.joins(path)` measures how the test pose deforms each join in `JOINS`; `run.poses(path)` shows the review
  poses on one sheet.
- A dent no count sees (a ring falling behind its neighbours): compare the hole's extents with the limb's first
  ring and have the human look at the join close from the front, back and side in Blender.

## Mesh health before accepting the build

Before the human accepts a full build, and for any part a local form or an edit changed, read the numbers
first: the build report's `degenerate` triangles per part (`report['build']['body']`), `join_report`'s wire,
non-manifold and open edges and intersections on every join, and `lpk.stages.checks.mirror_report` for the
pairs. What no number reads, duplicate surfaces and flipped normals, the human checks in Blender's
wireframe view and Face Orientation overlay. Fix the construction and rebuild. Tell a designed
opening, an intended overlapping shell and an unintended hole apart: not every part must be watertight, and
shells are not welded to satisfy a count. The join counts certify neither degeneracy nor normals nor every
crossing face; name any inspection you could not make.

## Limits

- The welded family is built for one density, `lpk.forms.torso.SIDES` vertices per trunk ring. The
  docstrings of `joins.armholes` and `joins.leg_holes` give the holes' sizes: `weld_limb` reads the
  armhole's vertices by index, and `weld_leg`'s `n` must equal the leg hole's (None takes it from the hole;
  another value raises `ValueError`). Another density needs separate shells or a local form.
- `move_part` and `ground_part` on a welded part stretch the faces it shares across the join.

## Rare cases

### Anatomy as a profile, not a tube

Where the muscle outline shows at the read size, an even tube reads as a pipe: give `limbs.limb` a profile of
arc-length entries `(s, ra, rb[, opts])` shaped with per-ring `'off'` shifts and radii where the drawing shows
them (the deltoid, the biceps, the forearm's bulge, a flat wrist); a blocky design may want the plain tube.
A joint bends across the rings round it: give it a ring above, at and below it, or it crumples in a pose, and
keep the pair of rings a few millimetres apart at a silhouette step (a sleeve hem). A ring that carries only a
colour boundary moves into a colour source under the texture stance. Check the bends in `run.poses`.

### Digitigrade and plantigrade legs

Plantigrade: hip, knee and ankle, a foot form at the ankle. Digitigrade: hip, knee, hock and ball, the knee
forward, the hock back and the ball on the floor, read off the side view; one loft with the colour split at the
knee and the toes as a part of their own at the ball ([feet.md](feet.md#digitigrade-feet)). Measuring an ankle
on a digitigrade-looking paw gives a raised heel; whether the raised heel is part of the read is the human's
call from the side in Blender. The path is a model-module helper the build and `bones(P)` share.

### Negative space between limbs

Where the drawing shows background between the limbs, the build must too, measured by `limb_separation`
below. Thin legs at their measured
spacing can read as one stick: propose a named spacing factor with that reason to the human.
`lpk.stages.checks.limb_separation(<body>, limb_parts, body_parts, z_range=...)` measures, row by row of the
front projection, where a limb touches the body (or another limb); pass `z_range` from the armpit down, since a
limb's root always touches.

### A limb unlike its pair

A limb that differs by design (a mechanical arm beside an organic one) is built on its own side, as a part of
its own, never mirrored, its rigid pieces pinned in `FIXED` ([gear.md](gear.md#rigid-pieces)). On a welded trunk
`armholes` opens and tags both holes: the different side either welds a short organic socket under its rigid
shell or closes its hole in a local form; the library has no one-sided armhole, and a hole left open is
an open edge no design intends. How the limb meets the body is the human's call at the blockout.
