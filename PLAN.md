# lowpoly-kit plan

The kit's structure is in [ARCHITECTURE.md](ARCHITECTURE.md). Open work:

## Further kinds of model

The skill branches by kind of model (`skills/lowpoly/references/kinds/`: `biped`, `prop`). Each further
kind lands as one card there with what it needs in `lpk` and its own worked example; the kind stays a
notion of the skill, never read by `lpk`. Each stage below is one pull request, in this order:

1. **Shared hard-surface forms**: a chamfered prism and box, a hinge pin, a hub, a plate along a segment,
   a plate standing off a face, a slot, a mechanical hand, merged into `lpk/forms/hard.py` on the
   human's request ([Where forms live](ARCHITECTURE.md#where-forms-live)).
2. **Rigid mechanism** (a turret, a drone, a walking machine, a chest with a lid): a skeleton template
   `lpk/skeletons/rigid.json` with a root only, the model's bones in `EXTRA_BONES`, every part pinned to
   one bone through `FIXED`; the export stays one mesh and one armature. A worked example.
3. **Quadruped**: a template `lpk/skeletons/quadruped.json` with its review poses, forms for four legs,
   paws and a level trunk, a worked example.
4. **Atlas variants**: a model attribute naming palette and colour-source overrides, each baked into its
   own atlas on the same UVs and exported beside the first.
5. **Clip review**: a review call that bakes a clip from another skeleton onto the model's rig by a bone
   map (rotation deltas for the trunk and legs, directions for the arms, scaled hips, optional
   procedural tail sway and foot planting) and captures chosen frames.
6. **First-person arms**: a skeleton of fixed standard proportions (the `biped` template with `full`
   hands below; the arms carry the character in mesh volume, not bone lengths), arm and digit forms at
   first-person detail with the weights written while building (a weights backend), review framing from
   the first-person camera, a worked example. The `biped` template gains a `full` hands choice: three
   phalanges on each of five digits.

## Deferred

- The hand unwrap: on the mannequin example, right after `freeze_texture` and before any edit,
  `run.check_uvs` lists hand faces on both hands with a texel density far below the rest of their
  island. The procedural unwrap squashes them, not the check. Fix the hand's
  seams or unwrap so a fresh frozen texture reports no hand faces; an intentional UV change, stated with
  a before/after in its commit.
- **Environment** (modular rooms with door sockets, collision boxes, a palette texture shared by a set of
  rooms): needs its own design before it enters the kit.
- **A set of props in one module**: one model module holds one prop today.
