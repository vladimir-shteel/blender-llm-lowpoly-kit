# A quadruped

An animal on four legs, its trunk level and its legs digitigrade (a dog, a cat, a wolf, a predator of that
build), rigged on the `quadruped` skeleton template (`SKELETON = 'quadruped'`). The worked example is
`examples/hound/hound.py`: read it before writing a model of this kind.

1. **Brief.** Read the brief and the references. Decide with the human: the triangle total, the atlas
   size, the skeleton's options (a tail and its bone count, a jaw that opens, toe bones or rigid paws:
   [weights](../weights.md#the-template-and-its-part-binding)), the read size, and whether the references
   may go to an image tool. They go into the module's docstring when it is written (step 3).
2. **Intake** ([intake](../intake.md)): the side view is the main view; calibrate it `rows` from the
   withers or the crown to the floor, or `known_span` over the body's length. The front or top view gives
   the widths. Read each leg's joints on the side view: the shoulder, the elbow, the wrist and the ball of
   the front paw; the hip, the stifle, the hock and the ball of the hind paw. The elbow and the stifle sit
   close under the trunk's outline; the wrist and the hock are the low joints a quadruped stands on above
   its paws. A model without references takes them from the brief
   ([without references](../intake.md#without-references)).
3. **The model file.** Write `props()`, the shared sections and `blocks(P)` first
   ([the model file](../model-file.md)).
4. **Blockout.** As for a biped: `run.model(MODEL, stages=('reference', 'blocks'))`. **Review:** the human
   compares the blocks with the drawings in Blender; `outline_diff` on the side view for proportions
   ([checking a step](../running.md#checking-a-step)): the trunk's length and depth, the legs' lengths,
   the head's place.
5. **Build part by part**, every part a separate shell ([style](../style.md#limbs-welded-or-separate-shells)):
   - the trunk as one loft along the body through its sections, every ring upright (a fixed `axis`), so
     the chest's depth and the loin's tuck-up are the sections' heights and centres, its rump closed on an
     apex over the tail and its front flat under the neck;
   - the neck as a loft from inside the chest into the skull;
   - the head from `head.snout_head` or `head.profile_head` ([head](../forms/head.md)), ears from
     `shapes.lobe`;
   - each leg as `limbs.limb` or a loft through its joints, its root buried in the trunk, rings either side
     of the elbow or stifle and the wrist or hock, its end buried in the paw;
   - the paws from `feet.mitt_paw` (a soft paw) or `feet.paw_toes` (separate clawed digits)
     ([feet](../forms/feet.md)), grounded;
   - the tail from `tails.straight_tail` ([tails](../forms/tails.md)).

   Build the left legs, paws and ears and copy them with `Builder.mirror_part`. After each part:
   `run.model(MODEL, stages=('build',))` and the outline against each calibrated view. **Review:** the
   human sees the part in Blender against its blocks and the references.
6. **Budget.** As for a biped ([style](../style.md)): four legs and four paws are most of a quadruped's
   count, so their side counts and rings decide it.
7. **New forms**, **freeze**, **texture**: as for a [biped](biped.md), steps 7 to 9.
8. **Rig.** `bones(P)` gives the spine along the trunk's upper third, the neck and head to the nose, each
   leg through its joints (the scapula from the withers to the shoulder joint), the toes from the ball to
   the tip, the tail's bones evenly along it. The trunk's binding takes the roots of the legs it hides;
   ears and gear take the head or the bone they ride through `ALLOWED` or `FIXED`. Run `rig`, then
   `run.poses(MODEL)`. **Review:** the poses: each leg bends at its joints without tearing its shell, the
   paws stay on their legs, the head and the tail turn.
9. **Export, only when the human asks** ([export](../export.md)): the generic profiles write the bones by
   the template's names. Every `reimport` must have an empty `diffs`. **Review:** the human checks the
   import in the target engine.

Limits: the template is digitigrade; a plantigrade animal (a bear) or a hoofed one is a question for the
human, as is any body plan no template covers ([weights](../weights.md#the-template-and-its-part-binding)).
