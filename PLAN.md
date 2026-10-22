# lowpoly-kit plan

The kit's structure is in [ARCHITECTURE.md](ARCHITECTURE.md). Open work:

## Deferred

- The hand unwrap: on the mannequin example, right after `freeze_texture` and before any edit,
  `run.check_uvs` lists hand faces on both hands with a texel density far below the rest of their
  island. The procedural unwrap squashes them, not the check. Fix the hand's
  seams or unwrap so a fresh frozen texture reports no hand faces; an intentional UV change, stated with
  a before/after in its commit.

### Ideas: further kinds of model

The skill branches by kind of model (`skills/lowpoly/references/kinds/`: `biped`, `prop`). Each further
kind lands as one card there with what it needs in `lpk` and its own worked example; the kind stays a
notion of the skill, never read by `lpk`.

- **Animated prop** (a chest with a lid, a door, a weapon with moving parts): a skeleton template
  `lpk/skeletons/prop.json` (a root and a chain the model sizes), export profiles for it (a profile's
  `bone_map` is checked against its skeleton), rigid binding through `FIXED`, and the review poses read
  from the template's `poses` instead of `stages.review.POSES`, which names biped bones (ARCHITECTURE.md,
  "Transition").
- **Quadruped**: a template `lpk/skeletons/quadruped.json`, forms for four legs and paws, a worked
  example.
- **First-person hands**: a template for the arms and the camera, forms of the forearm and the hand at
  first-person detail, and review framing from the camera's point of view.
- **Shared hard-surface forms**: a chamfered box, a hub, a hinge, a plate stack, merged from the local
  forms of several props into `lpk/forms/` on the human's request
  ([Where forms live](ARCHITECTURE.md#where-forms-live)).
- **A set of props in one module**: one model module holds one prop today.

## Open notes

- Rig building without a viewport: `skills/lowpoly/references/pitfalls.md` and `lpk/setup_check.py` say
  rig building and heat weights need a 3D Viewport, while CONTRIBUTING.md says `bpy` from pip runs every
  stage but the captures. Check in Blender which holds and make the three agree.
- `lpk.stages.export.export_fbx` hard-codes the FBX arguments the profiles' `exporter` already gives, and
  `tests/test_profiles.py` holds `unity_humanoid.json` equal to them: take the arguments from the profile
  alone and drop the test. Needs an export run in Blender.
- Six test files build their own Blender stand-ins (`_Vector`, `_Matrix`, `_Euler`): move them to
  `tests/blender_stand_ins.py`.
- ARCHITECTURE.md readability: the model module contract as one row per attribute; Build modes as a
  matrix of the two mode axes and a table of the build stamp's guards.
