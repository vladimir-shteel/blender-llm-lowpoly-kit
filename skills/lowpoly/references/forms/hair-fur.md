# Hair and fur

Hair and fur that change the head's or the body's silhouette at the read size are geometry; hair that does
not is the head's own faces coloured. The jagged colour pattern inside a mass is texture. Build them after
the head's last change: roots are cast onto a surface of the head (`shapes.bvh_of(b, ['head'])`), strands
onto a new one that includes the cap (`shapes.bvh_of(b, ['head', 'hair'])`).

## Choose the form

| The drawing shows | Form |
|---|---|
| Hair whose hairline thickness shows at the read size | `hair.hair_cap`, then `hair.remove_covered` |
| Short hair kept to the top, clipped sides and back | `hair_cap` with a high hairline, few rows, a thin shell; the clipped colour on the head's upper side bands |
| A loose lock, a fringe, a lock along a parting | `hair.hair_strand` |
| Short spikes over the scalp | `hair.hair_locks` |
| A bun | `hair.hair_bun`, its base buried in the cap, wisps sideways and back |
| Long hair falling down the back | `hair.hair_mantle`, its path starting buried in the cap |
| A long beard hanging below the chin | `hair.long_beard` ([eyes-face.md](eyes-face.md#facial-hair)) |
| A giant's mane, a fringe falling from the crown down one side | `fur.fur_mass` |
| A shaggy edge: a cuff, a collar's rim, a mane's rim | `fur.fur_fringe` on the widest ring |
| One spike, shard or blade | `fur.tuft`; a fan from one root, `fur.tuft_fan` |
| A lock that sweeps or hooks | `hands.talon` bent toward its curl; a fan of them, `fur.flame_locks` |
| Hair the budget cannot carry as a cap | a `Builder.box` or a local form |

## Hair is part of the head's size

Measure the skull under the hair and the hair's outline apart. Painted hair adds no volume: where the drawn
outline includes the hair, a head with painted hair reads off-size at any scale. Whether hair is geometry
follows its silhouette at the read size; when the drawing does not say, ask the human.

## Build a cap

```python
import math

from mathutils import Vector

from lpk.core import edits
from lpk.core.shapes import bvh_of
from lpk.forms import hair


def build_hair(b, P, data):
    front = math.atan2(P['hairline_front'] - P['head_c'][2], P['head_half'][1])

    def line(phi):                  # the hairline's elevation per azimuth, from the front and side views
        a = abs(math.atan2(math.sin(phi), math.cos(phi))) / math.pi
        return front + (P['hairline_back_rad'] - front) * a

    def thick(phi, f):              # full over the crown, a few millimetres at the edge
        return P['hair_t'] + (P['hair_edge_t'] - P['hair_t']) * f

    skull = bvh_of(b, ['head'])
    covered = hair.hair_cap(b, 'hair', skull, Vector(P['head_c']), line, thick, 'hair', n=HAIR_COLUMNS,
                            rows=HAIR_ROWS, symmetric=True)
    edits.apply(b, P, 'hair', data)
    hair.remove_covered(b, 'head', covered)
    return bvh_of(b, ['head', 'hair'])
```

Run `remove_covered` once the cap is built, with the covered part (the head) as its `part`: it deletes the
skull faces wholly under the cap, which then cost no triangles. A part of its own (an ear) keeps its faces.

## The cap: hairline, edge and columns

- `line(phi)` gives the hairline's elevation round the head's centre, a table read off the front and side
  views: high over the forehead, raised above the ears for pulled-up hair, low at the nape. `thick(phi, f)`
  gives the thickness from the crown (`f` 0) to the hairline (`f` 1). The last ring tucks under the hairline
  into the head and closes the edge.
- A thick edge over the forehead reads as a helmet rim: keep `thick` small toward the face and full over the
  crown and the back.
- A parting or a hairline running diagonally follows the columns only as finely as they are spaced: raise
  `n` until it follows the drawing.
- `symmetric=True` casts the +X half and mirrors it, an exact mirror image for a centre on the midline;
  without it a head triangulated differently on its two sides gives a cap a few millimetres off mirror
  (`lpk.stages.checks.mirror_report` lists it).
- Skull faces showing through near the edge, at the drawn thickness: the cap's vertices land on a faceted
  head and its faces run as chords between them, so add thickness locally through `thick` per azimuth, or
  more columns or rows; a thicker whole cap reads as a helmet. `lpk.stages.checks.shell_clearance(<body>,
  {'hair': 'head'}, centre=P['head_c'])` lists the head vertices standing out through the cap, the farthest
  first.

## Ears and the tuck ring

Decide for each ear which surface it grows from; either way it stays a part of its own.

- **An ear beside the hair** (human ears, ears under a pulled-back cap): keep the whole ear, its tip
  included, under the cap's tuck ring: lower or shorten it, or raise the hairline over it through `line`.
  Build it with the head, cast onto the skull. An ear tip above the tuck ring pierces the shell from inside.
- **An ear rising out of the hair** (animal ears on a head with hair): root it after the cap, cast onto a
  surface of the head and the hair together, tilted outward as drawn. An ear rooted on the skull under the
  cap is buried or floats.

## Strands, locks, buns, mantles

- `hair_strand` lays each section flat against the nearest surface at its own point, where a frame carried
  from the root would stand a fringe off the forehead like a visor. Its root and lift snap to the nearest
  surface point: cast each traced point from in front onto the head-and-cap surface and pass the hits. A
  lock lying flat on a temple is seen edge-on from the front: give it more `lift`, and more `thick` against
  `width`.
- `hair_locks` casts each root straight down at `(x, y)` and buries it, so locks follow the head's shape.
  With `mirror=True` list only the locks at `x >= 0`: the -X side is the exact mirror image. A lock whose ray
  misses is skipped and counted in the build report's `misses`.
- `hair_bun` wisps pointing up read as cat ears.
- `hair_mantle`: route it behind an A-pose arm, or the arm pierces the mass; outside a high collar or hood,
  or leave it out where the collar hides the nape (the human's call from the back in Blender).

## Masses and fringes

- `fur_mass` is one smooth loft with big `fur_fringe` tufts only on the rings whose outline needs them. The
  drawn outline runs over the tuft tips, so size the smooth volume inside it by the tufts' reach. Bury
  `cap0` well inside the head when the mass starts on it; a shallow one folds the first band across the cone.
  An apex close behind the last ring makes the end a flat disc. For a huge mane: a fixed `axis`, the back
  rings higher for a hump, the apex well behind the last ring, and a lip ring tucked onto the skull behind
  the eyes so the face sits in an opening that shows the mane's thickness. What the mass hides completely
  (the neck under a mane) is not built.
- Tufts break the outline, not the surface: few and large on the widest ring, alternating long and short; a
  second row shifted round the ring (a fringe's `'shift'`); a few on back rings for the side and back
  silhouettes; `keep` holds them off gear and off the side facing the viewer. Inner-ring tufts, face ruffs and
  zigzag sections read as crumpled paper. `out` sweeps them back or radiates them like a sunburst
  (`fur.fur_fringe`'s docstring gives the values).
- A cheek ruff flaring from the face's corner: flat `tuft` blades per side (a thin `thick`, `front` forward,
  `seal=True`) off the corner under the eyes, one straight out to the drawn cheek width, one down the jaw.
  Round tufts there fill the skull's V into puffy cheeks.
- Wing-like fur hanging from the arm has no library form: a local form, a loft over a thin upper arm, an apex
  above, a long taper to its widest along the forearm, flattened and hanging outward, tufts only on the
  vertices facing out or sideways. An even cone reads as a megaphone.

## Tufts and curved locks

`fur.tuft` with round sides (`n`) reads as a spike, flattened ones (a small `thick`, `front` set) as a shard
or a blade. It runs straight: tufts all round a crown read as a hedgehog's spikes where the drawing
sweeps a forelock forward and a ruff back. `tuft_fan`'s lean is a weight on `across`: give both sides of a
mirrored pair the same `across`, or they lean apart. `flame_locks`' curl sign flicks a tip up and out (1) or
hooks it down (-1); alternating signs read as a spider's legs.

## Limits

- An open tuft base shows its inside where the host is too thin to bury it or a neighbour can uncover it:
  `seal=True` on `tuft`, `fur_fringe` and `hair_mantle`, a buried apex `cap0` on a loft root.
- One arc per lock: a drawn mane's S-curves with hooked tips have no form yet; whether the single-arc gesture
  reads is the human's call.
- `hair_cap` puts a vertex whose ray misses at a fixed distance from the centre (its docstring) and counts
  it in `misses`.
