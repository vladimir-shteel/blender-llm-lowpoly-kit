# lowpoly-kit plan

The kit's structure is in [ARCHITECTURE.md](ARCHITECTURE.md). Open work:

## Next: static props

A prop is a model without a rig: a crate, a barrel, a lamp, a weapon held whole. The stages up to the
texture already take any mesh; the export and the skill assume a rigged biped. One pull request lands the
items below together ([Changing a contract](ARCHITECTURE.md#changing-a-contract), rule 4).

### Kinds of model in the skill

The skill stays one skill (AGENTS.md). It branches by the **kind of model**, a notion of the skill only:
the human chooses the kind at the brief, and `lpk` never reads or infers it. The code sees only the
module's attributes (`SKELETON` present or not, its template, `FACE_PART`, ...).

- `skills/lowpoly/SKILL.md`: the description names characters and props, so the skill is picked for
  both. A first table routes by kind to its card; the table of topic cards stays below it.
- `skills/lowpoly/references/kinds/`: one card per kind, the route of steps for that kind. Each step
  links the shared topic card and says only what the kind changes: the steps it has and skips, the
  module attributes it needs, its `SKELETON`, how its build splits into parts, its worked example. A card
  names no bone and no number; those live in `lpk` and its data.
  - `kinds/biped.md`: the current `references/process.md`, moved; every link to `process.md` follows.
  - `kinds/prop.md`: brief (triangle budget, atlas size, read size, export targets, and the pivot: the
    base on the floor at the origin, or the grip point for a held item; facing -Y), intake (often one or
    two views or none; the scale from a known size), the model file, the blockout, the build part by
    part (the prop's own parts, not body areas), the budget, freeze when needed, the texture without a
    face island, the export. No rig, `poses`, `joins` or pose stages.
- A kind's card lands together with what it needs in `lpk` and with its worked example; no card without
  an example.

### Shared cards

- `references/model-file.md`: the attribute set a prop needs (`NAME`, `PALETTE`, `props()`,
  `blocks(P)`, `build_mesh(P)`, `ATLAS`, `sheet_of`; optional `VIEWS`, `seams(P)`, `EXPORTS`) and the
  pivot rule.
- `references/style.md`: the defaults of hard surface where they differ from the organic ones: flat caps,
  hard edges, `seams(P)['hard']` for crisp island borders.
- `references/intake.md`: a note that the reading of landmarks and widths applies to an object as to a
  figure, with landmark names of the prop's own.
- `references/forms/gear.md` and `references/forms/README.md`: the hard-surface pieces a prop builds from
  the existing primitives (`Builder.box`, `Builder.loft` with flat caps, `shapes.profile_loft` for a
  turned part, `Builder.pyramid`) as local forms of the model.
- `references/export.md`: the export of a model without a rig.
- README.md, AGENTS.md and the docstring of `lpk/__init__.py`: characters and props; README's "Biped
  characters only for now" goes.

### Export without a rig

`export` needs the rig today: `run.export` requires `<NAME>_Rig`; `stages.export.export`,
`_export_copy`, `export_fbx`, `_export_glb` and `compare_import` take a rig name and select, copy, rename
and compare the armature.

- A model without `SKELETON` exports its body alone: `run.export` requires the body only when the module
  has no `SKELETON`, and the body and the rig when it has one. The stage functions take the rig as
  optional (None: no armature), never a second export route.
- The profile's skeleton fields (`skeleton`, `bone_map`, `deform_only`, `leaf_bones`,
  `influence_limit`) act on the rig only; a rigless export writes the mesh with the same exporter
  arguments. Decide in the pull request whether the shipped profiles serve both or a profile without a
  skeleton is allowed (`lpk.profiles.REQUIRED`).
- `compare_import` without a rig compares the mesh object count, triangles, UV layers, images and size,
  and reports an armature found in the import as a difference.
- ARCHITECTURE.md, "Model module contract": the `export` row says the rig is exported when the module
  has `SKELETON`.
- Tests: the pure parts of the profile check and the expected-bones logic with no rig.

### Worked example

- `examples/crate/` (or a barrel): a model module with references drawn by a script like the
  mannequin's, run from `reference` to `export` in Blender. It is the acceptance model of the prop kind
  (CONTRIBUTING.md, "Verifying a change") and the pattern `kinds/prop.md` names.

### Known limits to state, not fix

- `stages.review.MIN_HEIGHT` frames a model no closer than its value: a very small prop reads small in
  the captures.
- One model module per prop; a set of props in one module is not supported.

## Deferred

- The hand unwrap: on the worked example, right after `freeze_texture` and before any edit,
  `run.check_uvs` lists hand faces on both hands with a texel density far below the rest of their
  island. The procedural unwrap squashes them, not the check. Fix the hand's
  seams or unwrap so a fresh frozen texture reports no hand faces; an intentional UV change, stated with
  a before/after in its commit.

### Ideas: further kinds of model

Each lands as one card in `skills/lowpoly/references/kinds/` with what it needs in `lpk` and its own
worked example.

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
