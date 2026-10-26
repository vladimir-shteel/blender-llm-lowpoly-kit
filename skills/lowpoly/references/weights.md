# Skeleton and weights

The `rig` stage builds `<NAME>_Rig` from a skeleton template and the joints `bones(P)` gives, parents the
body to it, and weights the body (`lpk.stages.rig.build_rig`, then `lpk.stages.rig.skin`). What it reads
from the model module is in [the model file](model-file.md); the review calls are in
[running](running.md#review-calls).

```python
SKELETON = 'biped'
ALLOWED = {'hair': ['Head'], 'ear.{s}': ['Head']}            # over the template's part binding
FIXED = {'buckle': {'Hips': 1.0}}                            # rigid parts, weights summing to one
JOINS = [('trunk', 'arm.{s}', {'UpperArm.{s}': 0.10}),       # (parent part, child part, caps)
         ('trunk', 'leg.{s}', {})]
WEIGHTS = 'heat_proxy'                                       # a backend, or 'auto'
EXTRA_BONES = {'Prop': {'head': (0.2, 0.0, 1.0), 'tail': (0.2, 0.0, 1.1), 'parent': 'Hand.R',
                        'deform': False}}
TEST_POSE = {'UpperArm.L': (0, 0, 60), 'LowerLeg.L': (-45, 0, 0), 'Head': (0, 20, 0)}
```

## The template and its part binding

`lpk.skeletons.names()` lists the templates; `lpk.skeletons.load('biped')` gives its bones with their
roles, parents and rolls, its sides (`L` +X, `R` -X), its options, its part binding and its review poses.

- **Bones.** The rig has every bone the template does not mark optional, plus the optional bones
  `bones(P)` names: the biped's tail chain `Tail.1`, `Tail.2`, ... from 1 without a gap, and the mitten
  fingers `Index`, `Middle`, `Thumb` per side, complete or not at all. A hand without finger bones is
  rigid on its hand bone. The biped's `Neck`, `Shoulder` and `Toes` bones are optional too: a light rig
  (a low budget, a target that animates no neck, clavicle or toes) leaves them out of `bones(P)`, each
  side's pair together, and the bones they parent hang from the nearest bone the rig has (the head and the
  upper arms from the chest), unconnected. The poses leave out what the rig lacks (`ignored`). The biped has no twist bones; whether a target needs them is checked against
  its clips and its importer.
- **Names.** A template bone keeps the template's name; export profiles rename bones by role
  (`lpk.skeletons.role_of`) on a copy, during the export only.
- **Part binding.** `lpk.skeletons.part_binding(template, bones)` gives each part of the template the bones
  it may take weight from (the biped's `trunk`, `neck`, `head`, `arm.{s}`, `hand.{s}`, `leg.{s}`,
  `foot.{s}`, `tail`). The runner takes it for the rig's bones and updates it with `ALLOWED`; `FIXED`
  parts take the weights given. Every built part must be bound or fixed: parts the template does not
  name (hair, ears, gear) take the bone they move with through `ALLOWED`.
- **A body plan no template covers** is a question for the human, not a set of extra bones.

## Joints: bones(P)

`bones(P)` returns `{bone: (head, tail)}` in metres in the body's space, from the same measurements and
sections that built the mesh, so the joints follow when the measurements move:

- Put each joint where the mesh bends: the elbow and the knee at the sections the limb bends at, the
  shoulder at the arm's socket, the hip at the leg's top ring. A bone between two joints follows the bend.
- Hands are placed in the build's arm pose with the back of the hand facing out; fingers run through the
  mitten's or the hand form's own points.
- A digitigrade leg runs knee to hock, hock to ball, the toes forward.
- A tail is straight in the mesh with its bones evenly along it; a curl is a pose (`TEST_POSE`).
- A posture authored into the rest pose can be undone by an engine that retargets clips from its own
  reference pose: keep posture in the clips, not only in the rest.

`EXTRA_BONES = {name: {'head', 'tail', 'parent', 'roll'?, 'deform'?}}` adds the model's own bones after the
template's (ears, a prop socket, a root above the hips): `parent` a template bone the rig has, an earlier
extra bone or None, unconnected; `roll` a direction for the bone's Z axis at rest; `deform=False` for a
bone that deforms nothing. An extra bone never takes a template bone's name; it has no role, so profiles
keep its name, and a deform-only profile leaves out a non-deforming bone unless a deform bone hangs from
it. The part binding never names it: give it to parts through `ALLOWED` or `FIXED`. A bone that deforms
nothing cannot take weight.

## '{s}' and sides

`'{s}'` in a key of `ALLOWED` or `FIXED` and in a `JOINS` entry expands over the template's sides
(`lpk.skeletons.sided`): `{'ear.{s}': ['Head']}` binds `ear.L` and `ear.R`, and one `JOINS` entry gives one
join per side. A value that names `'{s}'` under a key without it raises: no side would fill it.
`bones(P)` and `EXTRA_BONES` give each side's bones by name.

## The weights backends

Every backend starts from the part-restricted distance weights (`lpk.stages.rig.distance_weights`) and
leaves them on any vertex it gives no weight; every backend's weights are then filtered by the part
binding and held to the influence limit. `WEIGHTS` names one of `lpk.stages.rig.BACKENDS`, or `'auto'`
(the default without `WEIGHTS`), which takes the first backend of `lpk.stages.rig.available_backends()`
that runs without an error: one model weights differently on another machine. Name the backend for a
model that must weight alike everywhere. `run.model(MODEL, stages=('rig',), backend='heat')` tries another
backend for one call; `report['rig']['skin']['weights']` says which ran (`backend`), which were
`available` and, under `'auto'`, which failed first (`skipped`).

| Backend | Choose it when | What it cannot see |
|---|---|---|
| `vhd` | the Voxel Heat Diffuse Skinning add-on and its binary are installed: heat through the volume does not jump the armpit, the crotch or a finger slit, and intersecting shells do not matter | a vertex that gets nothing on its part's bones keeps distance weights; a hung binary runs on past the call (`lpk.stages.rig.VHD_TIMEOUT`) |
| `heat_proxy` | the model must not depend on the add-on, or bone heat fails on open shells nested in others | heat is solved on a closed voxel copy: gaps narrower than a few voxels close and heat crosses them (fingers, an arm against the body); fixed parts are left out of the copy |
| `heat` | a closed, simple body without nested open shells | heat starts at the bones each vertex sees in a straight line: an island that sees none gets none, and the solve can fail for every bone at once, warning only in Blender's info log |
| `distance` | a quick first look | straight-line distance jumps every gap: a shoulder corner near the upper arm's bone follows a raised arm, a mitten's finger block crumples at its base |

- Raw heat leaks across parts (the head onto the shoulders, a trinket onto the thighs, a bracer onto the
  hand, a tail onto the legs); the part binding stops it. Check it by posing the neighbouring bone alone.
- The weights report counts the vertices a backend left on distance weights (`distance_kept_parts`) or
  without heat (`no_heat_parts`). `heat_proxy` also reports `far_parts`: vertices further from its copy
  than its reach, split into those in sight (`far_visible_parts`, their indices in `far_visible_verts`)
  and those another surface encloses (`far_enclosed_verts`). In sight, either the copy lost their shell,
  or they lie where two parts' volumes merge (between the legs, under an arm) and blend both parts like
  their neighbours. No count is a verdict: when a part lists far vertices in sight, pose the bones next
  to it in `run.poses` and look whether those vertices follow their neighbours; act on what the poses
  show. A finer voxel does not bring merged vertices within reach. Enclosed ones (a leg end inside a
  shoe) matter only when a pose uncovers them.

## Welded joins: Corrective Smooth baked into the weights

For each `JOINS` entry, random poses through a Corrective Smooth modifier give the smoothed shape, and every
vertex of the join zone (the parent's hole loop and the limb's first ring, grown a few edges) takes the
non-negative weights over its part's bones that reproduce it best (`lpk.stages.rig.smooth_zones`). It
carries the deltoid in one line instead of a crease at the weld.

- **The loop is found by its tag.** `lpk.forms.joins.armholes` and `leg_holes` tag the hole loops in the
  `join_loop` vertex layer (the body's builder needs it among its `vert_layers`); adjacency alone would
  also take in collar vertices `ridge_flip` connected to the sleeve.
- **The armhole's parent allows the upper arm.** The hole loop belongs to the parent part; without the
  upper arm among its bones the loop takes no weight from the arm while the limb's ring does, and the arm
  can break at the loop. The biped's `trunk` binding includes both upper arms; a garment part of the
  model's own takes it through `ALLOWED`.
- **Caps** (`{bone: share}`, the third item of a join) pin a bone's share on the parent's hole loop, on
  the loop's vertices whichever zone is solved, since neighbouring zones overlap. Without a cap the solve
  can give the loop enough of the limb's first bone that a raised arm lifts the side of the torso; a cap
  keeps the side at the cost of a kink on top of the shoulder. Neither is better by a number: compare the
  free bake and a capped one in the poses and let the human choose. A cap under
  `lpk.stages.rig.MIN_WEIGHT` is dropped.
- **No cap fixes a hole in the wrong place.** An armhole far below the shoulder leaves a deep armpit
  stretched in every variant, the body's side following a raised arm even under a cap: that goes back to
  the build and the human, never into weights.
- **The bake runs once per skin**, on that run's backend weights; smoothed weights are never smoothed again.
- **Mirror.** The random poses leave the sides uneven, so the right side then copies the left side's
  weights with `.L` and `.R` swapped; vertices without a twin keep their own, and
  `report['rig']['skin']['smooth']['mirror_unmatched_parts']` lists them. It should list only parts meant
  to be asymmetric, or a midline form cast vertex by vertex onto an uneven surface (a hair cap), whose
  weights stay its own. The runner mirrors over the whole body; `mirror` of `lpk.stages.rig.skin` ('zones',
  False) is not a model attribute.

Separate-shell limbs have no weld and no join: their weights are the backend's, and their roots are
judged for gaps and pierce-through in the poses, from below and behind, by the human in Blender
(`pose_test`; the pose sheet has no view from below).

## The influence limit

The skin keeps at most the smallest `influence_limit` of the `EXPORTS` profiles (`lpk.profiles.load`)
bones per vertex, `lpk.stages.rig.MAX_INFLUENCES` without `EXPORTS`; `report['rig']['skin']['influences']`
gives it. An export decided after the rig needs `rig` again before `export` only when a profile's limit is
lower than the limit the weights were made under.

## Reading the poses and the joins

After `rig`:

- `run.poses(MODEL)` sets each review pose of the skeleton template (`lpk.skeletons.poses`) and `TEST_POSE` (as `'test'`) and
  captures the body on one sheet, a pose per column, a view per row (`out/captures/poses/poses.png`); the
  rig returns to its pose afterwards. `ignored` lists per pose the bones it names that the rig lacks, which
  turn nothing; `skipped` the poses none of whose bones the rig has (the grip on a hand without finger
  bones). Read them before judging a pose. The framing reads the rest shape, so a posed part can leave the
  frame.
- `run.joins(MODEL, pose)` (a review pose's name, `'test'` or `{bone: degrees}`) returns, per
  `'<parent>/<child>'` join, `stretch` and `squash` (the largest and smallest edge-length ratio posed over
  rest in the zone), `area` (the smallest face-area ratio) and `loop_cm` (how far the hole loop moves).
  It says where a zone deforms most, never whether it looks right: less stretch is no better
  deformation. Zones that share vertices (two leg holes at a crotch seam) both read the deformation there.
- Look at the welded joins first (shoulders, armpits, hips), the most stretched first, then the hands and a
  tail. No tool reads the weights on a hole loop: judge them in the poses from the front and the side on
  the pose sheet, and from below in Blender (`pose_test`), not by reading vertex groups by hand.
- Show the deformation in the open `.blend`: `pose_test` sets `TEST_POSE`, `pose_rest` the rest pose. The
  test pose carries what the target's animations ask beyond the review poses (a head turn, a tail swing, a
  crouch, an arm swung back for a garment).
- A deformation tradeoff (a cap or none, another backend) is compared one change at a time, each run and
  shown in turn; the human says which stays.
