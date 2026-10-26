# First-person arms

The arms a first-person camera shows, rigged on the whole `biped` skeleton at its `standard` rest
(`lpk.skeletons.rest('biped', 'standard', ...)`) with `full` hands: every character's arms share one
skeleton, so the target's first-person clips play on all of them alike, and each character's look lives in
the mesh's volume and colours, never in bone lengths. Only the arms are meshed; the trunk, the head and the
legs stay in the rig, unweighted, for the target's humanoid avatar. The worked example is
`examples/fp_arms/fp_arms.py`: read it before writing a model of this kind.

1. **Brief.** Read the character's third-person model or concept and the brief. Decide with the human: the
   triangle total, the atlas size, the camera (`EYE`: the eye's point on the standard rest and the
   viewport's focal length, as near the target's camera as the human can say) and the target's clips at
   hand. They go into the module's docstring when it is written (step 3).
2. **No intake.** The arms are not measured off a drawing: the skeleton is fixed, so every size is the
   mesh's own, chosen against what the camera shows. Take colours, the sleeve, the gear and the hand's
   character (claws, gloves, a prosthesis) from the third-person model.
3. **The model file.** `props()` returns the standard rest's joints; `bones(P)` returns them all;
   `SKELETON = 'biped'`, `EYE`, and `POSES` that raise the arms into view.
4. **Build part by part:**
   - each arm as one loft from the upper arm (below where the camera sees) through the elbow and the
     wrist into the palm, closed flat at the knuckle line, rings either side of the elbow and the wrist so
     they bend, the palm's rings wide and thin across the hand's breadth;
   - each digit as a loft from inside the palm through its three joints to an apex, two rings round its
     first joint, a part of its own named as the template's binding names it (`thumb.L`, `index.L`, ...);
   - gear on the forearm and the hand from the hard-surface forms ([gear](../forms/gear.md)), pinned to
     its bone in `FIXED`.

   Build the left arm and copy it with `Builder.mirror_part`; build gear that differs per side after the
   copy. After each part: `run.model(MODEL, stages=('build',))`. **Review:** the human sees the part in
   Blender; the captures from the eye (`run.capture(MODEL, views=('eye',))` with the arms posed by
   `pose_test`) show what the player sees.
5. **Budget, texture**: as for a [biped](biped.md), steps 6 to 9. Spend the triangles where the camera
   looks: the hands and the last part of the forearms; the elbows and the upper arms are rarely seen.
6. **Rig.** `ALLOWED` keeps each arm on its own bones, away from the chest and the clavicle above where
   it starts; the digits take the template's binding. Run `rig`, then `run.poses(MODEL, views=('eye',
   'q34'))`. **Review:** the hands close and open without tearing, the wrists turn, the cuffs stay over the
   forearms.
7. **The target's clips** ([a clip on the rig](../weights.md#a-clip-on-the-rig)): map the clip's spine,
   arms and every finger, pass `hips_scale=0.0` (a first-person clip holds its camera still and moves the
   body under it, which a travelling root would carry out of view) and capture with `views=('eye', 'q34',
   'side')`. **Review:** the hands meet the weapon's grip and magazine where the clip puts them, the
   fingers close round the grip, nothing passes through the camera.
8. **Export, only when the human asks** ([export](../export.md)), for the humanoid avatar with the
   whole skeleton. **Review:** the human checks the arms in the engine with its own clips.

Limits: the eye view stands at `EYE` on the rest pose and does not follow the head a clip turns; the sheet
is the clip sampled onto the rig, not the engine's retargeting.
