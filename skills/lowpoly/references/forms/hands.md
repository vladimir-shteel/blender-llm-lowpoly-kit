# Hands

A symmetric pair is built on the left (`'hand.L'`) at the arm's wrist and copied with
`b.mirror_part('hand.L', 'hand.R')` once its `edits.apply` has run; the copy carries the left hand's edits.
A hand that differs by design (an organic hand beside a mechanical one) is built on its own side with that
side's frame. Every hand form takes the same frame, all `mathutils.Vector`s (several forms do not convert
tuples): the `wrist`, `d` (wrist to fingertips), `out` (the back of the hand; the fingers curl away from it)
and `across` (the palm's width, the thumb on its negative side).

## Measure the hand on its own crop

Read the wrist at the joint (not at the edge of a fur cuff or a sleeve, which moves the joint), the knuckles
where the fingers separate (not where the palm's outline ends), the fingertips and the palm's breadth, on
the largest calibrated drawing of the hand. Keep the palm length, the finger length and the half breadth in
`P`. A hand that reads small on the whole figure takes a named style factor in the model module (the worked
example's `HAND_STYLE`), proposed to the human and applied through the lengths you pass; skip it when the
drawing already exaggerates the hands, or when the arm was measured inside a bulky sleeve, which counts the
exaggeration twice.

## Choose the form

| The hand reads as | Form |
|---|---|
| One heavy mass, short closed fingers and claws | `hands.chunky_hand` |
| Long thin fingers ending in nails | `hands.slender_hand` |
| Long curved talons | `hands.talon_hand` |
| A mitten with a split index finger | `hands.fist_mitten` (`claws=` for claws, `finger_col=` for a fingerless glove) |
| No fingers at the read size, or more than the budget carries | a `Builder.box`, a low-sided loft closing the arm, or a local form |
| A mechanical or robot hand | `hard.mech_hand` (below) |

A heavy hand built from spread sticks costs as much and reads less like the drawing. Compare each docstring's
triangle count with the budget first. Of the library's hands only the mitten has finger bones: `bones(P)`
adds the template's mitten fingers (`Index`, `Middle`, `Thumb`) from `hands.fist_points`; every other hand
stays rigid on its hand bone.

## Build it

```python
from mathutils import Vector

from lpk.core import edits
from lpk.forms import hands, limbs

PALM_SHARE = 0.55
ACROSS = Vector((0.0, 1.0, 0.0))      # the left hand's palm width, the thumb forward


def build_hand(b, P, data):
    shoulder, elbow, wrist, d, out = limbs.arm_frame(P, 1, P['arm_rad'])    # mathutils Vectors
    length = P['hand_len']
    hands.fist_mitten(b, 'hand.L', wrist, d, out, ACROSS, 'skin',
                      length * PALM_SHARE, length * (1 - PALM_SHARE), P['hand_half_w'],
                      thick=P['hand_thick'] / P['hand_half_w'])
    edits.apply(b, P, 'hand.L', data)
    b.mirror_part('hand.L', 'hand.R')
```

`thick` is a ratio of the half breadth, not a length. Share the frame and the lengths with `bones(P)` through
a model-module helper (the worked example's `mitten_points` over `hands.fist_points`), so the rig binds the
same points the build used.

## Keep the standard rest orientation

The wrist, `d` and `out` from `limbs.arm_frame` with the side's sign, `across` along +Y for the left hand: the
back of the hand out, the palm toward the body, the thumb forward, on every model whatever the drawing shows.
Shared animations and held props then behave alike; a fanned or turned hand in the drawing is pose. A hand
built directly on the right takes the right side's frame: have the human check from three-quarter in
Blender that its thumb faces forward.

## The arm's end inside the hand

End the arm's last ring inside the hand's wrist section, flattened along `out` to the palm's thickness when
the forearm shows at the opening: a round forearm end stands out of a flatter opening such as a mitten's. The
form's docstring says where its wrist section starts and how wide and thick it is.

## Claws, finger lines and gloves

- **Talons that hook toward the thumb:** `talon_hand` with a `claw_curl` mixing the palm's direction (-`out`)
  with a share of -`across`, and thin fingers (`finger_w`) so the claws dominate; the talons then also curve
  in the plane of the fanned fingers.
- **Painted finger gaps on a mitten:** `hands.mitten_finger_lines` into a colour source masked to the hand
  parts, with the same frame and lengths as the mitten; build it for the left hand and mirror it inside the
  source's builder. Gaps are darker than the hand. A line narrower than the hand's texels resolve bakes as
  dashes (`lpk.stages.texture.MIN_LINE_TEXELS`): give the hand parts a texel boost in `BOOST`.
- **A fingerless glove:** `fist_mitten` with `finger_col`; on another form, recolour the faces past a distance
  along the arm with a model-module helper. The glove's edge is a colour boundary, not a ring.

## A mechanical hand

`hard.mech_hand`: a chamfered plate palm with its back in `back_col`, digits of a rectangular section
pinched at the middle joint. Give the first segment (`finger_col`) a light colour against a dark knuckle and
tip (`knuckle_col`) so the segments separate in a flat bake. Measure the palm's and the digits' widths off
the drawing: a thin palm with thin digits reads as a stick of tiny blocks. A hand it cannot make (digits
that bend on finger bones) is a local form. Its rigid pieces are pinned to one bone each in `FIXED` ([gear.md](gear.md#rigid-pieces)).

## Judge hands where they read

In the A-pose front view a hand is edge-on, and a posed hand hides behind the body. Capture the hand alone,
cut out of the body (posed or at rest) and framed on itself, in the three-quarter view, and show it beside
the hand's crop. The cut carries the corner colours, the UVs and the materials, so any shade works:

```python
result = {'files': run.capture(MODEL, tag='hand', views=('q34', 'front'), part='hand.L')}
```

## Limits

- `talon_hand`'s docstring gives its triangle count from `fingers` and `digit_sides`.
- An edit made on one hand of a mirrored pair is kept for the left hand only; the right is its mirror copy.
