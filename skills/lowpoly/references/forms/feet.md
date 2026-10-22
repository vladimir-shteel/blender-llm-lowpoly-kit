# Feet

A symmetric pair is built on the left (`'foot.L'`, the side sign +1) and copied with
`b.mirror_part('foot.L', 'foot.R')`; a foot that differs by design is built on its own side with that side's
sign. Toes face -Y. The leg loft ends inside the foot. The foot is the silhouette's base: measure it with
the side view's `outline_diff` and against the floor (the build report's `zmin`); the human judges it from
the side and three-quarter in Blender.

## Choose the form

How a foot reads comes from its volume and its digits' silhouettes, not from the form's name: a slanted
metatarsus with thin toes can read as a slab on the floor, a puffy mitt with claws peeking out as a paw, a
hand form laid flat as a row of claw spikes. Judge the chosen form against the foot's crop.

| The foot reads as | Form |
|---|---|
| A long hind paw on a raised heel, toes and claws in the silhouette | `feet.strap_paw` (built at y = 0, moved under the ankle) |
| A puffy paw standing on the floor | `feet.mitt_paw`, heel and toe as floor points |
| A platform boot | `feet.platform_boot` |
| A heavy lace-up boot to mid-calf | `feet.work_boot` (symmetric about its own x: no side parameter) |
| A mammal's clawed digits on an instep you build, or at a digitigrade ball | `feet.paw_toes` |
| Bird- or raptor-like toes from the ball of a digitigrade foot | `feet.talon_toes` (a toe at 180 degrees is a back toe) |
| A plain low shoe | a `ProfileKey` profile lofted with `profile_rings` (the worked example's `_shoe`), or a local form |
| A boot ending in a point | a horizontal `Builder.loft` with `axis=` along the foot to a toe apex just past the last ring |

`strap_paw` and the boots build sections fixed in metres around their `width` and `length`: compare their
size with the drawing before styling round them. `paw_toes`' `sections` are `Builder.loft` apothems, not the
drawn toe's half sizes: compare the built digits with the drawn toes.

## Measure

Heel, ball and toe off the side view, the foot's half width off the front, the ankle where the leg's joint
is (not at a trouser hem or a fur cuff). Feet that read small under the body on the whole figure take a
named style factor in the model module, proposed to the human, applied through the sizes you pass before
anything is placed on the foot.

## Build it

```python
from mathutils import Vector

from lpk.core import edits
from lpk.core.builder import Builder
from lpk.core.shapes import ring_band
from lpk.forms import feet


def build_feet(b, P, data):
    """A strap paw under each ankle, its strap painted on the Paint source (SOURCES['Paint']['mask'] the feet)."""
    rings = feet.strap_paw(b, 'foot.L', 0.0, 1, P['ankle_z'], 'fur', 'claw', length=P['paw_len'],
                           width=P['paw_w'])
    offset = Vector((P['ankle_x'], P['ankle_y'], 0.0))
    b.move_part('foot.L', offset)
    dz = b.ground_part('foot.L')
    edits.apply(b, P, 'foot.L', data)
    b.mirror_part('foot.L', 'foot.R')
    paint = Builder(PALETTE)
    shift = offset + Vector((0.0, 0.0, dz))
    ring_band(paint, 'strap.L', [[p + shift for p in r] for r in rings], 'strap', P['strap_half'])
    paint.mirror_part('strap.L', 'strap.R')
    return paint
```

## Standing on the floor

Ground each foot in the build: `b.ground_part(<part>)` after the foot's last shaping step and before
`mirror_part`. An elliptic loft's radii are apothems, the distances to its flat sides: a ring touches the
floor with a flat side or a vertex depending on its sides and its frame, so a foot placed by its radius sinks
or floats. The boots ground themselves; `mitt_paw`, `strap_paw`, `paw_toes`, `talon_toes` and local
forms do not. `ground_part` returns its shift, which every point a form returned (the strap rings) takes
too. A lift typed in as a constant stops matching the next time the foot's shape changes.

## Straps, socks and wraps

Toes and claws that change the silhouette stay geometry: a sock-shaped paw with painted toes loses the
splayed claws. A strap round the paw's column is paint under the texture stance: `shapes.ring_band` on the
rings `strap_paw` returns, shifted by the `move_part` offset and the `ground_part` shift, into a colour source
masked to the feet. `ring_band` follows the loft's own facets, where a ribbon snapped to the surface twists
into a zigzag at every corner of the column. Under the geometry stance colour the faces between those rings.

## Boots

- Boots narrower than the trouser hems vanish under them: compare their widths in the front view's `outline_diff` `parts`.
- The upper meets the sole at full width (`work_boot` sinks it in); a narrower bottom leaves a shelf of sole.
- The rig's foot and toe bones bind to the boot's points, which `feet.work_boot_points` gives without
  building, from the same arguments and on the floor as the built boot stands; `bones(P)` reads them there:
  `k = feet.work_boot_points(x, top_z, length=P['boot_len'])  # k['ankle'], k['ball'], k['toe']`.
- Near-black boots read as flat slabs: give them a lighter sole and rand, a palette value the human picks.
- Cast laces from above onto the instep: cast from the front they land on the toe cap, the first surface in
  their way.
- A pointed toe: the apex's distance past the last ring sets how pointed it reads; far past it the last band
  stretches into a spike the drawn toe may not have. A split toe is the last segment plus the apex, the split
  itself a painted strip, or a face-colour cut under the geometry stance.

## Digitigrade feet

The leg runs hip, knee, hock and ball ([joins.md](joins.md#digitigrade-and-plantigrade-legs)); the toes carry
the silhouette and hide the leg's flat cap:

- a bird's or a raptor's toes: end the leg loft at the ball with a flat cap inside the toes and fan
  `talon_toes` from the ball, their tips touching the floor (place the ball a toe radius above it);
- a mammal's digits: end the leg loft at the ball with a flat cap and run `paw_toes` forward to the drawn toe
  tips, its open ball rings buried in the leg's end;
- a mitt paw: end the leg at the hock and stand `mitt_paw` under it, heel to toe;
- fur drawn at the shin's top: a fringe of a few upward tufts ([hair-fur.md](hair-fur.md#masses-and-fringes)).

Bird's toes under a mammal read as talons, a flat hand form as claw spikes: the human judges which from the side in Blender.

## Limits

- `talon_toes`' default `scale` and `claw_len` are sized for the figure its docstring names, taller than
  the one the other defaults assume; set both from the figure's own toes and claws, not by one body-height
  ratio.
- `paw_toes` with an odd `digit_sides` is not symmetric about each digit's centre line: build one foot and
  copy it with `mirror_part`. Neighbouring digits overlap and read as one mass once a digit's span passes
  `spacing` (the docstring gives the span per side count).
- `mitt_paw`'s claws, fixed in metres, dip under the floor on a low paw (its docstring gives the height):
  `ground_part` after it.
- `strap_paw`'s ankle column, heights and toe sections are fixed in metres; only the instep, ball and toes'
  spread and reach scale with `width` and `length`.
