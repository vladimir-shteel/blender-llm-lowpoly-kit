# Gear: straps, plates and hard parts

Gear on a character is hard surface: flat caps, cut corners and flat facets read as made next to the organic
body, so the apex ends of organic parts do not apply to it. Gear that changes the silhouette is geometry, in a
part of its own. Under the texture stance gear that does not change the silhouette is painted
([markings-decals.md](markings-decals.md)); under the geometry stance it is an in-mesh decal or a plate in a
part of its own, or left out by the human's decision.

The library has no hard-surface forms yet (a chamfered box, a hinge pin, a hub, a plate stack, a mechanical
hand): build them from the primitives below as local forms of the model
([README.md](README.md#where-a-new-form-goes)).

## Choose the primitive

| The piece | Call |
|---|---|
| A block or a case | `Builder.box(part, center, half, rot, col)` (`rot` a `mathutils.Matrix` or None) |
| A rounded-box, plate or chamfered section | `Builder.loft` with flat caps (`cap0='flat'`, `cap1='flat'`), its ring options shaping the section |
| Spikes and studs | `Builder.pyramid(part, base, apex, col)`, the base buried |
| A star badge, a buckle, a lens in a frame | `shapes.star_prism` |
| A belt with a box buckle | `torso.belt` |
| A screen, a light, a symbol | `Builder.decal(part, pts, col, normal)`: one flat polygon a few millimetres off the surface |
| Armour, pads, panels that read as part of the garment | `shapes.conform_plate` |

## Place gear by casting onto the body

Cast the piece's anchor onto a surface of the parts it sits on, then build it from the hit and its normal:
gear placed by coordinates floats or sinks after the body changes.

```python
from mathutils import Vector

from lpk.core import edits
from lpk.core.shapes import bvh_of, cast_point, conform_plate


def build_gear(b, P, data):
    body = bvh_of(b, ['trunk', 'arm.L'])
    plate = conform_plate(b, 'pad.L', body, Vector(P['pad_c']), Vector((0.0, -1.0, 0.0)), Vector((0.0, 0.0, 1.0)),
                          P['pad_w'], P['pad_h'], Vector(P['shoulder_joint']), 'armour',
                          side_col='armour_dark', chamfer=PAD_CHAMFER)
    edits.apply(b, P, 'pad.L', data)
    half = P['buckle_half']                                  # (x, y, z) half sizes off the drawing, m
    hit = cast_point(b, body, P['belt_front'], (0.0, 1.0, 0.0), sink=-half[1], distance=0.5, part='buckle')
    if hit is None:
        raise ValueError('the buckle ray missed the trunk: move P["belt_front"]')
    b.box('buckle', hit, half, None, 'metal')
    edits.apply(b, P, 'buckle', data)
    return plate['top']
```

A negative `sink` stands the point off the surface along the ray's reverse, here the buckle's half depth in
front of the belt.

## Plates that follow the body

`shapes.conform_plate` with its centre just off the surface and its `focus` deep inside the body: the rays
converge on `focus`, so a near focus shrinks the plate. The grid counts and `chamfer` shape its outline (the
docstring gives the values for an elongated hexagon), `jitter` chips it (seeded by `seed`), `offset` and
`thick` come from the drawn gap and profile. The returned `'top'` and `'normal'` grids place rivets and decals
on it. A box placed on a shoulder reads as glued on; a projected plate reads as part of the garment. A plate
that breaks the side profile as the drawing's pad does reads as a pad; one that stays inside it reads as
paint.

On a ball-like mass (a shoulder, a round helmet, a big fur mass) the surface normals turn the plate edge-on
to the viewer: fix its facing in a local form over the plate's grid, moving its vertices most of the
way toward the tangent plane at its centre and lifting it off the mass.

Detail barely proud of the surface (pocket flaps, small buckles, latches, small lights) does not change the
silhouette at the read size: paint it (a thin `conform_plate` or a fill into a colour source), or under the
geometry stance make it a `Builder.decal` or a thin plate in a part of its own.

## Straps

- Under the texture stance a flat strap is paint: `shapes.axis_fill` round the segment, or `shapes.ring_band`
  on a loft's ring (a strap round a column). A strip snapped across low-poly facets folds and steps, where a
  region or a ring band follows the facets. A narrow diagonal strap stair-steps when it is thin for its
  texels ([markings-decals.md](markings-decals.md#thin-lines)).
- Under the geometry stance a flat strap is the faces between a loft's own rings coloured as the band, or a
  thin geometric strap.
- A belt round the waist is `torso.belt` at a height of the trunk's sections, its buckle a box on its front
  or another piece built at its returned `'front'`
  ([torso-clothing.md](torso-clothing.md#garments-from-the-body-a-skirt-a-tunics-hem-a-belt)).
- Another strap that changes the silhouette (a hanging sash, a bandolier) is a loft with a rectangular
  section through ring centres cast onto the body and lifted off it, with flat caps. Look closely: the body
  must not show through it.

## Gear that encloses a limb

A bracer, a gauntlet or a boot shaft: end the limb loft inside the gear with a flat cap and drop the rings it
hides ([joins.md](joins.md#limbs-a-garment-or-gear-hides)); where organic cloth meets a rigid housing, end the
cloth in a short stub under the housing. Check from below and behind for a showing open end.

## Make neighbours separate

Same-value pieces side by side (white links on a white shell) vanish into one shape: put a dark rail or core
behind them. Near-black parts read as flat slabs: give them a mid-grey rim or sole so their sub-forms show.
The grey is a palette value the human picks. Judge it in the colour capture.

## Mechanical bulk

Rigid shells at the measured width, chamfered dark cores per segment, a dark knuckle block at each joint, each
member overlapping the next, hubs on the flexion axis turned toward the front; organic radii or widths under
the drawn ones read as a stick with floating plates ([joins.md](joins.md#a-limb-unlike-its-pair)).

## Rigid pieces

Give every rigid piece a part of its own and pin it to one bone in `FIXED` (`{part: {bone: weight}}`, `'{s}'`
expanding per side), a hub to the child bone. Rigid pieces must not bend; in a pose they rotate through each
other round the hubs, which reads as a mechanical joint. Place wrist devices on the back of the forearm in the
rest pose: a screen drawn facing the viewer comes from the pose.

## Limits

- `conform_plate` builds the top and the rim walls; its underside stays open against the body. A grid point
  whose ray misses stays on the plane, its normal back along the ray.
- `star_prism`'s and `Builder.pyramid`'s backs stay open (`pyramid(..., cap=True)` closes its base).
