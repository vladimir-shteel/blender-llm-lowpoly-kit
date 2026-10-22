# Head

Heads face -Y and are built once on the midline, a closed part of their own; the trunk's neck ends inside
them ([torso-clothing.md](torso-clothing.md#the-neck-under-the-head)). Eyes, hair and ears are cast onto the
finished head: take the head's surface (`shapes.bvh_of(b, ['head'])`) after its last deformer and its
`edits.apply`, never before.

## Choose the form

| The head reads as | Form |
|---|---|
| A muzzled animal, a reptile, any silhouette drawn from the side (an elongated skull, a helmet-like head) | `head.profile_head` with `ProfileKey` records |
| The same, but a key needs a loft option a `ProfileKey` has no field for (`ra_neg`, `rb_neg`, `off`, `mult`) | `head.snout_head` with keys in metres (length, width, height 1) |
| A stylised human at its fixed density | `head.human_head` |
| A head the budget or the read size cannot carry at those densities | `profile_head` at a lower side count, a `Builder.box`, or `shapes.point_loft` through measured slices in a local form |

Compare the triangle cost in each docstring with the brief's budget first. Profile keys set whole
sections, so a face that needs a flat front plane and a separately controlled corner to the sides is hard to
hold in a profile loft; horizontal slices (`human_head`, `point_loft`) carry such planes directly.

## How the keys make the front form

The side view sees only each key's top and bottom; the front and three-quarter form comes from the keys as
sections:

- Each key is a superellipse centred at its mid-height, half its top-to-bottom span as its half height, its
  half width at that mid-height, where it is widest. The exponent sets round (2) against box (higher). The
  loft runs straight from section to section.
- The front outline is the envelope of all sections, a width per height, not per key. Read each key's half
  width at its own mid-height on the head alone (no ears, hair or ruff), then check the envelope with
  `head.front_envelope`. A section the envelope hides (a muzzle in front of the cheeks) shows its width only
  on its own drawn outline.
- A section is as wide below its mid-height as above it unless the key gives the lower half its own
  half width (`half_width_lower` of a `ProfileKey`, `'ra_bneg'` in a `snout_head` key's options).
- A mass standing out of another (a muzzle from the face plane, a brow over the eyes) is a width or height
  step between two close keys.
- The apex turns the last band into a cone: how far it sits past the last key sets how pointed the end
  reads. A blunt drawn muzzle keeps a nearly full last key just behind the nose apex; only a drawn point
  puts the apex well ahead of a small last key.

Half widths read off the front where the drawn width is the ears, the hair or another section's pass the side
comparison and still distort the front: a wide cranium over a narrow muzzle reads as a pear.

## Measure the keys

- **A calibrated side view draws the head:** trace the head's side outline and its front outline alone as
  views.json traces on the largest calibrated drawing of each view (a head close-up when one is calibrated),
  tied to the head part. Choose the key columns at the side outline's turning points (back of the skull,
  crown, eye plane, face plane, muzzle root, nose base, the muzzle's drawn front) and read them with
  `head.traced_keys`; `head.side_key` reads one key and `head.side_point` an apex. The columns and exponents
  stay your choice. The worked example [snout-keys.md](snout-keys.md) reads one drawn head through two
  passes.
- **Only proportions are known:** `head.muzzle_keys` with the values in head units (each divided by the
  head's length, half width or half height). It fills every key it is not given from fixed ratios, which
  fit a head no profile shows. `bridge=(root top, nose top)` runs a straight nose line after a stop step
  where the default eases down.
- Measure a tilted or turned head along its own axis, and the skull under the hair
  ([hair-fur.md](hair-fur.md#hair-is-part-of-the-heads-size)).

Traced keys come as `(s, top, bottom, half width[, options])` in metres about the head centre, `s`
positive toward the back; the fifth element is an exponent or a dict of loft options (`snout_head`'s).
About the same origin (axis -Y, up +Z) each becomes `ProfileKey(name, s, top, bottom, half_width,
exponent, half_width_lower)` with `s` turned in sign (a `ProfileKey`'s runs toward the front), `exponent`
the fifth element or its `'p'` (the field's default when absent), and `half_width_lower` its
`'ra_bneg'` (None without it). A key whose options hold `ra_neg`, `rb_neg`, `off` or `mult` has no
`ProfileKey` form and stays a `snout_head` key. Head-unit keys from `muzzle_keys` are first scaled by the
head's length, half height and half width.

## Build it

```python
from mathutils import Vector

from lpk.core import edits
from lpk.core.builder import Builder
from lpk.core.sections import ProfileKey
from lpk.core.shapes import bvh_of, cast_point, lobe
from lpk.forms import head as head_form

HEAD_SIDES = 10                   # this model's sides per section, planned against its budget


def head_keys(P):
    """The head's profile keys from the back of the skull to the nose, m about P['head_o']."""
    return tuple(ProfileKey(name, s, top, bottom, w, exponent=e) for name, s, top, bottom, w, e in P['head_keys'])


def build_head(b, P, data):
    h = head_form.profile_head(b, 'head', P['head_o'], head_keys(P), HEAD_SIDES,
                               {'skull': 'fur', 'snout': 'muzzle'}, nose=P['nose'], skull=P['skull'],
                               stop='eye', eye_height=P['eye_h'])
    head_form.wedge_muzzle(b, 'head', Vector(P['head_o']), 1.0, 1.0, h['keys'], h['stop'], k=P['wedge_k'])
    edits.apply(b, P, 'head', data)
    skull = bvh_of(b, ['head'])
    root = cast_point(b, skull, P['ear_out'], (-1.0, 0.0, 0.0), sink=P['ear_sink'], distance=1.0,
                      part='ear.L')
    if root is None:
        raise ValueError('the ear root missed the skull: move P["ear_out"]')
    lobe(b, 'ear.L', root, P['ear_tip'], P['ear_w'], P['ear_t'], P['ear_front'], 'fur', inner_col='ear_in')
    edits.apply(b, P, 'ear.L', data)
    b.mirror_part('ear.L', 'ear.R')
    return h, bvh_of(b, ['head'])
```

`profile_head` returns `'rings'`, `'keys'` (the sections as lofted, in `snout_head`'s form, for
`front_envelope` with the origin as centre, `wedge_muzzle` and `profile_key_deviation` with length and h 1),
`'names'`, `'stop'`, `'pt'` and, with `stop` and `eye_height`, `'eye'` and `'eye_x'` for the eyes.
`snout_head` returns `'rings'`, `'eye'`, `'eye_x'` and `'pt'`. `human_head` returns `'eye'`, `'eye_x'`,
`'front_y'` and `'pt'` (head units to world, for decals and gear). Its `color(i, j, normal)` names the bands
and columns in its docstring; `profile_head` also takes `{key name: palette name}`.

## Shape it after the loft

Deformers run before the part's `edits.apply`, which must see the final form:

- **A triangular nose and a ridged bridge:** `head.wedge_muzzle`. Its default `k` is a start, not a fit:
  lower it where the front capture shows the root or the middle narrower than drawn, raise it only while the
  ridge still reads round. On a head with stored edits a change of `k` moves the edited vertices too (the
  edits are offsets on unchanged topology): look at the edited head again.
- **A chin narrower than the cheeks:** give the jaw's keys a lower half width, checked with
  `front_envelope`; or `head.taper_below` over the built head with `start` at the cheek line, under the eyes.
  It scales every vertex below `start`, the muzzle included: started higher, it narrows the face at the eyes
  until their outer corners fall off it. `front_envelope` sees lower half widths, not the taper.
- **A drooping profile on an edited head:** `head.lift_muzzle` raises the nose tip and keeps the topology;
  new keys or sides change it, and the build stops on the stored edits until they are re-captured or dropped.
- **A deep, boxy jaw that keeps its depth to the chin:** boxy exponents in your keys, or `head.REPTILE_KEYS`
  with `REPTILE_NOSE`, `REPTILE_SKULL` and `REPTILE_STOP`. Where the drawing colours the top darker than the
  jaw, end the top's colour at the mouth line in the `color` function; a snout tapering in depth reads as a
  capsule or a duck bill.
- **A styled head:** a head that reads off-size on the whole figure takes a named style factor, proposed to
  the human, applied about the head's centre in `props()` (the worked example's `HEAD_STYLE`) or with
  `b.scale_part` after the last deformer, before anything is placed on the head.
- **Keys that carry no shape:** `head.profile_key_deviation` gives each inner key's distance from its
  neighbours' line (in screen pixels with `read_mpp`). A key near zero can leave the mesh, its colour boundary
  kept by a full-key copy in a source ([markings-decals.md](markings-decals.md#the-tools-behaviour)).

## Ears

`shapes.lobe` per ear, its base seated with `shapes.cast_point` (`sink` the burial depth; `part=` names the
ear so a miss is reported for it), placed only where the cast found the skull, then `b.mirror_part`. Ears
stay parts of their own.

- `front` is the direction the ear's opening faces in the drawing, between the front and the side when both
  views show the opening. `width` runs across the cupped face, `thick` along `front`. A side ear whose
  `front` points along the side shows the front view its edge: a thin vertical spike.
- `cup` sets the inner side's concavity; `inner_col` and `tip_col` colour it. Take the inner, tip and outer
  colours from the drawing and judge the front capture: an ear the colour of the head behind it merges into
  the forehead, and the inner colour changes which animal it suggests.
- With a hair cap, decide which surface each ear grows from ([hair-fur.md](hair-fur.md#ears-and-the-tuck-ring)).
  Ears on a fur mass sit forward of where the mass starts, or it swallows them.

## Limits

- `profile_head` refuses another axis or up than -Y and +Z, an apex on the wrong side of its end key, and a
  `stop` given without `eye_height`. Keep `eye_height` below the stop key's top line, or the eyes climb onto
  the forehead and into the hair.
- Every head form closes both ends on apexes; a flat-ended head is a `shapes.profile_loft` with flat caps.
- `Builder.loft` without `axis=` stands each ring perpendicular to the path through its neighbours: a snout
  lowered under the cranium tilts its face ring, which reads as a protruding forehead. Pass `axis=` or use
  `shapes.profile_loft`.
- `snout_head`'s apex caps take their end band's colour: a mark whose edge does not follow the bands (a nose
  pad, a stripe over the skull) goes into a colour source ([markings-decals.md](markings-decals.md)).
- Chosen columns, straight lofting, finite sides and deformers leave small differences against the traced
  outline: judge the side and front captures, not every pixel.
