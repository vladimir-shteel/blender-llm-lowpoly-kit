# Eyes and face

An eye is either geometry in the body (`eyes.socket_eyes`, `head.face_decals`, `shapes.fan_decal` into a
body part) or colour layers in a colour source the bake paints into the head (`eyes.traced_eye`,
`eyes.bevel_eye`, `shapes.fan_decal` into a source builder, listed in `SOURCES` with `'mask': ('head',)`).
Cast either onto the head's surface taken after its deformers and its `edits.apply`
([head.md](head.md)).

## Measure the eye

Sample the eye's width (the iris, or the whole drawn eye) off the largest calibrated drawing of the face,
keep it in `P` and size the eye from it, not from the head: the head's dimensions do not set the drawn
eye's size. The eye's size and place in the finished face are the human's call on the captures.

## Choose geometry or colour

- **The read size first.** An eye whose outline cannot show at the read size is a flat colour region of the
  face, or left out; a mesh for it costs triangles nothing shows.
- **Colour layers** when the face island gives the eye enough texels to keep its outline (`FACE_PART`,
  `face_pred(P)` and `FACE_TEXELS` or `FACE_AREA` in the model module). A baked eye at a low density is a few
  texels and loses its outline.
- **Geometry** when it does not, or when the face must stay crisp at any density.

The bake reports an eye's width in texels for the eyes an eye form drew and the decals marked
`mark='eye'`; it does not see `head.face_decals`' eyes.

| The eye reads as | Form |
|---|---|
| Round and lidded, in a muzzled head | `eyes.socket_eyes` with `profile_head`'s or `snout_head`'s `'eye'` and `'eye_x'` |
| Drawn: an almond with a heavy liner and a wing | `eyes.traced_eye`, one source builder per layer |
| Drawn where the head turns from front to side, seen in both views | `eyes.bevel_eye` per side, or `traced_eye` with that `direction` |
| Large and bulging (an alien, a cartoon face) | `shapes.fan_decal` with a low `dome` and `mark='eye'`, a small highlight polygon above the pupil |
| Crisp features on a `human_head` | `head.face_decals` through the head's `pt` |

## Build it

```python
from lpk.core.builder import Builder
from lpk.core.shapes import fan_decal
from lpk.forms import eyes

EYE_LIFT = 0.0015


def build_eyes(b, P, h, skull):
    """Socket eyes in the body; the mouth line on the Face source (SOURCES = {'Face': {'mask': ('head',)}})."""
    eyes.socket_eyes(b, 'eyes', skull, h['eye'], h['eye_x'], P['eye_r'], 'iris', 'pupil', 'fur', mask='mask')
    face = Builder(PALETTE)
    fan_decal(face, 'face', skull, P['mouth_outline'], (0.0, 1.0, 0.0), 'mouth', lift=EYE_LIFT, mark='line')
    return {'Face': face}
```

`build_mesh(P)` returns the source builders beside the body, `(b, {'Face': face})`; each key needs its entry in
`SOURCES`, and sources later in `SOURCES` cover earlier ones in the bake.

## Socket eyes

A raised lid ring round a shallow dome reads as an eye in a socket without cutting the head's topology:
shade under the lid, a domed eye, a forward gaze. Both sides come from one call, in a part of their own.
`inset` sets how close-set and forward-looking they are; `lid`, `brow` and `mask` colour the lid ring, an
optional brow tuft and an optional dark patch. An eye whose ray misses the head is skipped and counted in
the build report's `misses`.

## Traced eyes as colour layers

One source builder per layer, listed back to front in `SOURCES`, each outline mapped from the view's trace
through its calibration (`Calib.model`) to model points in front of every surface it must reach, the
temples included; `mirror=` repeats every layer for the other eye. Each layer lies at the same lift in a
source of its own, and the bake lays later sources over earlier ones: layers stacked a fraction of a
millimetre apart in one builder cut into each other and into the head. Under the geometry stance trace the
same outlines into in-mesh decals (`shapes.fan_decal` into a body part).

## Eyes both views draw

An eye at the face's edge, near the head's top corners, sits where the head turns from its front or top to
its side. Cast along each view's own axis, the two outlines land at different places, as two eyes; cast
along the front axis alone, the eye can land on the front where the profile shows none. `eyes.bevel_eye`
casts from one `direction` (from above and outside, or from the front and outside, into the head), `along`
the head's forward axis; check that the front and the side capture show one eye in the drawn place.

## Markings round the eyes

A dark mask, a stripe over the bridge or a muzzle patch: trace each patch as its own outline on the largest
calibrated face drawing, map it through `Calib.model`, and cast it with `shapes.fan_decal` into a source from
the direction both views agree on, after the head's last change. Patches the drawing separates stay separate
outlines; a bridge between them takes the colour the drawing gives it. `socket_eyes`' `mask` is sized by the
eye: narrowing the eye shrinks it to a ring, and a large flat patch can sink into a curved skull, so only a
traced outline gives a drawn mask's shape. A mark whose edges follow the head's bands may colour the loft's
faces through its `color` function instead, but a band runs across a gap the drawing leaves between the mask
and its neighbour.

## Human faces as in-mesh decals

`head.face_decals` with each shape as `(x, height)` points in head units, listed back to front (later shapes
sit higher). Split every shape at the face plane's corner and keep its points on the face: a shape spanning
the corner tilts across the bend, and a point past it flattens the decal on the side (the docstring gives the
corner's place). A fixed expression (no facial animation) reads at decal density: narrowed eyes drop the
upper lid and clip the iris; a smile is a lip polygon under a thin dark line, one corner lifted.

## Mouth and teeth lines

Cast each guide point from in front onto the head, keep the hits, then `shapes.surface_strip` into a source:
it snaps every point to the nearest surface, and from points far in front the nearest point can lie to the
side of the drawn line. A line narrower than the face's texels bakes as dashes
([markings-decals.md](markings-decals.md#thin-lines)).

## Facial hair

A beard or a moustache is `head.face_shell` from guide rows just off the face: a shell shows its thickness at
the edges, where hair coloured onto the head's faces reads as paint. `tip` closes the last row on a point (a
goatee).

A long beard hanging below the chin is `hair.long_beard`: its root row is cast from the head's centre onto the
skull along the jaw, at the elevation `line(phi)` across `span`, and lifted by `thick` as `face_shell` lifts its
rows; below it, `stations` hang flat sections in the air down and forward to `tip`, each `(f, k)` placed `f`
of the way to the tip at `k` times `width` and `depth`. A small last `k` with the tip well past it reads as a
point, a large one close to the tip as a blunt end; `fork` splits the end into two locks (`fur.tuft`). Keep
a moustache as a `face_shell` of its own over it.

Measure: `line` from where the beard leaves the cheeks and the chin in the front and the side view (as a
hair cap's hairline); `tip` from the side view (its depth in front of the chest) and the front; `width` and
`depth` from the beard's widest under the chin in the front and the side view.

```python
from mathutils import Vector

from lpk.core import edits
from lpk.core.shapes import bvh_of
from lpk.forms import hair


def build_beard(b, P, data):
    skull = bvh_of(b, ['head'])
    hair.long_beard(b, 'beard', skull, Vector(P['head_c']), BEARD_LINE, P['beard_tip'], P['beard_w'],
                    P['beard_d'], 'beard', stations=BEARD_STATIONS, symmetric=True)
    edits.apply(b, P, 'beard', data)
```

Weight it to the head (`ALLOWED = {'beard': ['Head']}`). `long_beard` refuses (`ValueError`, naming the ring)
any band or end triangle that would collapse: stations that fall back onto the root, a tip on the last
station. Its hanging part does not see the chest: check the side capture and the test pose's nod.

## Limits

- `fan_decal` and `traced_eye` cast each outline point over a fixed reach round it (their docstrings give
  it): a point beyond that reach snaps to the nearest surface point, from far in front of a face the nose
  tip.
- `dome` is metres whatever the head's size: too high for the face it reads as goggles in profile; keep the
  outer corner on the face plane, or the outline kinks in the three-quarter view.
- In-mesh eyes and lights sit in a part no source's `mask` names: the bake paints a source over any face in
  its reach.
