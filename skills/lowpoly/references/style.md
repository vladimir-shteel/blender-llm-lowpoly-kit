# Style

A model's style lives in its module: named constants and form parameters, each with a one-line reason.
Each axis below says how to choose it and, as **Default**, what the forms assume. A departure from the
default, and any axis the concept leaves open, is put to the human.

## Shape in the mesh, colour in the texture

Where a colour change lives: painted into the atlas (the palette colours, the colour sources baked over
them), or cut into the mesh, whose faces carry their palette colour so the edge stays crisp at the cost of
triangles.

- **Default: shape in the mesh, colour in the texture.** The mesh carries what changes the silhouette; a
  colour change that does not is painted.
- **Per boundary:** a boundary the player must read sharply at the read size, which the atlas cannot hold
  crisp, goes into the geometry; the rest goes into the texture.
- **For the whole model** the brief may cut every boundary into the mesh: then the atlas holds only the
  faces' flat colours, with no colour sources and no face island, and eyes and face lines are in-mesh
  decals (`lpk.forms.head.face_decals`, `lpk.core.shapes.fan_decal`).
- **Relief:** under the texture stance a shape that stands off the surface by less than the read size
  shows is painted; under the geometry stance it is cut into the mesh or dropped, and dropping it is the
  human's call.
- The output always carries a baked atlas; boundaries cut into the mesh stay crisp in it only where they
  are island borders, which the seamed unwrap makes of flat-colour borders ([atlas](atlas.md)).

## Ends: apex or flat

How a tube closes at a finger, a tail tip, a horn or a limb's end: at an apex point or with a flat cap
(`cap0`, `cap1` of `Builder.loft`, `lpk.core.shapes.profile_loft`, `lpk.core.shapes.point_loft`).

- Choose from the concept's silhouette: an apex reads as a point, a flat cap as a cut. Where the apex sits
  past the last ring sets how pointed the end reads.
- Hard-surface gear belongs on this axis: flat caps, cut corners and flat facets read as made rather than
  grown beside an organic body.
- A form without a cap parameter closes as its code does; build a part that needs another end as a local
  form of the model ([where a new form goes](forms/README.md#where-a-new-form-goes)).
- A strip (`STRIPS`) unrolls only a loft whose cap apex comes last.
- **Default:** apex ends on organic parts, flat ends on gear.

## Density

How many facets the silhouette shows, and where.

- Give the silhouette the facets it shows at the brief's read size, no more, and enough that no curve
  breaks into visible steps at that size: judge it on captures scaled to that height beside the concept
  (`lpk.stages.review.play_size(NAME, read_px, out=...)`, one sheet with each part's relief in screen
  pixels, `relief`).
- Plan it against the triangle budget before the first part; replace a form whose fixed density the plan
  cannot carry rather than cut it down later. A bend needs rings where the joint bends; the poses say how
  many ([weights](weights.md)).
- `report['build']['body']['tris']` and `['by_part']` give the count after every build.
- **Default:** none; the forms' defaults are a starting point at their reference scale.

## Limbs: welded or separate shells

- **Welded:** the limb grows out of a hole in the trunk and shares its vertices
  (`lpk.forms.torso.trunk`, `lpk.forms.joins.armholes`, `leg_holes`, `weld_limb`, `weld_leg`). One surface,
  no hidden faces, the join reports (`run.joins`) and the smooth bake on the joins; it costs the welded
  trunk's fixed density and both sides of a pair welded alike.
- **Separate shells:** the limb is a closed or capped loft of its own (`lpk.forms.limbs.limb`,
  `profile_loft`, `point_loft`, a primitive or a local form) whose root ends inside the part it leaves. Any
  density, a limb unlike its pair; no join reads its root, so the roots are judged by eye at rest and in
  the poses, from below and behind, in Blender (`pose_test`).
- Choose from the density the plan needs and from the concept: a body whose density the welded trunk
  cannot carry, or whose paired limbs differ, takes shells.
- **Default:** welded.

## Hard surface

A prop, and gear on a character, is made, not grown: its faces read as cut and its edges as edges.

- **Ends:** flat caps (`cap0='flat'`, `cap1='flat'` of `Builder.loft`), coloured for what they show (end
  grain, a lid) by `col0` and `col1`.
- **Steps:** a band that stands off the surface (a hoop, a rim, a trim) is a step in one loft: two rings
  at one height, the radius changing between them, with the loft's `axis` fixed so the rings stay
  parallel: without it each ring turns to the path through its neighbours' centres, which two rings at
  one centre leave without a direction.
- **Colour borders** run along ring and column edges: each colour is a face colour, and its border an
  island border of the seamed unwrap, crisp at any atlas density ([atlas](atlas.md#smart-or-seamed-unwrap)).
- **Sides:** the fewest that keep the outline round at the read size; a turned prop shows its sides on its
  silhouette.
- **Default:** flat ends and colour borders in the mesh for a prop.

## Symmetry

Whether the model is mirror-symmetric, and which parts pair. Choose it from the concept: asymmetric hair,
gear, markings, a limb unlike its pair or a held pose make the sides differ. Make the one decision and pass
it everywhere it acts, since the forms and the rig do not assume the same by default:

- **Measurements:** average the two sides' landmarks for a symmetric model (the worked example's `pair`);
  read each side for an asymmetric one.
- **Build:** build one side of a pair and copy it with `Builder.mirror_part`, which gives exact mirror
  images (building each side separately is not exact for an odd-sided section); welded limbs are built per
  side over `SIDES`; a part that differs by design is built on its own side, never mirrored.
- **Forms with a symmetry option:** `lpk.forms.hair.hair_cap(symmetric=True)` mirrors its cast through
  x = 0, so a head whose triangulation differs between its sides still gets a mirrored cap.
- **Check:** `lpk.stages.checks.mirror_report(NAME)` reads which parts mirror from the vertex positions,
  never from the names: its `pairs`, `unpaired` and `parts`.
- **Weights:** the smooth bake mirrors the right side from the left; its `mirror_unmatched_parts` should
  list only the parts meant to differ ([weights](weights.md)).
- **Default:** none.

## Proportion and look

- **Proportion:** build honest to the drawing first. When a part reads off-size in 3D, propose a factor to
  the human and apply it in `props()` as a named constant with its reason (the worked example's
  `HEAD_STYLE`, about the head's centre). **Default:** none; every factor is the model's own.
- **The look:** the preview's shading (`PREVIEW`), the final material (`MATERIAL`) and the grit (`GRIT`,
  none by default; [atlas](atlas.md#colour-sources-and-the-bake)). Choose it from what the concept shows
  of shading and from the target engine; a drawing's rendering style is not always what the engine should
  show. **Default:** neutral ([atlas](atlas.md#the-preview)).
- **Presets:** the values stay in each model module. When this user's models of one style repeat a set of
  overrides for a shared form, you may propose it to the human as a named preset beside the form, always
  passed explicitly; adding it to the shared library is their decision, as for a form
  ([where a new form goes](forms/README.md#where-a-new-form-goes)).

## The optimisation pass

A triangle count over the budget is a mark for an optimisation pass after the full build, not an alarm
while building. Build every part at the density decided first, then cut only what is still over, in the
order of the model's colour stance:

1. **Under the texture stance:** colour-only geometry first, its colour moved into a colour source: rings
   and profile keys that carry a colour change but no shape (`lpk.forms.head.profile_key_deviation` shows
   how far each profile key sits off its neighbours' line; `lpk.core.shapes.polygon_rings` and
   `lift_rings` turn a loft's rings into a source just above the mesh). Under the geometry stance
   colour-only geometry is the style, not a cut.
2. Facets the silhouette does not show at the read size (`play_size`'s `relief` per part in screen
   pixels; `images=False` measures it without the sheet).
3. Rings no bend needs, and rings hidden inside a garment or gear.

Never cut silhouette, the rings a bend needs or detail the reference needs to meet the number. A cut that
changes how a part reads (a colour boundary merged or dropped, a facet the silhouette shows) is the
human's decision. Keep the captures from before and after the pass (`run.capture(MODEL, tag=...)` with two
tags); what is still over afterwards goes to the human with the parts it is in and what each further cut
would lose.
