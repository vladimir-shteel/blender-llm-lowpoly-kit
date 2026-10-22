# The atlas

One colour atlas per model: one image, one material, one UV map. Each face carries its palette colour; the
colour sources are baked over it in bake order; no light is baked in. The stages are `unwrap`, `pack`
(repeated until the face island settles), `bake` and `preview` ([running](running.md)); what they read
from the model module is in [the model file](model-file.md). The docstrings of
`lpk.stages.texture.unwrap`, `pack_step` and `bake` state every parameter and limit.

```python
ATLAS = (512, {'Body': 1.0, 'Outfit': 1.0})    # size in pixels, {group: relative texel density}

def sheet_of(colour, part):                     # the group of a face
    return 'Body' if colour in ('skin', 'hair') else 'Outfit'
```

Everything below is the procedural texture. Under a frozen texture (`TEXTURE_FROZEN = True`) `unwrap` and
`pack` refuse and the bake adds only the `'over'` sources: [the frozen texture](frozen.md#frozen-texture).

Colour sources overlap the body until the bake, so a painted layer (a mask, a belly patch, tail rings)
looks ragged in a capture before it: judge painted layers on the baked atlas (`shade='tex'`).

## Groups and texel density

- **Densities are relative.** Each group is scaled to its density before the pack; the pack then scales
  everything into the square. Whether a group gets the texels it needs is read off the bake, not assumed:
  `report['bake']['report'][group]['texels_per_m']`, the groups `Face` (the face island) and `Strip`
  included. Compare two layouts by these numbers side by side, never by how tidy the UV layout looks.
- **Density follows the finest detail a group carries.** A group with fine painted detail (chest lines, a
  face without its own island) needs a density that keeps that detail whole; a group of flat colour can
  run lower. A group's lines break into texel steps below what they need, however sharp a denser
  neighbour reads.
- **A figure far above human size in one atlas:** let large flat areas run at a low density and spend on
  the head and on small gear (a denser group).
- **Route detail to the denser group.** A line takes the density of the group its faces belong to. A part
  coloured like the body that carries a thin painted line (a cord, piping, a strap) goes to the denser
  group in `sheet_of`: test the part before the colour.
- **Boosts cost every other island.** `BOOST = {part: factor}` is a linear UV scale on top of the group's
  density, so the part gets the factor squared in texels; the face island takes none. The pack shares one
  square, so every other island loses texels: read the group's `texels_per_m` before and after.
- The first group of `ATLAS` is the one whose density the face island and the strips take.

## Count texels before painting a line

A line narrower than `lpk.stages.texture.MIN_LINE_TEXELS` texels is missed by some texel centres and bakes
as dashes (the constant's comment gives the reason). Compare a line's width with its part's density (its
group's texels per metre times its boost) before painting it; when it falls short, boost the part, widen
the line or route the part to a denser group. A stripe that tapers over its whole length leaves its thin
end too thin. After the bake, `report['bake']['report']['texels']` lists every line the line and strip
tools recorded, fewest texels first, with the points under the minimum (`under`), and the eyes an eye
form or a decal with `mark='eye'` drew (`lpk.stages.texture.texel_readings`).

- Lines that stand for gaps (between a mitten's fingers) take the darkest palette colour: dark lines read
  as gaps, mid-grey ones as the stripes of a glove. The palette stays the human's.
- Stairs on a diagonal line, and a hem drawn ragged in the reference, are look questions: ask the human
  how they should read at the read size. Boost the part when a line must be clean; at a low density the
  small steps of a ragged edge can bake as loose shapes apart from the hem.

## The face island

When eyes, mouth or markings are painted into the atlas, the front of the head becomes the face island:
unwrapped conformal with seams on its border, scaled to its own budget before each pack.

```python
FACE_PART = 'head'
FACE_TEXELS = 400            # texels per metre the face's finest painted feature needs

def face_pred(P):            # (centre, normal) -> bool over FACE_PART's faces, object space, front is -Y
    (cx, cy, cz), (W, D, H) = P['head_c'], P['head_half']
    facing, across, below, above = FACE_BOUNDS      # the model's shares of the head, read off the drawing
    return lambda c, n: n[1] < -facing and abs(c[0]) < W * across and cz - H * below < c[2] < cz + H * above
```

- **State the budget in texels.** `FACE_TEXELS` fixes the density; `FACE_AREA` (a share of the atlas)
  fixes the area instead, so the same share gives a larger face fewer texels per metre, and a share copied
  from another model fits only that model's face (`lpk.stages.texture.face_area_for` converts). Derive the
  density from the narrowest painted feature and `MIN_LINE_TEXELS`; correct it after a bake from the
  `Face` group's `texels_per_m` and the close-up.
- **Where the island ends.** Its border is a seam: a feature cut by it bakes in two islands at different
  densities and shows a colour step. Put the border under the chin, behind the face's colour edge or at
  the hairline, with every eye, the mouth and the markings well inside; take its bounds from `P`. A
  selection of regions that share no edge (each side of a long head) becomes one conformal piece per
  region, all scaled alike.
- **Orientation.** The unwrap reports `face_angle`, how far the island's up direction turns off the texel
  columns (degrees, -45 to 45); the pack turns islands by quarter turns only, so the angle stays. A
  turned island stairs the eyes and the mouth.
- **Baked face or decals.** A baked eye of a few texels is a smudge; decal geometry
  (`lpk.forms.head.face_decals`, `lpk.core.shapes.fan_decal`) is crisp at any density. Bake what the face
  island gives enough texels; build a feature that would get only a few pixels in the mesh. With a face
  island of its own budget a baked face is fine; without one it is not.

## How packs settle

Blender's packer has no per-island area weight, a pinned island does not keep the others off it (they are
packed over it), and the `AABB` shape method squeezes islands. So the face island is scaled toward its
budget and the whole atlas packed normally, again, until the island's size stops moving:

- Each `pack` is one `lpk.stages.texture.pack_step`. Its report gives `face_area_before`, `face_area`,
  `face_span` (texels) and `face_side_change`; `lpk.stages.texture.pack_settled` is true once the side
  moves by less than `lpk.stages.texture.SETTLED_TEXELS` texels, or when there is no face island (one pack is
  final). The runner stops the listed packs at the first settled one and marks it `settled`.
- The first pack after an unwrap in the same call reads the island as the unwrap left it and does not
  rescale; after a call that only unwraps, pass `rescale=False` to the first pack call
  ([running](running.md#splitting-calls)). A pack that does not rescale never settles, unless the model
  has no face island: then the first pack is final and settled.
- A face budget that does not fit beside the other islands keeps moving: lower `FACE_TEXELS`, raise the
  atlas size, or move texels from another group.
- `out/<NAME>.pack.json` caches packs keyed on the starting UVs and the settings; on a hit the pack
  restores the cached UVs (`cached` in the report). Deleting it changes only the time.

## Gaps and margins

Every island pays the pack margin along its whole border, so the gaps' share of the atlas grows with the
islands' count and border length. A smart-projected clothed body (many small islands) can spend a large
share on gaps. The bake reports `islands`, `by_part` (the parts with the most islands first),
`margin_share` and the coverage per group and in total (`coverage_total`): read them before and after a
change. Fewer, larger islands (the seamed unwrap) give that share back to the surface. The margin and the
packer's shape and margin methods (`lpk.stages.texture.PACK_SHAPES`, `PACK_MARGINS`) are parameters of
`pack_step`; the runner packs with their defaults, which keep the gap a fixed number of texels.

## Smart or seamed unwrap

Without `seams(P)` every group is smart-projected on its own: no seam data, enough for a first atlas. Its
islands lie at any angle in many small pieces, so lines baked across them stair and the gaps eat the atlas.

`seams(P)` returns any of `cuts`, `panels` and `hard` and selects the seamed unwrap: islands cut along part,
group and flat-colour borders, projected where a projection fits, flattened elsewhere, and every island but
the face island and the strips turned to the texel grid. Use it for the final atlas of a clothed or marked
character, and always when colour boundaries are cut into the mesh: those stay crisp in the atlas only
where they are island borders.

```python
def seams(P):
    cuts = {}
    for side, sx in SIDES:
        _, out = arm_axes(arm_point(P, 'shoulder', sx), arm_point(P, 'wrist', sx))
        cuts.update({'arm.' + side: [tuple(-c for c in out)],     # an arm's underside
                     'leg.' + side: [(-sx, 0.0, 0.0)],             # a leg's inner side
                     'hand.' + side: [(0.0, 1.0, 0.0)], 'foot.' + side: [(0.0, 0.0, -1.0)]})
    return {'cuts': cuts, 'panels': {'trunk': BOX}}   # BOX: front, back, the sides, top and bottom
```

- **Flat-colour borders are seams.** An island border bakes as a clean polygon edge; a colour border
  inside an island bakes as texel stairs wherever it runs diagonally (an ear's rim, a fur patch). The
  seamed unwrap cuts there by itself; smart projection does not.
- **Project where a projection fits.** A region whose faces all turn less than the unwrap's angle limit
  from its mean normal is projected flat along it, up the body along V: verticals stay vertical and decals
  read as painted from the front. Flattening a curved panel instead spreads its distortion as turn and
  shear, which tilts painted shapes and zigzags lines.
- **Panels by normal** (`panels={part: [direction, ...]}`): split a torso, a pelvis or a neck like a
  garment pattern, each face to the direction its normal is nearest. Keep top and bottom among the
  directions, or the shoulders and the underside fall into the front panel, which then turns too far to
  project; a torso in one piece can fan under the flattening.
- **Tubes are cut once on the hidden side** (`cuts={part: [direction, ...]}`): an arm's underside, a leg's
  inner side, the palm or back of a hand, a shoe's sole. Derive each direction from the measurements
  that placed the limb, as above: a direction typed in does not follow the limb when the measurements
  move it. Each flattened island is turned so its rings lie on texel rows; at a diagonal every line along
  it bakes as fine teeth.
- **Rigid gear** (`hard={part: degrees}`): a seam on every edge whose faces meet at more than that angle.
- **Conical bands fan:** a band round a cone (a neck, a widening cuff) unrolls into an arc whose straight
  lines fan; give it projected panels instead.
- **Regions that fold** (an ear, a toe, a mitten open only at the wrist): the unwrap splits them by their
  normals into pieces that project, else cuts from the border to the farthest vertex, else
  smart-projects them. The unwrap report names each: `split`, `extra_cuts`, `fallback`,
  `fallback_tris`, beside `regions`, `projected` and `cut_open`.
- **Limit:** a painted line across a tube's cut (a strap across a paw) still steps at the cut; move the
  cut, or accept the step.

## Strips and own materials

- **Strips** (`STRIPS = {part: sides}`): a loft with colour bands along it (a ringed tail) unrolls into one
  straight strip; the pack turns islands by quarter turns only, so every band stays on its own texel
  rows and the band edges meet round the tail. The part must be one `Builder.loft` of that many sides and
  nothing else: its rings in vertex order, each a closed loop, a single cap apex last joined to the last
  ring only. Anything else raises before the UVs change; a flat-capped banded part takes the seamed
  unwrap instead.
- **Own materials** (`OWN = {part: material name}`): a part textured apart from the atlas (an eye plane
  with its own shader). Its UVs fill the whole square, its faces take that material on a slot after the
  atlas's, and the bake makes a flat placeholder unless the scene already holds a material of that name
  (`report['bake']['report']['own']` says which). It is no strip and not the face island's part.

## Colour sources and the bake

`build_mesh(P)` returns the body and `{source: builder}`; `SOURCES = {source: {'mask': parts}}` lists them in
bake order, later covering earlier. The bake writes the palette into `Col` on the body and every source,
bakes the flat colours, then each source in a pass of its own, then a copy pass so the margin extends the
final colours (a helper of your own needs that pass too, or island borders show as seams under
nearest-texel sampling). The atlas is saved as `out/<NAME>_Atlas.png`.

- **Where they live.** `build` puts the sources in the collection `<NAME>_Sources` under `<NAME>`,
  excluded from the view layer: they are in the `.blend` but not shown, selected or exported (the export
  writes the body and the rig only). The bake includes the collection for its call. To look at a source,
  include the collection in the outliner; the next `build` excludes it again.
- **In the frozen mode** the sources follow the frozen body: `build` carries each from the parametric body
  onto it, keeping its lift (`report['build']['conform']`, [the frozen mode](frozen.md#colour-sources-on-the-frozen-body)).
  `'conform': False` in a source's entry keeps it where `build_mesh` put it.

- **Mask, lift and order every source** as [markings](forms/markings-decals.md#lift-reach-and-layering)
  says: the bake paints a source onto every face within its reach, and faces outside a mask bake into a
  throwaway image.
- **Reach.** A source bakes where its surface lies between `lpk.stages.texture.BAKE_CAGE` above the body
  and `BAKE_RAY` minus that below it; a source entry may set its own `'cage'` and `'ray'` in metres. A
  source further off bakes holes. `report['bake']['report']['reach']`, keyed by the source's object name
  `'<NAME>_<source>'`, gives each source's `highest`, `lowest`, `beyond` and `deep` vertices
  (`lpk.stages.texture.source_reach`).
- **Lines on a part's own surface** are cast onto a scratch copy of the part
  (`lpk.forms.hands.mitten_finger_lines` does this for a mitten), so they follow its real facets.
- **Final material** (`MATERIAL`, a name of `lpk.stages.texture.MATERIALS`): `'base'` links the atlas to
  the Base Color only; `'emission'` also emits it, so renders show the atlas unlit like an unlit runtime
  shader. Neither has a right value: it is part of the look.
- **Grit** (`GRIT`, an optional model attribute: None, the default, for flat colours, or an `(r, g, b[, a])`
  colour, `lpk.stages.texture.GRIT` being one) multiplies an object-space noise of that colour into the
  albedo, shared by a source and the body under it. Large areas of one colour under grit read blotchy:
  show them to the human before keeping it.

## The preview

`preview` saves the atlas as `out/<NAME>_Atlas_preview.png` and shows it on the body in the `PREVIEW` look,
a name of `lpk.stages.preview.PRESETS`: `'neutral'` (grey to white, no tint, no steps, the default) or
`'toon'` (a hard three-tone cel ramp). It imitates a runtime shader with one key light, shown through the
body's object-level slot link; the mesh keeps the bake's final material, which the export exports. The
preview approves nothing and measures nothing. Settle the look with the human (the preview look, the final
material, any grit) from what the concept shows of shading and from the target engine, on captures of the
preview (`run.capture(MODEL, tag='look', shade='material')`, which shows the preview's material), never on
the build's vertex-colour captures; check the atlas itself, unshaded, with `shade='tex'`. A grey preview in
the viewport comes from the scene's view transform, not from the atlas.

## Your own unwrap or bake helper

The Blender behaviour the unwrap, the pack and the bake work round is in
[pitfalls](pitfalls.md#your-own-bpy-and-bmesh-code).
