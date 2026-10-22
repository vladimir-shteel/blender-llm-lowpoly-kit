# lowpoly-kit plan

The kit's structure is in [ARCHITECTURE.md](ARCHITECTURE.md). Open work:

## Deferred

- The hand unwrap: on the worked example, right after `freeze_texture` and before any edit,
  `run.check_uvs` lists hand faces on both hands with a texel density far below the rest of their
  island. The procedural unwrap squashes them, not the check. Fix the hand's
  seams or unwrap so a fresh frozen texture reports no hand faces; an intentional UV change, stated with
  a before/after in its commit.

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
