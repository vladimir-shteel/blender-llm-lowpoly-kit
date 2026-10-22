# Torso and clothing

On a welded body the trunk is one surface from the crotch (or a garment's hem) to the neck: tight clothes and
bare fur are its band colours, its bottom ring splits into the leg holes and a pair of its rings opens into
the armholes ([joins.md](joins.md)). With separate-shell limbs the torso is any closed loft at the model's
density. A garment that stands off the body is shape; a colour change on the body is texture under the
texture stance and cut into the mesh under the geometry stance.

## The trunk as one surface

`torso.trunk` with its sections bottom up, the first the crotch, each `((x, y, z) centre, rx, ry)` with
optional vertex multipliers, one per ring vertex (`torso.SIDES`); the docstring gives each ring vertex's
angle and which index is which side. The first `round_rings` keep the full polygon, so the hips stay round
under tight clothes; above them the `torso.FLAT` vertices sit midway between their neighbours, a fitted
jacket's flatter outline, whose columns `torso.ARMHOLE_COLS` address. `boxes` draws the crotch and seat
rings as rounded rectangles round two thighs side by side; as ellipses their back-outer diagonals fall
inside the thighs.

```python
from lpk.core import edits
from lpk.core.sections import section_radii
from lpk.forms import joins, torso


def build_trunk(b, P, data):
    """b = Builder(PALETTE, vert_layers=(joins.LAYER,)); returns the armhole and leg hole loops."""
    sections = trunk_sections(P)                       # model-module Section records, bottom up
    names = [s.name for s in sections]
    hem, collar = names.index('hem'), names.index('collar')
    colour = lambda i, j, normal: 'trousers' if i < hem else ('shirt' if i < collar else 'skin')
    rings = [(s.at,) + section_radii(s, torso.SIDES)[:2] for s in sections]
    boxes = tuple((i, s.exponent) for i, s in enumerate(sections) if s.exponent != 2.0)
    R = torso.trunk(b, 'trunk', rings, colour, boxes=boxes)
    arm_holes = joins.armholes(b, R[names.index('chest')], R[names.index('armhole')], torso.ARMHOLE_COLS)
    leg_holes = joins.leg_holes(b, R[0], 'trunk', P['crotch_z'] + P['crotch_seam'])
    edits.apply(b, P, 'trunk', data)
    return arm_holes, leg_holes
```

The trunk's sections serve the blocks, the build, the seams and the rig alike: keep them in one model-module
function (the worked example's `trunk_sections`).

## The trunk's density

A body with welded limbs keeps `trunk`'s `torso.SIDES` vertices per ring: the holes index it. A torso
without welds may take a lower-density outline: `shapes.polygon_rings` with the vertices to drop, lofted with
`shapes.point_loft`, or any loft at the planned density. An even polygon of fewer sides is another outline,
its corners elsewhere (a groove can run down the front), where dropping vertices from the higher outline keeps
that layout on fewer triangles. Which reads right shows only in captures of both variants side by side.

## Measure the side as well as the front

The front sets only the widths; the depth and the side outline come from the side view. Shape the side by
per-ring offsets and front and back radii (`'off'`, `'ra_neg'`, `'rb_neg'` in `Builder.loft` ring options;
per-vertex multipliers in `trunk` sections, which its `boxes` rings refuse), not by extra rings: the waist's
back, the ribcage, the shoulder blades, the buttocks where the drawing shows them. A barrel chest can need a
deeper front radius at the chest ring than its width suggests; a blocky design's profile may be a slab.

- **A V-shaped torso:** after widening the chest rings, taper the rings between the hem and the chest back
  toward the waist's width; widening the chest widens the rings below it too, growing a jacket's hem into a
  belly.
- **A hunched figure:** ring centres and the spine bones in `bones(P)` on one smooth path (a quadratic from
  the hip joints to the shoulder line); centres placed one by one break into an S. Arms stay in the A-pose
  from the forward shoulder line; size the figure so the straightened body reaches the intended height.

## The neck under the head

With no collar or hood, carry the trunk's last rings up into the head and end them inside it: the top ring
buried under the head's surface past the jaw's underside, so no ring edge shows from the front, the side or
below. The head stays a closed part of its own, not welded. A ring left at the jaw line shows as a gap or a
collar under the chin. Build the head first and cast onto a surface of the head's parts alone, so the buried
neck does not catch the head's casts.

## Tight clothes are band colours

Colour the trunk's bands by their index in its `color` function, and let the legs leave a tight hem in line
with the hole (`joins.weld_leg`'s `follow`). A garment loft of its own stands off the waist, a flared cuff reads
as a skirt, and a pelvis of its own keeps a corner at the waistband. A boundary that falls between rings goes
to a colour source (`shapes.ring_band`, `shapes.band_source`) under the texture stance; under the geometry
stance add the ring and colour its band: that ring is the stance's cost.

## Garments from the body: a skirt, a tunic's hem, a belt

A garment that starts from the body (a skirt's waistband, a tunic below its belt, a vest's collar line)
takes its top section from the body at that height, pushed a little out, at the same n-gon angles; a section
of its own leaves a gap or a ledge. `torso.section_at(sections, z)` is that cut: the trunk's `Section` at a
height, interpolated between the two sections round it (the worked example's `trunk_sections` give them).

- **A skirt or a tunic's hem** that stands off the legs is `torso.skirt`: a separate open shell, not welded,
  from a top height down to a hem. Each ring stands `thick` off the widest the body gets above it, so it
  hangs from the hips instead of cutting into them, and spreads by `flare` toward the hem; its `tuck` ring
  closes the top edge into the body. A hem that ends above the crotch, tight on the body, stays a band
  colour of the trunk instead.
- **A belt** is `torso.belt`: a hoop of `width` and `thick` round the widest body across its height, with flat
  bands into the body above and below, `over` the skirt's `thick` when it sits on a skirt's top, and an
  optional `buckle` box on its front. Its returned `'front'` places another buckle (`shapes.star_prism`,
  `shapes.conform_plate`, [gear.md](gear.md)).

Measure from the drawings: the top and the belt's middle heights and the hem's height from the front or the
side view; `flare` from the hem's half width and half depth against the body's at that height; `thick` from
the drawn step at the hem's edge in the side view; the belt's `width` from the front.

```python
from lpk.core import edits
from lpk.forms import torso


def build_garments(b, P, data):
    sections = trunk_sections(P)                       # the trunk's sections, bottom up
    top = P['belt_z'] + P['belt_w'] / 2
    torso.skirt(b, 'skirt', sections, top, top - P['hem_z'], 'tunic', thick=P['skirt_thick'],
                flare=P['hem_flare'], rows=SKIRT_ROWS)
    edits.apply(b, P, 'skirt', data)
    belt = torso.belt(b, 'belt', sections, P['belt_z'], P['belt_w'], P['belt_thick'], 'belt',
                      over=P['skirt_thick'], buckle=BUCKLE_HALF, buckle_col='metal', buckle_part='buckle')
    edits.apply(b, P, 'belt', data)
    return belt['front']
```

Weights: the skirt to the hips and the upper legs (`ALLOWED = {'skirt': ['Hips', 'UpperLeg.L', 'UpperLeg.R']}`),
the belt and its buckle to the hips and the spine, or pinned to the hips in `FIXED`. Check the skirt for the legs below the
crotch with `lpk.stages.checks.shell_clearance` (`{'skirt': ['leg.L', 'leg.R']}`; the trunk's sections end
there, so `skirt` does not see the thighs) and in the test pose for the legs passing through it.

## Loose garments

- **Bell sleeves, a drop shoulder, an oversized top:** keep the armhole near the anatomical shoulder and give
  the sleeve its drape through its own rings (wide, `'off'` toward the bottom) and through the pose. Fix an
  intersection between the sleeve's underside and the body in the sleeve (a smaller inner radius near the
  socket), never by moving the seam down: a sleeve welded down the body's side reads as glued
  ([joins.md](joins.md#an-arm-welded-down-the-bodys-side)).
- **A sleeve much wider than the arm:** lower its ring centres with `'off'` until its top runs along the
  shoulder line in the front view's `outline_diff`; centred on the arm path it rises beside the head.
- **Baggy trousers:** alternate fuller and pinched rings (thigh, knee, hem bunching) and add radius noise with
  `shapes.jitter_rings` over `shapes.path_rings`, the first ring left clean; `amount` comes from the drawn
  outline. Even rings read as machined pipes. Trousers so wide they meet at the midline: narrow the inner
  side only ([joins.md](joins.md#which-radius-runs-along-which-axis)) and spread the knees.
- **Hems and linings:** a lining ring of a smaller radius in a lining colour, a little further along the loft's
  axis than the rim ring. A ring folded back level with its neighbour flips the loft frame and twists the
  band.
- **Hoods:** sections narrowing toward their top, wide over the shoulders; the first ring an inner lip laid
  onto the head and neck with `shapes.hug_rings`; `shapes.point_loft` for a hood narrowing to a peak. A hood of
  plain ellipses reads as a helmet or a box from the side.
- **A stand-up collar open at the front:** fold the front vertices down to just above the collar's base to
  open a V; a collar up to the jaw needs the vertices beside the front pair folded part of the way too.
  Pulling the front vertices toward the neck closes the collar over the throat and sinks the head into it.
- **A sash, a tabard or a loincloth:** a flat loft with a rectangular section (`ra` its width, `rb` its
  thickness) through ring centres cast onto the pelvis and the thigh, lifted further off toward the bottom, a
  flat bottom cap and a few `fur.tuft` tatters of different lengths. Over thin legs long flaps lifted far off
  read as an apron column and hide the legs. Its weights go to the hip and the upper leg (`ALLOWED`).

## Detail, and what clothes hide

An opening, a shirt strip, piping and pockets are colour sources on the garment's form under the texture
stance ([markings-decals.md](markings-decals.md)); a colour in a fold (a shirt in an open collar) goes on the
faces, since the bake's rays can miss a decal there. Whether the body under a garment exists is the human's
call; when it does not, end the limbs inside the garment with a flat cap: hidden geometry costs triangles and
intersects.

## Limits

- `trunk` has `torso.SIDES` vertices per ring, fixed: the one density the welded family is built for. A box
  ring with a vertex multiplier other than 1 raises `ValueError`.
- `polygon_rings` is not for a welded trunk: `ARMHOLE_COLS` and `split_bottom_ring` index the full ring.
- `section_at` reads the sections as horizontal cuts; under tilted section normals it approximates.
- `skirt` runs straight between its rings: where the body bulges between two ring heights it shows through
  (add `rows`). It is one open surface: from below its inside shows. In a wide stride the legs pass through
  it.
- `belt` is rigid round the body: a deep bend at the waist pushes the trunk through it.
