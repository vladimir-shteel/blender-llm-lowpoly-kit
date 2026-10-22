# Tails

A tail is built once on the midline, or drifted to one side as drawn. Its rest shape is straight: the rig's
bone chain, spaced evenly along it, gives every curl.

## Tails are straight in the mesh

Model a curled tail, an S on the floor or a tail wrapped round a leg straight from the pelvis back and down
toward the floor, and leave the curl to the pose. A curled mesh cannot straighten or swing cleanly; a straight
one skins evenly along its chain. The straight mesh loses the curl from every still capture, the rest pose
included: when the curl is part of how the character reads (drawn the same in every view), ask the human
whether the straight rest tail is acceptable and whether the animation set must carry the curl.

## Choose the form

| The drawing shows | Form |
|---|---|
| A plain or thin tail | `tails.straight_tail`, a narrow root, an even body, rings where the chain bends |
| A bushy brush tail | `straight_tail` with `fur.fur_fringe` tufts in a part of their own |
| A ringed tail | `straight_tail` with its root open, then `shapes.band_source` on a source, unrolled in `STRIPS` |
| Long flat locks fanning from one root (a feathered tail) | `tails.lock_fan`, its knot buried under clothing |
| A thick tail that must clear baggy trousers | `Builder.loft` over `shapes.path_rings` through the root, a point behind the hips and the tip |

## Build it

```python
from mathutils import Vector

from lpk.core import edits
from lpk.core.builder import Builder
from lpk.core.shapes import band_source
from lpk.forms import tails

TAIL_SIDES = 6


def build_tail(b, P, data):
    """A ringed tail: the mesh keeps the shape's rings, the bands go on the Tail source;
    STRIPS = {'tail': TAIL_SIDES} unrolls it as one strip."""
    root, tip_dir = Vector(P['tail_root']), Vector(P['tail_dir']).normalized()
    profile = P['tail_profile']               # [(s, ra, rb)] in metres, read off the side and back views
    R = tails.straight_tail(b, 'tail', root, tip_dir, P['tail_len'], profile, TAIL_SIDES,
                            Vector((1.0, 0.0, 0.0)), 'fur')
    edits.apply(b, P, 'tail', data)
    source = Builder(PALETTE)
    band_source(source, 'tail', R, P['tail_bands'], root + tip_dir * P['tail_len'], ('fur', 'ring'), 'ring')
    return source
```

The profile's `s` is metres from the root, `ra` along `ref` projected off the direction, `rb` across it; keep
the last `s` short of `length`, or the tip's cone folds back over it.

## Close the root inside the body

Start the loft inside the hips or under clothing and close the root with a buried apex: `cap0` a point
inside the body. A thinner neighbour can uncover an open root. The exception is a part unrolled as a strip,
which keeps its root open (`cap0=None`) and starts deep enough in the body that no neighbour uncovers the
opening. A tail running straight down rubs through baggy trousers: route it back first, then down, with a
`Builder.loft` over `shapes.path_rings`, since `straight_tail` runs in one direction.

## Coloured bands

Under the texture stance build only the rings the shape needs, its root open, its tip on its apex and nothing
else in the part, then lay the bands on a colour source with `shapes.band_source` over the rings
`straight_tail` returns, and list the part in `STRIPS`. `band_source` interpolates a ring at every band
boundary, so the boundaries fall on the strip's texel lines whatever the mesh's ring count. It alternates its
first two colours from the root: count the drawn bands from the root to the tip, a dark tip among them, and
pass that count with the root's colour first so that the last band comes out in the drawn colour; `tip_col`
colours only the apex cone past the last ring. Place the tip from the drawing: a blunt drawn tip keeps a
full last ring with its apex just past it.

A strip needs the part's ring-major vertex order with the apex last, so tufts go in another part; smart
projection would cut the bands into pieces that do not meet at the seams. Keep the source on the mesh's own
rings: one with more sides paints the wrong colour where the facets cut through it. Under the geometry stance
put a ring at each band boundary and colour it through the loft's `color`.

## A big brush tail

One `straight_tail`, not mirrored, a narrow root closed by a buried apex, its widest ring over the lower
middle, a soft close over the last rings and the apex only a little past the last ring. Tufts with
`fur.fur_fringe` on several of the returned rings, in a part of their own, `keep` turning them off the side
facing the legs and each ring's vertex list rotated to a different start, so they stagger round the tail;
rooted inside the loft, they reach out and down past its outline. An even tube with one fringe ring stays
smooth over most of its length, and a long apex cone ends it in a point the drawn brush may not have. A glow
or a speckle goes in the texture.

## A fan of locks

`tails.lock_fan` with the locks read off the side view as (angle under the horizontal backward, length);
every other lock splits into a mirrored pair. `spread` and `drop` are components of a lock's direction before
it is normalised, not distances. Every lock starts at the knot, so bury the knot under clothing.

## The tail between the legs

A tail on the midline fills the gap between the legs in the front view: drift it to one side as drawn,
behind one leg. `lpk.stages.checks.limb_separation(<body>, ['tail'], ['leg.L'])` measures the touching span
between the tail and a leg; the front capture shows it.

## Limits

- Every section stays perpendicular to `direction`: a bend is a pose, or a path loft.
- A thin tail needs enough rings for its chain to bend smoothly; nothing else changes its silhouette, so the
  pose test judges it.
