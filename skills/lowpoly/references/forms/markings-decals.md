# Markings and decals

Under the texture stance, colour that does not change the silhouette goes into the atlas. It gets there two
ways:

- **Body face colours:** the palette colour of the body's own faces, set by a form's `color` function or by a
  model-module helper over a part's faces. Use it when the boundary runs along rings or faces the shape needs
  anyway.
- **Colour sources:** geometry lying just above the body, built into builders of their own that
  `build_mesh(P)` returns beside the body (`(b, {'Stripes': s, ...})`), baked onto the body and hidden. Each
  source has an entry in `SOURCES`, `{'Stripes': {'mask': ('head', 'trunk')}}`, in bake order: later sources
  cover earlier ones. A source costs no triangles in the exported mesh.

Under the geometry stance every boundary is body face colours: colour the faces, add rings where a boundary
needs them, or build decals into body parts (`shapes.fan_decal`, `head.face_decals`, `Builder.decal`) at the
cost of triangles; `SOURCES` stays empty. The tools below then build into the body builder.

## Choose the tool

| The mark | Tool |
|---|---|
| An eye, a light, a patch with an outline seen from one direction | `shapes.fan_decal` |
| A panel round the side of a torso, a pad over a shoulder, a stripe down a forearm | `shapes.axis_fill` |
| Piping, seams, a zip, drawstrings, a mouth line | `shapes.surface_strip` |
| A flat region of any outline that does not wrap round a side | `shapes.surface_fill` |
| A pocket, a label, a screen | `shapes.surface_patch` |
| A star | `shapes.surface_star` |
| Scars, scuffs, grime | `shapes.surface_blotches` (seeded) |
| A patch over a garment layer lying just over another | `shapes.ray_grid` |
| A band round a column, a cuff, a strap at one ring | `shapes.ring_band` |
| Equal bands along a loft (a ringed tail) | `shapes.band_source` ([tails.md](tails.md#coloured-bands)) |
| Tiger-like stripes across a head or a limb | `markings.wrapped_stripes` |
| Colours of loft rings or keys dropped from the mesh | the full-ring loft in a source, pushed off with `shapes.lift_rings` |

## Build it

```python
from lpk.core.builder import Builder
from lpk.core.shapes import axis_fill, bvh_of
from lpk.forms import markings


def build_marks(b, P):
    """SOURCES = {'Panels': {'mask': ('trunk',)}, 'Stripes': {'mask': ('head',)}}."""
    trunk, head = bvh_of(b, ['trunk']), bvh_of(b, ['head'])
    panels = Builder(PALETTE)
    outline = P['panel_outline']                                       # [(azimuth deg, s m)] off the views
    axis_fill(panels, 'panel.L', trunk, P['hip_c'], P['neck_c'], (0.0, -1.0, 0.0), outline, 'stripe')
    stripes = Builder(PALETTE)
    rows = P['stripe_rows']                                            # [(s m, reach deg, width m, lean m)]
    markings.wrapped_stripes(stripes, 'stripes', head, P['head_back'], P['nose_tip'], (0.0, 0.0, 1.0), rows,
                             'stripe')
    return {'Panels': panels, 'Stripes': stripes}
```

## Anchor by rays, not coordinates

Cast every anchor, guide and outline onto a surface of only the parts the mark belongs on
(`shapes.bvh_of(b, [...])`, which raises on a part name the builder does not have) and pass the hits. Choose
the direction by the surface you want to hit: a ray lands on the first surface in its way (laces cast from the
front meet a boot's toe cap; cast from above, the instep). Nearest-point snapping from a point in front lands
on whatever surface is nearest, which can lie to the side of the intended one.

## Lift, reach and layering

- Lift every source just off the body (each tool's `lift`). Within one source list overlapping shapes back to
  front and lift each later one higher: shapes stacked a fraction of a millimetre apart cut into each other
  (`surface_blotches` lifts each blotch above the last for that reason). Across sources the order of `SOURCES`
  decides: each bakes in a pass of its own, the later covering the earlier wherever its rays reach.
- The bake casts from a set height above the body over a set depth: a source surface further out is missed. A
  source that must lie further off gets a wider reach with `'cage'` and `'ray'` in its `SOURCES` entry, in
  metres (`lpk.stages.texture.source_specs` gives the defaults).
- Mask every source: the bake paints it onto every face within its reach, so without a `mask` a source near a
  plate, a bracer or an ear paints spots onto them too. Keep in-mesh decals and plates out of every mask.

## The tools' behaviour

- **`fan_decal`** casts each outline point along `direction` and fans the polygon through `rings` rings, so it
  follows the curvature where a single n-gon is triangulated across the bend and cuts into the surface. Pass
  `mark='eye'` for an eye and `mark='line'` for a line drawn as an outline (a mouth, a brow, a stripe); an
  unmarked decal is unknown to the bake's texel readings.
- **`axis_fill`** takes the outline as azimuths round the segment's axis and lengths along it, and casts every
  vertex from outside toward the axis onto the outermost surface, so a region runs round a side, which a fill
  in its best-fit plane cannot. A point read off a front view at `x`, on a segment of half depth `D`, lies at
  about `degrees(atan2(x, D))` from the front. `reach` must exceed the surface's distance from the axis. Over a
  raglan yoke start the axis at the shoulder joint, or the rays miss. Centre a shoulder pad toward the front,
  or it sits on top and vanishes from the front view.
- **`surface_strip`** resamples the guide every `step` and snaps each point to the nearest surface, so the guide
  must already lie on it: cast the guide points from in front at regular steps first. Across low-poly facets a
  strip folds: for wide bands use `axis_fill` or `ring_band`, which follow the facets.
- **`surface_fill`, `surface_patch`, `surface_star`, `surface_blotches`** snap to the nearest surface point; a
  fill triangulates in its own best-fit plane and cannot wrap round a side. Pale blotches on a dark part read as
  specks, many small ones in a few reds as burn scars: judge the baked preview.
- **`ray_grid`** takes every vertex as a first hit from outside, where nearest-point snapping drops points onto
  the surface underneath and tears the band. Its faces are chords between the hits: over a ridge a coarse grid
  dips under the surface and bakes a hole there, so refine `angles` and `offsets` until the baked preview shows
  none.
- **`ring_band`** builds its band from the loft's own facets, between `half` toward the ring above and below.
- **`wrapped_stripes`** runs each stripe from near the top midline down one side, wavy, leaning back and
  tapering only near its end, so the midline stays clear and most of each stripe keeps its width. Both sides
  come from one call.
- **Dropped rings:** the removed rings lay almost on their neighbours' line, so a full-ring copy pushed off
  with `lift_rings` (its apexes too, from the centre they move away from) coincides with the mesh and bakes
  its colours where they were.

## Thin lines

Count a line's texels before painting it ([atlas](../atlas.md#count-texels-before-painting-a-line)); a
diagonal strap also stair-steps and chips at the island borders. Besides a boost (`BOOST`, `{part: linear UV
scale}`; a boost of k gives k squared the texels and takes them from every other island), a denser group or a
larger atlas (the human's budget call), a filled region in place of the line also reads.

## Paint what reads, not what was there

A plate baked into the texture loses its relief, so its painted shape must read on its own (a broad band over
the shoulder, not a thin outline). Small symbols go on flat areas, in a part of their own with a boost: on a
curve a badge wraps out of view. End a region at the edge of whatever covers it, or the bake carries it onto an
overlapping rim.

## What a missed ray does

Each tool falls back its own way (its docstring): `cast_point` returns None, `fan_decal` and `traced_eye` snap to
the nearest surface, `axis_fill` and `ray_grid` drop the face and leave a hole, `snap_ring` leaves the vertex,
`conform_plate` keeps it on its plane; nearest-point tools never miss. Counted misses are in the build report's
`misses`, the first missed point with them; the count does not say whether the fallback shows, the baked
preview does.
