# The frozen mode

A model builds in one of two modes. The module's `FROZEN` chooses it; `lpk.run` says so in every build
report (`report['build']['frozen']`).

| Mode | The body comes from | The human may | Hand edits are kept by |
|---|---|---|---|
| parametric (`FROZEN` absent or False) | `build_mesh(P)`, every build | move vertices, never change the topology | `capture_edits` into `EDITS`, replayed by every build |
| frozen (`FROZEN = True`) | the frozen mesh `<NAME>_Frozen` in the open `.blend` | change anything: add, delete, subdivide, extrude, dissolve | `freeze`, which stores the body as the new frozen mesh |

`build_mesh` keeps making the colour sources in the frozen mode, and `build` carries them onto the frozen
body ([colour sources on the frozen body](#colour-sources-on-the-frozen-body)); every stage after `build`
reads the body as it stands and works the same in both modes.

The texture has two modes of its own, procedural and frozen, independent of the mesh's except that a
frozen texture needs the frozen mesh ([frozen texture](#frozen-texture)).

## When to switch

Stay parametric while the shape is still found from the references: a change of numbers in the module
rebuilds every part, the overlay and the measurements read the build, and a moved vertex says which number
is wrong. Switch when the detail needs edits the forms cannot make (a fold, a cut-in pocket, a reshaped
ear), when the human wants to sculpt by hand from here on, or when the model exists already (adopt).

The rule: in the parametric mode the human never changes the topology. Vertex moves only, stored by
`capture_edits` before the next build. A topology edit is done after `freeze`, or freezes the edit first.

## The build stamp

`build`, `freeze` and `capture_edits` stamp the body with its topology and positions. A build that finds
the body changed since raises and names the stage that keeps the change:

- topology edited, parametric mode: run `freeze` and set `FROZEN = True`;
- topology edited or vertices moved, frozen mode: run `freeze`;
- vertices moved, parametric mode: run `capture_edits`;
- a body the kit did not write: rename it, or rebuild over it.

`run.model(MODEL, stages=('build',), discard_edits=True)` rebuilds over the change and drops it: only when
the human says to.

## Freezing

```python
report = run.model(MODEL, stages=('freeze',))['freeze']
result = {k: report[k] for k in ('reference', 'topology_changed', 'far', 'changed', 'join_loop', 'next')
          if k in report}                              # 'next' only while FROZEN is unset
```

`freeze` triangulates the body, keeps or transfers its zones (the part of each vertex, the colour of each
face, the joins' hole loops), writes `<NAME>_Frozen` and stamps the body. It does not edit the module:
until `FROZEN = True` is set there, `build` stays parametric and rebuilds the body from `build_mesh`
(the frozen mesh keeps the edit). After setting it, `build` and every stage after it run again.

Read the report:

- `reference`: `body` (the topology was the kit's: the zones are kept as they are), `frozen` (taken from
  the frozen mesh the edit started from) or `parametric` (first freeze of an edited body: taken from a
  fresh build).
- `far`: per part, the vertices farther than `lpk.stages.zones.FAR_TOLERANCE` from the reference
  surface: what the edit added off the surface (an extrusion, new detail). Their part is the nearest
  surface's guess: check each part listed.
- `changed`: per part and per colour, what the transfer changed against the layers Blender left; Blender
  interpolates those through topology operators, so a change here is usually a repair.
- `join_loop`: tagged hole-loop vertices of the reference and of the body; fewer on the body means the
  edit moved or removed loop vertices, and the rig's join smoothing reads fewer.

## Adopting an existing model

Set `ADOPT = '<mesh object in the scene>'` and `FROZEN = True`, then
`run.model(MODEL, stages=('adopt', 'build'))`. `adopt` copies the object (its transform applied) into
`<NAME>_Frozen`. Parts come from vertex groups named like the model's parts, else from materials named so,
else from the nearest block of `blocks(P)`; colours from a flat material colour, else from the model's
texture under the centre of each face's UVs, else from the colour attribute, nearest to `PALETTE`, else the
first palette colour. Its report says how many vertices and faces each source decided (`pal`: `material`,
`texture`, `colour`, `first`). An adopted mesh has no hole loops: `JOINS` smoothing finds none.

A model with its own texture (a UV map and one image on its materials' Base Color) keeps it: `adopt`
stores the UV map and the image as the frozen texture (`report['adopt']['texture']`; None when there is
none, or when the materials show several images). Set `TEXTURE_FROZEN = True` with `FROZEN = True`
before the build, so the stages keep the texture ([frozen texture](#frozen-texture)); the report's
`texture_next` says so while it is unset.

## Fixing a zone

The human selects in Edit Mode; the agent calls the runner with the model path:

```python
run.select(MODEL, 'arm.L')                 # selects the part for the human to see or edit
run.assign(MODEL, 'hand.L')                # the selected faces' vertices become hand.L
run.assign(MODEL, 'hand.L', selection='verts')
run.paint(MODEL, 'shirt')                  # the selected faces take the PALETTE colour shirt
```

Each call leaves Edit Mode itself and returns to it. In the frozen mode run `freeze` afterwards to store
the change; a parametric build replaces it.

## Operations on a part

A whole part changes with a few numbers instead of vertex edits. Each call works on the scene's body,
then stores it as the frozen mesh with the zones the operation wrote, and stamps it: one call is one
stored change, no `freeze` needed after it. The frozen mode only: in the parametric mode each call raises
and the module's numbers are the way to change a part. A body whose topology was edited by hand since the
kit wrote it is refused until `freeze` stores that edit; vertices moved by hand are stored with the
operation. After the operations run `build` and the stages
after it again: the rig, the UVs and the atlas belong to the body before.

```python
run.transform(MODEL, 'arm.L', rotate=(0, 8, 0), pivot=(0.16, 0.0, 1.2), falloff=3)
run.transform(MODEL, 'hand.L', translate=(0.0, 0.0, -0.01), scale=1.1, pivot='base')
run.replace(MODEL, 'head')                   # the module's recipe for the part, built afresh
run.decimate(MODEL, 'hair', 0.5)             # keep about half of the part's faces
run.subdivide(MODEL, 'foot.L', cuts=2)
run.smooth(MODEL, 'trunk', iterations=2, factor=0.3)
```

- `transform`: move (m), turn (degrees, X then Y then Z) and scale a part about its `'centre'`, its
  `'base'` (the lowest point under its centre) or a point. The other parts' vertices within `falloff`
  edge rings follow less and less, so a welded seam stays closed and those rings stretch to take up the
  move; a separate shell (a hand, an ear, a shoe) moves alone. `falloff=0` moves the part only and
  stretches the faces across its seam. Report: `neighbours_moved` per part.
- `replace`: a part whose numbers changed in the module after the freeze returns to the recipe: the part
  of a fresh parametric build takes its place. Only a separate shell (no vertex shared with another part:
  a head, a hand, an ear, the hair, a shoe); a welded part raises naming the parts it is welded to. The
  new part has no hole loops. Report: `part_vertices`, `part_faces`, and how far the new part lies from
  the old one.
- `decimate`: fewer faces on a dense part; flat places go first and no vertex moves. Report:
  `part_faces`, `target_faces` (fewer can stay when no collapse is left that keeps the surface sound) and
  `removed_max_cm`, the shape lost.
- `subdivide`: more faces where a part needs detail; the shape does not change, so move or smooth after.
- `smooth`: round a part; a rounded part shrinks a little toward its border with each step.

Pinned, in `decimate`, `subdivide` and `smooth`: the part's vertices on its border with another part and on
an open rim neither move nor go, and the faces beyond the border keep their topology, so the seams stay
closed; `pinned` in the report counts them. Every report holds `vertices` and `faces` (the body's, before
and after), `max_displacement_cm` (the farthest a kept vertex moved) and `freeze` (the store's report).

## Colour sources on the frozen body

The sources are built on the parametric body (`build_mesh(P)`), so in the frozen mode `build` carries
each one onto the frozen body (`lpk.stages.zones.conform_sources`): every vertex keeps its offset over the
nearest point of the parametric body within the source's mask and moves to the matching point of the same
part on the frozen body, so a face or a trouser line follows a head or a trunk reshaped by an operation or
by hand. A part the frozen body has unchanged leaves its sources exactly where they were.

```python
report = run.model(MODEL, stages=('build',))['build']['conform']   # {source: report}, None when it opts out
```

Per source: `moved` and `max_shift_cm` (how far it followed), `offset_cm` (its lift over the parametric
body), `outside_reach` (vertices whose lift already lies outside the bake's reach: they bake nowhere),
`unmasked` (vertices over a part outside the mask, which the bake leaves out) and `unmatched` (vertices
whose part the frozen body lacks, left where they were: after a part renamed by `assign`). The match is the
nearest surface: a part moved further than about its own thickness, or turned far, maps the source to the
wrong side of it; read the bake's `reach` and the atlas after a large change.

`'conform': False` in a `SOURCES` entry keeps that source where `build_mesh` put it: for a source placed
in space on purpose, not on the body. The bake's `reach` then shows where the body left it.

## Frozen texture

The UVs and the atlas are made again by `unwrap`, `pack` and `bake` on every run: the procedural texture.
The frozen texture keeps them instead, so the human can paint the atlas in Blender (Texture Paint) or move
UVs by hand and the kit never undoes it. Ask the human before freezing it, and freeze it only when they
want to paint by hand or the model came with its own texture: after freezing, the model's colours,
sources and atlas settings no longer reach the texture except through the additions below.

```python
run.model(MODEL, stages=('bake', 'freeze_texture'))          # FROZEN = True: stores the UVs and the atlas
report = run.model(MODEL, stages=('freeze_texture',))['freeze_texture']
result = {k: report[k] for k in ('image', 'size', 'packed', 'uv_layer', 'islands', 'texture_next')
          if k in report}                              # 'texture_next' only while TEXTURE_FROZEN is unset
```

`freeze_texture` (frozen mesh only) writes the body's UV layer onto `<NAME>_Frozen` and a copy of the atlas
`<NAME>_Atlas` as `<NAME>_AtlasFrozen`, packed into the `.blend`, both as they stand: what the human painted
or moved is what is stored. Save the `.blend` to keep it. Like `freeze` it does not change the module:
set `TEXTURE_FROZEN = True` (with `FROZEN = True`), then `build`. Run `freeze_texture` again after each
round of hand painting or UV editing.

With `TEXTURE_FROZEN = True`:

- `build` brings the stored UVs back with the frozen mesh.
- `unwrap` and `pack` refuse: they would replace the frozen UVs.
- `bake` starts from `<NAME>_AtlasFrozen` and bakes only the colour sources whose `SOURCES` entry sets
  `'over': True`, each where its rays hit and in the bake margin round them outside the islands; every
  other texel keeps the frozen atlas exactly, the base colours and the earlier sources included. The
  result is `<NAME>_Atlas`, which `preview` and `export` use as before.
  `report['bake']['report']['sources']` gives per added source the texels it `hit`, the `margin` texels
  and the texels it `changed`; `reach` reads as in the procedural bake.
- The build stamp guards the hand work: a `build` over UVs edited since the last `freeze_texture`, and a
  `bake` over an atlas painted since, raise; run `freeze_texture` to keep the edit, or pass
  `discard_edits=True` when the human says to drop it.
- `freeze` and the zone operations store the body's UVs with the mesh as Blender's operators left them
  ([mesh edits under a frozen texture](#mesh-edits-under-a-frozen-texture)). While a frozen texture is
  stored and `TEXTURE_FROZEN` is unset, they refuse.

**Adding on top.** A new painted layer (a belt, a scar, a badge) is a colour source like any other, built
in `build_mesh` with an entry `{'mask': parts, 'over': True}` in `SOURCES`. Each bake composites it over
the frozen atlas again, so a repeated bake gives the same atlas; where it reaches, it covers what the human
painted there. Once the human is happy with it, `freeze_texture` stores it in the frozen atlas; drop its
`'over'` then, or a later hand paint over it is covered again at the next bake.

**Unfreezing** is the human's call and loses their hand work: `run.model(MODEL,
stages=('unfreeze_texture',))` removes `<NAME>_AtlasFrozen` and the stored UV layer, and its report's
`lost` says what is gone. Tell the human before running it. Then set `TEXTURE_FROZEN = False` (the report's
`texture_next`) and run `build`, `unwrap`, the packs and `bake` again.

## Mesh edits under a frozen texture

Topology edits stay allowed with a frozen texture. Blender keeps or interpolates the UVs through most
operators (subdivide, knife, loop cut, dissolve, delete, merge), and `freeze` and the zone operations store
them with the mesh as the operators left them. What an edit makes without usable UVs (the sides of an
extrusion, a filled hole, a face dragged in the UV editor) needs new ones; the UV check finds it.

```python
report = run.check_uvs(MODEL)
result = {'broken': report['broken'], 'parts': {p: {k: e[k] for k in ('zero', 'outside', 'overlap', 'density')}
                                                for p, e in report['parts'].items()}}
```

Run it right after `freeze_texture`, before the human edits, and again after the edit: what the first run
lists comes from the unwrap itself (a tight fold squashes faces inside an island), not from the edit. The
reports of `freeze`, the zone operations and the frozen-texture `build` and `bake` carry the same check as
`uv_check`; it reads the body as it stands, so it also runs on a hand edit before `freeze`.

Per part it lists face ids of the body and why:

- `zero`: no UV area; the face shows a single texel, or a line of them. Extrusions and fills leave these.
- `outside`: a corner off the atlas; the face reads the atlas again from its other side.
- `overlap`: the face lies on an island of another part and shows that part's colours. Of two overlapping
  islands the smaller is listed, both when they are of one size: islands of `.L` and `.R` laid on each
  other by hand list both; ask the human whether that was meant.
- `density`: its texels per metre far from the rest of its island (`ratio`): stretched or squashed.

The limits are constants of `lpk.stages.zones` (`ZERO_UV_TEXELS`, `OVERLAP_TEXELS`, `DENSITY_RATIO`), and
the check decides nothing: tell the human which parts it lists, and ask whether to repair them.

**Repairing**, on the human's request:

```python
report = run.repair_uvs(MODEL, parts=['trunk', 'leg.R'])     # parts=None: every part the check lists
result = {k: report[k] for k in ('placed', 'faces', 'texels_per_m', 'changed', 'next') if k in report}
```

`repair_uvs` takes only the faces the check lists (of `parts`, when given), unwraps them flat as new
islands at their part's texel density and places them in free atlas space: no existing island moves, and
no texel outside the new islands' cells changes. It bakes those faces only, their palette colour and every
colour source whose mask covers them, into `<NAME>_AtlasFrozen` and `<NAME>_Atlas`, then stores the UVs
and the atlas as `freeze_texture` does, so no `freeze_texture` is needed after it; `report['after']` is
the check on the new UVs. A repaired face is an island of its own: hand painting that crossed it does not
continue into it. The human paints it again in Texture Paint where it shows, then `freeze_texture`.

It runs after `build` (it bakes from the colour sources the build makes) and refuses a body whose mesh
changed since the kit wrote it (run `freeze` first) and an atlas painted since its last store (run
`freeze_texture` first).

**No room.** When the free atlas space cannot hold every new island, `placed` is False, nothing changes,
and `next` names the way out: `unfreeze_texture`, which loses the hand painting. Tell the human, and run it
only on their word.

## Reviewing by part

Read numbers per part instead of vertex lists:

```python
result = run.zones(MODEL, reference='frozen')     # or 'parametric', or None
```

For each part: faces, triangles, vertices, centre and size, neighbouring parts with their shared edges,
the mirror twin and how far off mirror it stands, uncoloured faces, and the deviation from the reference's
same part. `reference='parametric'` shows how far the frozen body has moved from what the module builds.
The human sees one part alone in Blender with `run.select` and local view;
`run.capture(MODEL, tag='edit', part='head')` captures it when the human is not at Blender (it needs
Blender's user interface, as every capture does).

## What stops working after freezing

- `capture_edits` raises in the frozen mode; `freeze` stores every edit.
- The module's body numbers no longer reach the body: changing a section, a form parameter or `props()`
  changes the colour sources, the bones and the blocks, not the body. Re-freezing from a new parametric
  build means switching back to the parametric mode and dropping the hand edits.
- The colour sources are still built from the module's numbers and then carried onto the frozen body:
  their outlines (an eye's size, the trouser line's height) come from the module, and a part added in the
  frozen mesh gets none; check the bake where the human edited.
- `STRIPS`, the seam directions of `seams(P)` and `face_pred(P)` were written for the built topology: an
  edited part may no longer be a strip or have the seam side the module names. Read the unwrap report and
  the atlas.
- Under a frozen texture `sheet_of`, `ATLAS`, `seams(P)`, `BOOST` and the face island no longer reach the
  atlas: only `'over'` sources do.
