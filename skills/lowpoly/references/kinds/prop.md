# A prop

An object without a rig: a barrel, a crate, a lamp, a weapon held whole. Its module has no `SKELETON`, so
there is no rig, no pose and no join to review, and the export writes its body alone. A prop with moving
parts (a lid, a door) needs a rig and is not this kind. The worked example is `examples/barrel/barrel.py`:
read it before writing a model of this kind.

The human reviews at the points marked **Review**: show them what the step made, say what to look at, and
wait for their answer before the next step. A part goes through at most a few passes; if it still does
not read right, say what is off and ask how to go on.

1. **Brief.** Read the brief and the references. Decide with the human: the triangle total, the atlas
   size, the read size (how tall the prop stands on screen at the farthest distance
   players must read it) and the **pivot**, the point the engine places and turns the prop by: the centre
   of its base on the floor for a prop that stands, the grip for one that is held, the hook for one that
   hangs. The model is built round that point at the origin, its front facing -Y. They go into the
   module's docstring when it is written (step 3).
2. **Intake** ([intake](../intake.md#objects)): a round or turned prop reads from one view, a boxy one
   from a front and a side. Calibrate the main view from the prop's top and base rows and its known
   height, or from a known length; name the landmarks after the prop's own parts. A prop without
   references skips this step ([without references](../intake.md#without-references)).
3. **The model file.** Write `props()`, the shared profile or section functions and `blocks(P)` first
   ([the model file](../model-file.md#a-prop)).
4. **Blockout.** `run.model(MODEL, stages=('reference', 'blocks'))`: every part as its primitive beside the
   references. **Review:** the human compares the blocks with the drawings in Blender
   (`run.capture(MODEL, tag='blocks', objects=['<NAME>_Blocks'])` for pictures); fix proportions in
   `props()` and the shared functions, not in the blocks. Without references, `stages=('blocks',)` and the
   human judges the blocks by eye.
5. **Build part by part:** the prop's own parts, the main body first, then what sits on it (trims, bands,
   handles, fittings), each cast onto the surface it sits on ([gear](../forms/gear.md)). Hard surface takes
   flat caps and crisp colour borders ([style](../style.md#hard-surface)). A piece the prop repeats
   (plates, boards, rivets, studs) is one local form called once per copy from a list in P, each copy in
   a part of its own (`plate.1`, `plate.2`) or all in one part; a mirrored pair is built once and copied
   with `Builder.mirror_part`. After each part:
   `run.model(MODEL, stages=('build',))` and `run.capture(MODEL, tag=<part>)`. **Review:** the part
   against its blocks and the references. If the human corrects a part by hand, run `capture_edits` before
   the next build and read what they moved.
6. **Budget.** Once every part is built, count the triangles (`report['build']['body']['tris']`) against
   the brief. An overrun goes to the optimisation pass ([style](../style.md)) now, before the texture.
7. **New forms.** A piece the library lacks (a chamfered box, a hinge, a handle) is a form in the local
   package of this model, `lpk_local.forms.<model>`; never move one into `lpk/forms` on your own
   ([where a new form goes](../forms/README.md#where-a-new-form-goes)).
8. **Freeze when detail needs it.** Topology edits by hand, or a model that exists already, go to the
   frozen mode as for any model ([the frozen mode](../frozen.md)).
9. **Texture.** `unwrap`, `pack`, `bake`, `preview` ([atlas](../atlas.md)). Without a face island the first
   pack after the unwrap is final and reports `settled`; a prop takes a face island only for painted
   detail that needs one (a label, a sign). **Review:** the atlas on the model
   (`run.capture(MODEL, tag='tex', shade='tex')`): the seams and the colour borders.
10. **Export, only when the human asks.** The prop is finished with the texture's review; the export may
    come much later, for several models at once. When asked, settle the targets with the human, write
    `EXPORTS`, run `export` ([export](../export.md)); every `reimport` must have an empty `diffs`.
    **Review:** the human checks the import in the target engine: the pivot, the size, the facing and the
    material.

Limits: one model module holds one prop, so a set of props is a module each; the captures frame a model
no closer than `lpk.stages.review.MIN_HEIGHT`, so a very small prop reads small in them.

Throughout: one runner or review call per bridge call, a short report back, and the human's corrections
turned into numbers in the model file.
