# The model file

One Python file per model, next to its `views.json`, `refs/` and an `out/` folder the kit writes (a
model without references has neither: [without references](intake.md#without-references)).
It holds data and composition only: every number is a measurement, a style choice with its reason, or a
form's parameter. The worked example of the model's kind is the pattern (`examples/mannequin/mannequin.py`
for a character, `examples/trooper/trooper.py` for a light character without references,
`examples/hound/hound.py` for a quadruped, `examples/fp_arms/fp_arms.py` for first-person arms, `examples/barrel/barrel.py` for a prop, `examples/turret/turret.py` for a
rigid mechanism); copy its layout. The listing below is a
character's; [a prop](#a-prop) leaves out the rig's attributes.

## What each stage reads

ARCHITECTURE.md "Model module contract" is the full list; a stage that needs an attribute the module
lacks raises, naming it.

```python
NAME = 'Mannequin'                       # objects <NAME>, <NAME>_Rig, <NAME>_Atlas, ...
VIEWS = 'views.json'                     # paths are relative to the module's folder
REFS = ('front', 'side', 'back')         # optional: the views the reference stage shows, none of mode 'none'
EDITS = 'edits.json'                     # the human's hand edits; capture_edits writes it
FROZEN = False                           # True: build copies <NAME>_Frozen (freeze or adopt makes it)
TEXTURE_FROZEN = False                   # True (with FROZEN): keep the UVs and atlas freeze_texture stored
ADOPT = 'Imported'                       # only for adopt: the mesh object of an existing model
PALETTE = {'skin': (0.87, 0.71, 0.60), 'shirt': (0.27, 0.48, 0.62)}   # sRGB, sampled off the drawing

def props(): ...                 # measurements in metres off views.json: one dict P
def blocks(P): ...               # [(kind, part, colour, args)]: the shape blockout
def build_mesh(P): ...           # (body Builder, {source: Builder})

ATLAS = (512, {'Body': 1.0, 'Outfit': 1.0})    # size in pixels, {group: relative texel density}
def sheet_of(colour, part): ...                 # the atlas group of a face
FACE_PART, FACE_TEXELS = 'head', 400            # the face island and its texels per metre
def face_pred(P): ...                           # (centre, normal) -> bool over the head's faces
SOURCES = {'Face': {'mask': ('head',)}}         # colour sources in bake order, each within its parts;
                                                # 'over': True adds one over a frozen texture
def seams(P): ...                               # {'cuts', 'panels', 'hard'}: the seamed unwrap

SKELETON = 'biped'
def bones(P): ...                               # {bone: (head, tail)} in metres
ALLOWED = {'hair': ['Head'], 'ear.{s}': ['Head']}   # bones per part over the template's binding
JOINS = [('trunk', 'arm.{s}', {'UpperArm.{s}': 0.10})]   # welded joins to smooth, caps per join
TEST_POSE = {'UpperArm.L': (0, 0, 60), 'Head': (0, 20, 0)}
EXPORTS = ('glb_generic', 'fbx_generic')        # only once the human asks for an export
```

`'{s}'` in `ALLOWED`, `FIXED` and `JOINS` expands per side (`lpk.skeletons.sided`).

## A prop

A model without a rig defines the attributes up to the atlas and the export, and none of the rig's:

```python
NAME = 'Barrel'
VIEWS = 'views.json'
EDITS = 'edits.json'
PALETTE = {'wood': (0.55, 0.36, 0.20), 'iron': (0.25, 0.25, 0.27)}

def props(): ...                 # measurements in metres off views.json
def blocks(P): ...               # [(kind, part, colour, args)]
def build_mesh(P): ...           # (body Builder, {}): no colour source unless the prop paints one

ATLAS = (256, {'Prop': 1.0})
def sheet_of(colour, part): ...
def seams(P): ...                # optional: the seamed unwrap
EXPORTS = ('glb_generic', 'fbx_generic')   # only once the human asks for an export
```

- **No `SKELETON`.** `rig`, `pose_test`, `pose_rest`, `run.poses` and `run.joins` need a rig and raise;
  `export` writes the body alone, and the profile's skeleton keys (`bone_map`, `deform_only`,
  `leaf_bones`, `influence_limit`) act on no bone.
- **No face island** (`FACE_PART`, `face_pred`, `FACE_TEXELS`) unless painted detail needs one.
- **The pivot is the origin.** Build the prop round the pivot the brief names: a standing prop's base
  centre on z = 0, a held prop's grip, a hung prop's hook; its front faces -Y.
- **Shared functions.** As a character's sections are, a prop's profile is one function of P that
  `blocks(P)`, `build_mesh(P)` and `seams(P)` read (`stave_radius` and `stave_rings` in the example).

## Measurements: props()

`props()` reads `views.json` through `lpk.core.views.Views` and returns plain numbers and tuples in metres
(and radians): `views.calib('front').z(row)` for a height, `.m(px)` for a length,
`views.calib('side').side(px, py)` for a depth and height, `views.landmarks(view)` and
`views.widths(view)` for the readings of the [intake](intake.md). Style factors (a head drawn small and
built larger) and values the drawings do not give are named constants above `props()`, each with a
comment saying why. The runner adds `P['edits']`, the stored hand edits.

## Sections shared by every stage

Put each part's sections in a function of P (`trunk_sections(P)`, `arm_sections(P, sx)` in the example) that
`blocks(P)`, `build_mesh(P)`, `seams(P)` and `bones(P)` all read. The rig then needs no build: a joint is a
section's centre, and a hand's bone ends come from `lpk.forms.hands.fist_points`, the points the mitten is
built round. Every literal in the example's section functions is that body's: a new body re-derives them from
its own measurements (the example names them as constants or shares of P). Sides: the left side (+X) is built
and the right one mirrored or built with `sx = -1`.

## Blocks: blocks(P)

A list of `(kind, part, colour, args)` that `lpk.stages.blocks.build` turns into `<NAME>_Blocks`; the kinds
and their args are in its docstring: `box`, `wedge`, `ellipsoid`, `tube`, `loft` (sections of
`lpk.core.sections.Section`), `profile` (keys of `lpk.core.sections.ProfileKey`). Each part takes the
primitive its shape reads as: a square head a box, a pointed muzzle a wedge, a limb a loft through its
sections.

## The build: build_mesh(P)

One `lpk.core.builder.Builder(PALETTE, vert_layers=(lpk.forms.joins.LAYER,))` for the body, one more per
colour source. Call the forms (the shared `lpk.forms` or the local `lpk_local.forms.<model>`: [where a new
form goes](forms/README.md#where-a-new-form-goes)) and kernels directly, part by part, in the order the joins
need (the trunk before the limbs welded out of it, the head before what is cast onto it), and after each part
call `lpk.core.edits.apply(b, P, part, P['edits'])`: it triangulates the part, replays the human's edits and
records the part for `capture_edits`. Mirror a finished part with `b.mirror_part('ear.L', 'ear.R')`.
`lpk.core.shapes.bvh_of(b, ['head'])` gives the surface later parts are cast onto, once the part is finished.
The runner finishes the builders into objects (`lpk.core.builder.finish`).

Return `(body, {source: builder})`; every key of `SOURCES` needs a builder. The same model gives the same
vertex order, UVs and weights: seed every random choice in the module and its local forms, and never
iterate geometry in set or dict-of-objects order.

## Hand edits

In the parametric mode the human may move vertices of the built body in Blender and never changes its
topology: no vertex, edge or face added, deleted, merged or reconnected. A build over a body whose
topology was edited raises; a topology edit belongs to the frozen mode: `freeze`, then `FROZEN = True`
([the frozen mode](frozen.md)), where `freeze` stores every edit and `capture_edits` is not used.

After vertex moves, run `capture_edits` before the next build: a build over moves not stored raises. It
diffs the scene's body against a fresh build and adds the offsets to `EDITS`.
Its report's `parts` counts the vertices this capture took, `stored` every stored offset per part: a part
edited earlier and not moved since reads 0 in `parts` and keeps its offsets. Read `untracked` too: moved
vertices no part keeps, lost on the next build.
The next build replays them right after making each part. A part whose topology no longer matches its
stored edits stops the build with an error naming it: the human re-captures after the change or drops
that part's entry. Read what the human moved: it says where the model's numbers are wrong, so change the
numbers and drop the edit when they do.
