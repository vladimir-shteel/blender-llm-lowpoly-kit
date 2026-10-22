# A biped character

A character on two legs, rigged on the `biped` skeleton template (`SKELETON = 'biped'`). The worked example is
`examples/mannequin/mannequin.py`: read it before writing a model of this kind.

1. **Brief.** Read the brief and the references. Decide the tier with the human: the triangle total, the
   atlas size, the skeleton, the read size (how tall the character stands on screen at
   the farthest distance players must read it), and, when the environment offers an image tool, whether
   the references may be sent to it. They go into the module's docstring when it is written (step 3).
2. **Intake** ([intake](../intake.md)): choose the source before any cleaning, cut the views, calibrate each,
   sample the palette and read the landmarks, widths and depths into `views.json`. A character without
   references skips this step ([without references](../intake.md#without-references)).
3. **The model file.** Write `props()`, the shared sections and `blocks(P)` first
   ([the model file](../model-file.md)).
4. **Blockout.** `run.model(MODEL, stages=('reference', 'blocks'))`: every part as its primitive beside the
   references. **Review:** the human compares the blocks with the drawings in Blender (front, side,
   three-quarter; `run.capture(MODEL, tag='blocks', objects=['<NAME>_Blocks'])` for pictures); fix
   proportions in `props()` and the sections, not in the blocks. Without references, `stages=('blocks',)`
   and the human judges the blocks by eye; so too every later review compares with the human's idea.
5. **Build part by part:** head and face, hair, torso and clothing, legs and feet, arms and hands, tail,
   gear, each from its area's card ([forms](../forms/README.md)). After each part:
   `run.model(MODEL, stages=('build',))` and `run.capture(MODEL, tag=<part>)`.
   **Review:** the part against its blocks and the references. When a part's accuracy is in doubt, lay the
   build over the reference view (the overlay, [running](../running.md#review-calls)). Measure a shape off the
   reference; do not tune a preset made for another species or body. If the human corrects a part by hand,
   run `capture_edits` before the next build and read what they moved: vertex moves only, the topology
   stays (step 8 for more).
6. **Budget.** Once every part is built, count the triangles (`report['build']['body']['tris']`) against
   the tier. An overrun goes to the optimisation pass ([style](../style.md)) now, before the texture and the
   rig, which a cut makes again; never to cutting detail while building.
7. **New forms.** A form a part needed that the library lacked is written in the local package of this
   model, `lpk_local.forms.<model>`, or copied there from another model's package and changed as this
   model needs; similar forms in several packages are proposed to the human as one shared form. Never
   move one into the shared library `lpk/forms` on your own
   ([where a new form goes](../forms/README.md#where-a-new-form-goes)).
8. **Freeze when detail needs it.** When the human wants topology edits (a fold, a cut, a reshaped part)
   or the model exists already, switch to the frozen mode: `freeze` (or `adopt`), set `FROZEN = True`,
   build again ([the frozen mode](../frozen.md)). **Review:** the freeze report's `far` parts and the zone
   summary; fix a wrong zone with `run.assign` or `run.paint`; change a whole part with the
   [operations on a part](../frozen.md#operations-on-a-part). Stay parametric otherwise.
9. **Texture.** `unwrap`, the packs until settled, `bake`, `preview`, split over calls
   ([running](../running.md#splitting-calls); the settings in [atlas](../atlas.md)). **Review:** the atlas on the
   model (`run.capture(MODEL, tag='tex', shade='tex')`): the painted face, the seams, the colour boundaries.
   When the human wants to paint the atlas by hand, or the model came with its own texture, freeze the
   texture ([frozen texture](../frozen.md#frozen-texture)); from then on add painted layers only as `'over'`
   sources. After a mesh edit under the frozen texture, **review** the UV check's parts and repair on the
   human's word ([mesh edits under a frozen texture](../frozen.md#mesh-edits-under-a-frozen-texture)).
10. **Rig.** `rig`, then `run.poses(MODEL)` and `run.joins(MODEL)` ([weights](../weights.md)). **Review:** the
   poses: no tearing at the joins, limbs that bend where the joints are.
11. **Export, only when the human asks.** The character is finished with the rig's review; the export
    may come much later, for several models at once. When asked, settle the targets with the human,
    write `EXPORTS`, run `export` ([export](../export.md)); every `reimport` must have an empty `diffs`.
    **Review:** the human checks the import in the target engine.
