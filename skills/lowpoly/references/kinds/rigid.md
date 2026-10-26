# A rigid mechanism

An object of rigid pieces that move against each other: a turret, a drone, a walking machine, a weapon with
a slide and a magazine, a chest with a lid. Rigged on the `rigid` skeleton template (`SKELETON = 'rigid'`):
one `Root` bone at the pivot, every moving piece a bone of the model's own, every part pinned to the bone it
moves with. Nothing bends, so there are no joins to weld or smooth. The worked example is
`examples/turret/turret.py`: read it before writing a model of this kind.

1. **Brief.** Read the brief and the references. Decide with the human: the triangle total, the atlas
   size, the read size, the **pivot** (as for a [prop](prop.md)) and the **moving pieces**: which pieces
   move, about which axis they turn or along which line they slide, and how far. Each moving piece is one
   bone; pieces that move together share it. They go into the module's docstring when it is written
   (step 3).
2. **Intake** ([intake](../intake.md#objects)): as for a prop. A mechanism drawn in one position is
   modelled in it; a piece drawn moved (a lid open) is measured where the drawing has it and posed back.
3. **The model file.** Write `props()`, the shared profile or section functions and `blocks(P)` first
   ([the model file](../model-file.md#a-prop)), with the pivots of the moving pieces among the
   measurements.
4. **Blockout.** As for a prop: `run.model(MODEL, stages=('reference', 'blocks'))`. **Review:** the human
   compares the blocks with the drawings in Blender; `outline_diff` on `['<NAME>_Blocks']` for proportions
   ([checking a step](../running.md#checking-a-step)).
5. **Build part by part:** each moving piece in parts of its own, never sharing a part with a piece that
   moves otherwise, from the hard-surface forms ([gear](../forms/gear.md)). Where two pieces turn against
   each other, a hub or a drum on the axis hides the gap the turn opens ([gear](../forms/gear.md#rigid-pieces)).
   A sliding piece overlaps what it slides in by its stroke, so the pose opens no hole. After each part:
   `run.model(MODEL, stages=('build',))` and the outline against each calibrated view. **Review:** the
   human sees the part in Blender against its blocks and the references.
6. **Budget.** As for a prop ([style](../style.md)), before the texture.
7. **New forms.** As for a prop: a local form of this model ([where a new form goes](../forms/README.md#where-a-new-form-goes)).
8. **Freeze when detail needs it** ([the frozen mode](../frozen.md)).
9. **Texture.** As for a prop ([atlas](../atlas.md)). **Review:** the atlas on the model in Blender's texture
   shading.
10. **Rig.** `bones(P)` gives `Root` from the pivot; `extra_bones(P)` gives each moving piece's bone, its
    head on the piece's pivot, its parent the piece it rides on, and a `roll` wherever the bone points along
    the default roll direction ([weights](../weights.md#joints-bonesp)). A bone that turns about one axis
    lies along it or across it so the turn is one Euler angle; a bone that slides lies along its stroke so
    the slide is one offset. `FIXED` pins every part to one bone, `'{s}'` expanding paired pieces;
    `WEIGHTS = 'distance'` keeps those weights alone. `POSES` holds one review pose per moving piece at the
    end of its travel, a turn as `(x, y, z)` degrees or a slide as `{'loc': (x, y, z)}` metres along the
    bone's own axes (`lpk.stages.pose.channels`); `TEST_POSE` all of them together. Run `rig`, then
    `run.poses(MODEL)`. **Review:** the poses: every piece moves about its pivot, nothing opens a gap or
    passes through a piece it should not.
11. **Export, only when the human asks.** As for a prop, with the rig: the generic profiles write the
    bones by the model's names ([export](../export.md)); a humanoid profile has no use for this skeleton.
    Every `reimport` must have an empty `diffs`. **Review:** the human checks the import in the target
    engine: the pivot, the facing, and each bone turning its piece.

Limits: the export is one mesh and one armature, so a piece that leaves the body (a dropped magazine, a
broken-off part) stays skinned to its bone; a piece the game spawns apart is a prop of its own.
