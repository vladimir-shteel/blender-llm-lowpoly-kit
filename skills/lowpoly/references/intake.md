# Intake: from reference pictures to views.json

Intake turns the pictures into `views.json` beside the model module: one cut image per view under
`refs/`, each view's calibration and fields, the landmarks and widths read on it in its own pixels, and
the traces of its ignore regions. `props()` reads the file through `lpk.core.views.Views`
([the model file](model-file.md)). Everything but the camera fit runs on the host, with Pillow and numpy:

```
python -m lpk.host.intake crop <sheet.png> <model_dir> <scale> name=x0,y0,x1,y1 [name=...] [--alpha]
python -m lpk.host.intake grid <model_dir> <view> [step] [x0,y0,x1,y1] [--zoom Z] [--no-marks]
python -m lpk.host.intake key <sheet.png> <model_dir> x,y [x,y ...] [--radius R]
python -m lpk.host.intake seeds <sheet.png> x,y [x,y ...] [--step S] [--radius R]
python -m lpk.host.intake sample <model_dir> <view> name=x,y [name=x,y ...] [--radius R]
python -m lpk.host.intake clean <picture.png> <model_dir> [--min-px N] [--keep x0,y0,x1,y1 ...]
python -m lpk.host.intake compare <model_dir> <view> <original view>
```

Each prints JSON. Calibrations, landmarks, widths and traces are written with `lpk.intake`
(`read_views`, `update_views`, `write_views`) or by hand; `examples/mannequin/views.json` shows the
format. The order: choose the source ([choose the source](#choose-the-source-before-cleaning)), cut,
sample the palette, read the main view's crown and sole and calibrate, then read
landmarks and widths per part; a sheet on a painted, graded or gridded ground is keyed first
([key a painted ground](#key-a-painted-ground)).

## Choose the source before cleaning

Look at the sheet before any key and sort it by what stands between the reader and the figure:

| The sheet | Route |
|---|---|
| Separate figures on a flat ground | cut it as it is |
| Noise in the ground only: a gradient, a grid, compression noise | [key a painted ground](#key-a-painted-ground) |
| Clutter on or against the figure: views overlapping, text or arrows over it, sketch lines, specks and scattered marks, hatching that runs into the ground; or a key that still loses figure or leaves ground after its seeds were checked | the steps below, in order |

1. Ask the human for a cleaned picture, in the same message as
   [what to ask for](#what-to-ask-for-before-starting): each view on its own, a flat ground, no labels,
   the figure untouched, at the sheet's scale and on its ground line. Their picture becomes a source of
   its own, compared with the original as a cleaned copy is
   ([cleaned and generated pictures](#cleaned-and-generated-pictures)); the residue is cleaned, keyed and
   ignored as below.
2. When the human cannot, and the environment offers an image-generation or image-editing tool the human
   allowed, clean it there ([cleaned and generated pictures](#cleaned-and-generated-pictures)).
3. Otherwise clean with the kit's tools. `clean` removes every piece of ink under `--min-px` pixels
   (default `lpk.stages.imaging.CLEAN_MIN_PX`) that touches nothing else: specks, dots, letter fragments.
   It writes `refs/<picture>_clean.png` and a record of each piece it removed: read the boxes, and keep a
   small part of the figure drawn apart (a loose lock, a pattern's dot) with `--keep`. A mark that
   touches the figure, and anything larger, is an ignore region's; a painted ground is keyed first
   ([key a painted ground](#key-a-painted-ground)), and the keyed sheet cleaned. Each new key needs a new
   cause; a boundary still inseparable after that stays unread, and what depends on it is a named value of
   the model module with its reason, reported as a guess.

Removing specks and stray marks with one-off scripts, attempt after attempt, is no route: `clean` and the
ignore regions leave a record of what left the picture; a script leaves an outline no one can check.

## Cut the views once

- `crop` cuts one picture per view, `refs/<view>.png`, and merges its `image`, `size` and `source`
  (sheet, box, scale) into `views.json`, keeping the view's other fields. Boxes are sheet pixels, `x1`
  and `y1` exclusive; a box may reach past the sheet's edge (filled white). Leave room round each figure.
- `scale` enlarges by nearest neighbour at 1 and above, so a pixel read on the crop maps back to the
  sheet exactly; below 1 it box-filters.
- A view given as a picture of its own goes through `crop` too, its box the whole picture. Keep the given
  pictures under other names than `refs/<view>.png`.
- Cut once, before reading anything: a view cut again at another box or scale moves every pixel measured
  on it, and its landmarks, widths, traces and calibration are read again.
- A close-up on the sheet (a head, a hand) is cut as a view of its own: the largest drawing of its part,
  the one its shape, features and markings are read on.
- A swatch strip on the sheet is cut as a view with calibration `{'mode': 'none'}` to sample it.
- A view without a metric calibration (mode `none`) stops the `reference` stage: list `REFS` without it
  ([stages](running.md#stages)).

## The palette

Sample right after cutting: a warning that calls for a new ground key then costs no readings.

- `sample` takes the per-channel median of a square patch (`--radius`) round each named point, so a
  stray line pixel or speck does not tint it. Its `colours` are sRGB 0..1, the format of `PALETTE`.
- Pick each point in a flat area, away from lines and shading; a colour drawn in several flat tones (cel
  steps, a lit and a shadow side) at its lit tone: the shading belongs to the look.
- Read the warnings first. A high `ground` share: the patch reaches off the figure, move the point.
  `keyed`: a ground-key seed's tolerance reaches the colour, which then keys as ground wherever its
  outline opens: key the sheet again. `ink_refused`: the ground could not be told from the ink.
- Where a swatch strip and the figure disagree, keep one, note which beside `PALETTE`, and ask.
- `lpk.core.builder.lift_dark` raises near-blacks most, so a runtime shader's dark step still reads on
  near-black cloth; a large dark area then lands lighter than drawn: lower its sample first. Lifting is
  the human's call on the look.

## Calibrate each view

A calibration turns a view's pixels into metres; the fields per mode are `lpk.core.views.MODES`, defined
in that module's docstring.

| The picture | Mode | How |
|---|---|---|
| The main view (the front of a sheet, or a single concept) of known height | `rows` | `lpk.intake.rows_calibration(data, view, height_m)` from its `crown` and `sole` landmarks; the height runs to that crown, so put the crown where the brief's height is measured to (the top of the hair, a crest), not on an ear or horn the height leaves out |
| Another view of the same sheet, drawn at one size on one ground line | `rows_of` | `lpk.intake.rows_of_calibration(data, view, of)` from the two crops' boxes; it refuses crops cut at different scales |
| A view given as its own picture at the main view's size | `rows_of` | `row_offset_px` by hand: row `py` here is row `py + row_offset_px` there; take it from the sole (or crown) row both show |
| A zoomed crop of another view of one sheet | `crop_of` | `lpk.intake.crop_of_calibration(data, view, of)` |
| A close-up drawn apart, at its own scale | `crop_of` | by hand from two landmarks both views show, spread over the part: `zoom` is their distance here over their distance there, and `origin_px` is a point there minus the same point here divided by `zoom`; give the close-up its own `mid_px` |
| A figure of known height on the model's ground line | `scale_figure` | `figure_top_px`, `ground_px`, `figure_height_m` |
| A known length between two landmarks (a prop, a door) | `known_span` | `a`, `b`, `metres`, `ground_px`, optional `axis` |
| No scale at all | `none` | the landmarks give proportions only; the metres come from the brief, as named values in `props()` |

- When the main view's scale comes from a scale figure or a known span, calibrate it so first, read the
  character's height from it (`Views.calib(view).m` of the crown-to-sole pixels), have the human confirm
  it, then write the main view as `rows` with that height.
- Check a hand-derived `rows_of` or `crop_of` on a third landmark both views show (`Views.calib(v).z`):
  another height means the views differ in size or a landmark is misread.

The view fields the calibrations, overlays and the reference stage read:

- `mid_px`: the figure's midline column. A `rows` calibration does not apply it on its own: `props()`
  passes it (the mannequin reads `views.view('front')['mid_px']`); the other modes default to it.
- `zero_px` and `facing` (`left` or `right`) on a profile: the column of model depth 0 (over the hip
  joint) and the way the figure faces; `side(px, py)` then gives a point's depth and height. `facing`
  `back` mirrors a back view in the overlays, so the character's left lands on the viewer's left.
- `facing` `turned` on any turned view: its columns mix width and depth, so it gives heights only, and
  `lpk.stages.review.calib_fit` refuses it. `depicted_pose` and `note` are for the reader, not lpk.

```python
from lpk import intake

path = 'models/hero/views.json'
data = intake.read_views(path)
intake.update_views(data, landmarks={'front': {'crown': [338, 130], 'sole': [338, 1465]}})
intake.update_views(data, views={
    'front': {'calibration': intake.rows_calibration(data, 'front', 1.75), 'facing': 'front', 'mid_px': 338},
    'side': {'calibration': intake.rows_of_calibration(data, 'side', 'front'), 'facing': 'left', 'zero_px': 250},
})
intake.update_views(data, widths_px={'front': {'neck': 47}},
                    traces={'front_label': {'view': 'front', 'px': [[20, 20], [180, 20], [180, 60], [20, 60]]}},
                    views={'front': {'ignore': {'front_label': 'the view title, not the figure'}}})
intake.write_views(path, data)
```

`update_views` replaces a view field whole (`ignore` included), sets single landmarks and widths, and
removes an entry given as `None`.

## Read landmarks and widths on the grid

`grid` draws a view labelled in its own pixels, its landmarks as magenta crosses with their names and its
ignore regions hatched: `out/grids/<view>.png`. With a box it draws that region enlarged (give the step
before the box; `lpk.host.intake.grid` states the default step and zoom of each), labelled in the view's
pixels still, so a point read there goes into `views.json` as it is. `--no-marks` hides the crosses.

Landmarks are read by hand, part by part: decide what a landmark means on the drawing, read its pixel on
the zoomed grid of that part, write it, and draw the grid again to see the cross on the feature. Where a
value must be exact (an outline's edge on a row, a width), read it from the ink instead:

```python
from lpk.core.views import Views
from lpk.host import png
from lpk.stages import imaging

views = Views('models/hero/views.json')
regions = views.ignore('front')
picture = png.load(views.image('front'))
unread = imaging.region_labels(picture.shape, [r['px'] for r in regions.values()]) > 0
ink = imaging.ink_mask(picture, ignore=unread)
waist_row = imaging.ink_runs(ink, 'x', 415)   # [(first, last), ...]: the outline crosses at the ends
figure = imaging.figure_box(ink)              # the box round all ink (labels too: ignore them first)
```

### Joints and outlines

Joints feed bones and lengths; outline points feed widths and the silhouette. Never use an outline point
as a joint. Key names are the model's own; the ones below are the convention the mannequin uses. `.L` is
the character's left (+X): the viewer's right in a front view, the viewer's left in a back view. Read both
sides; average a pair only where the design keeps it symmetric.

### Front view (the main view)

| Key | Read at | Note |
|---|---|---|
| `crown` | the top of the skull | read the hair's top apart when the hair has volume |
| `eye.L`, `.R` | the iris's centre | read the iris's width too; never derive the eye from the head |
| `chin` | the jaw's lowest point | head height is crown to chin, unless the head is tilted |
| `collar_base` | where the neck meets the shoulders, on the midline | |
| `shoulder.L`, `.R` | the centre of the upper arm's top; on a raised arm, over the armpit, half the arm's thickness above it | not the shoulder's outline or a seam |
| `elbow`, `wrist`; `knuckle`, `fingers` | the joints' centres; the knuckle row, the longest fingertip | the wrist at the joint, not a cuff or a fur boundary |
| `armpit.L`, `.R` | the row where the arm's underside leaves the body | a welded armhole reaching below it fuses sleeve to body |
| `chest`, `waist`, `hips` | the outline at its widest, narrowest, the pelvis's widest | outline points, not joints |
| `hip.L`, `.R`; `crotch` | the leg's joint, inside the outline; the crotch on the midline | a crotch read too low shows as a seam |
| `knee`, `ankle` / `hock`, `ball` | the joints; the hock is the backward joint above a digitigrade foot | a front view's lowest toe row can be the toes' top: check the profile |
| `sole` | the lowest point | soles on different rows (a stride, a tilted camera) are a question for the human |

### Profile and back

Profile: `skull_back`, `crown`, `brow`, `eye`, `bridge`, `nose`, `lip`, `chin` (lowest), `chin_front`
(foremost), `jaw` (its angle), `throat`, `ear_root`, `ear_tip`, `hair_nape`; `neck_front`, `neck_back`;
`chest_front`, `back`, `waist_front`, `waist_back`, `belly`, `seat`, `thigh_front`, `thigh_back`;
`knee_front`, `knee_back`, `ankle` or `hock`, `heel`, `ball`, `toe`; `tail_root` and points to the tip.

- `chin` and `chin_front` tell a muzzle dropping from the nose from a jaw sloping back from the lip.
- `skull_back` and `crown` are read on the skull under hair, crest or mane; the volume's outline apart.
- A head with a snout or beak is read as traced outlines: the worked example
  [forms/snout-keys.md](forms/snout-keys.md) works one through.
- The back view shows the back of the hair, hems and seams, a tail's root, markings.

### Widths

`widths_px` holds full widths across the drawn outline, in the view's pixels: `skull`, `neck`,
`upper_arm`, `forearm`, `wrist`, `hand`, `thigh`, `knee`, `shin`, `ankle`, `foot`, `tail`, and those the
model adds (the hair's outline, the iris, the mouth).

Read a width square to the part's axis (across a limb drawn at an angle, not along the row), and a
curved part's thickness square to its own axis, never its outline's extent, which adds the curve's sweep.
A drawn outline includes fur tips and loose cloth: say which in the view's `note`.

### Hard cases

- A joint the drawing hides (a straight sleeve with no elbow): read what another view shows (a knee where
  the profile's outline breaks); otherwise place it by an anatomy proportion written as a named constant
  of the model module with its reason (a palm's share of the hand placing the knuckle row), and tell
  the human it is a guess.
- A neck drawn wider than the jaw hides the chin in the front: read its row on the profile. Arms inside
  bulky sleeves: read the joints inside, provisionally; a proportion factor on top counts the drawing's
  exaggeration twice.
- A tilted or turned head is measured along its own axis (skull back to snout tip), not crown to chin;
  a long head drawn at another scale in the front than in the profile is placed by its own crown and
  chin rows in each view. Hair: measure the skull under it and the hair's outline separately.
- A feature at two positions in two views: record both and ask which wins. Hands curled toward the
  viewer measure short; fanned hands measure wide: read across the palm.
- A colour boundary (where dark fur starts, a sock's top, a hem) is read like a joint: it becomes a ring
  position or a painted region's edge.

### Objects

A prop is read the same way, with landmark names of its own parts.

- Calibrate the main view `rows`: `crown` on the prop's top row, `sole` on the row it stands on, the
  height from the brief (`lpk.intake.rows_calibration`); or `known_span` over a length the brief gives.
- `mid_px` is the prop's centre line. A held or hung prop's pivot (the grip, the hook) is a landmark too:
  `props()` places it at the origin.
- Landmarks are the rows and points of its parts: a band's lower and upper edge, a handle's ends, a
  fitting's centre, a rim where it crosses the outline. Widths are its outline across a row. The barrel
  example reads `hoop.<k>.bottom`, `hoop.<k>.top`, a hoop's rim and the widths `base`, `bilge` and `top`.
- A round or turned prop gives every radius in one view; a boxy one takes its depths from a side view
  (`side(px, py)`).
- A smooth curve (a bulge, a taper) is read at three or more rows and fitted in `props()`, as the barrel's
  staves are a parabola through the base, the bilge and the top, not traced point by point.

## What the landmarks feed

`props()` turns them into metres: `Views.calib(view)` gives `z(py)`, `m(px_len)`, `model(px, py)` and,
on a profile, `side(px, py)`; `lpk.core.views.measure(calib, landmarks, widths_px)` packs heights,
distances, widths and spans (`examples/mannequin/mannequin.py`: heights from the front, depths from the
side, pairs averaged). They feed the joints the blocks, the build and `bones(P)` place, the forms (head
size, eyes, garment edges, limb radii), and the overlay review, which projects through the calibration
(`lpk.stages.review.calib_fit`): a wrong `mid_px`, `zero_px` or calibration shifts the whole figure.

## Ignore what the model does not need

Trace each region the ink readers should not read as a closed polygon in the view's pixels (a trace)
and name it in the view's `ignore` field with its reason: labels, arrows, frames, grid and floor lines, a
cast shadow, an overlapping view or close-up, a second figure. The grids hatch it; `sample`, the ink
reads and the outline fits leave its pixels unread.

- A part drawn in another pose than the build's (arms in a T-pose, a curled tail): trace its ink as a
  region and leave the part out of the build's side as well (`exclude_parts=` of
  `lpk.stages.review.project`, `outline_diff` and `concept_fit`), so it is left out on both sides.
- Never draw or widen a region over the figure to make a comparison look better; ask before covering
  anything the model may need. `ignore` is written whole: name every region the view keeps.

## Style factors

Measured proportions are honest to the drawing, not to how the model reads in 3D: build parts as drawn.
When a part reads off-size on the built figure, propose a factor for that part to the human; only their
answer applies it. Write an applied factor as a named constant of the model module with a one-line
reason and apply it in `props()` on top of the measurement, so the measurement itself stays honest
(`HEAD_STYLE` and `HAND_STYLE` in the mannequin). A factor on the head applies to what hangs on it (ears,
horns, hair) so they keep their proportion. A part drawn off-size on purpose (a small head on a heavy
body) is the design: propose nothing for it. Which stance to take on proportion is in
[style](style.md#proportion-and-look).

A projection correction ([turned concepts](#turned-concepts-and-the-camera)) or an anatomy fallback is no
style factor: it undoes how the picture was drawn or stands in for a joint it does not show. Keep each as
its own named constant with its reason.

## What to ask for before starting

Ask for everything missing in one message:

- a front and a side on one ground line;
- both profiles or a back view for a design that differs between its sides (a cape on one shoulder);
- the final look (clothed, with its gear) in every view, hands and feet in frame, a neutral expression;
- a close-up of a head with a snout, a beak, a mane or a helmet;
- the height, when nothing in the pictures gives the scale;
- a cleaned picture, when the sheet is cluttered ([choose the source](#choose-the-source-before-cleaning));
- when the environment offers an image-generation or image-editing tool: whether the references may be
  sent to it. Ask once per model and write the answer into the module's docstring with the brief.

A view the human cannot give (a front and a side when only a three-quarter concept exists, a back) is
generated when the tool is there and allowed ([cleaned and generated
pictures](#cleaned-and-generated-pictures)); otherwise the concept is read as a turned view
([turned concepts](#turned-concepts-and-the-camera)). A part no view shows becomes a named value in the
model module with its reason, reported as a guess.

## Cleaned and generated pictures

A picture a tool made from a reference is a source of its own: keep the original beside it, save it under
another name than `refs/<view>.png`, cut it with `crop` like any picture, and write in the view's `note`
what it was made from and with which tool.

- **A cleaned copy** keeps the original's pixels where the figure is: ask the tool for the same size and
  framing, and only the clutter removed. Before reading on it, cut the original too, as a view of its
  own (`<view>_original`, calibration `{'mode': 'none'}`, left out of `REFS`), both with the same box and
  scale (a copy the tool returned at another size scaled back to the original's first), and run
  `compare <model_dir> <view> <view>_original`. Its picture, `out/compare/<view>.png`, shows the copy's
  ink over the original's: grey where both have ink, red where only the copy does, blue where only the
  original does. Its `metrics` list each region of difference with its box: `extra` regions are ink the
  tool drew, `missing` ones ink it removed. A cleaned copy adds nothing and removes only clutter; an
  `extra` region on the figure, or a `missing` one that was part of it, means an outline that moved, a
  part redrawn or a proportion changed, and makes the copy a generated view (below), not a cleaned one.
  A copy that holds is read like the original and calibrated against the main view as any picture given
  apart ([calibrate each view](#calibrate-each-view)).
- **A generated view** (a front or a side drawn from a three-quarter concept, a back) is a new drawing of
  the design. The original concept wins: where the two disagree, follow the concept, write the
  disagreement in the view's `note` and tell the human at the next review. Accept a generated view
  yourself when it shows the design the concept shows. Calibrate it `rows` from its own crown and sole at
  the height the main view gives, and read its landmarks and widths into `views.json` like any view's;
  at the next review tell the human which measurements come from it. When the human gives a drawing of
  that view, it replaces the generated one and its readings are taken again.
- Generate one view per call from the original concept, not from another generated view, and ask for an
  orthographic view, the figure standing on the ground line at the concept's proportions: a perspective
  picture gives no exact numbers.

## Without references

A model the human describes, or designs as it goes, has no `views.json`: leave `VIEWS` out of the
model module, skip the `reference` stage and take every size from the brief as a named value of
`props()`. The reviews then compare with nothing drawn: show the step, ask the human whether anything
should change, and turn each answer into numbers in the model module.

## Limits of reading pixels

- A grid, however zoomed, presents pixels; a cross read off it by eye is not a measurement. Exact values
  come from the ink (`ink_runs`, `figure_box`) or the human's coordinates.
- The ink readers lose a line drawn in the ground's colour up to its whole width, and compression noise
  can put an edge outside the drawn one by `read_ink`'s `noise_px`.
- A keyed picture is no anatomical outline: never infer clipped anatomy, erase figure content for a
  cleaner silhouette, or derive a mask from the blocks.
- A turned view gives heights only, a perspective view no exact numbers, a `none` view proportions only.

## Less common cases

### Key a painted ground

The ink readers (`lpk.stages.imaging.read_ink`, behind the sampling, the overlays and the outline
comparisons) tell drawing from ground by the colour of the picture's border, or by its alpha when it has
transparent pixels. A painted, graded or gridded ground has no one colour and they refuse it. Key such a
sheet's ground to transparent before cutting, then cut from the keyed copy with `--alpha`:

```
python -m lpk.host.intake key refs/sheet.png <model_dir> 40,40 1900,40 980,1500
python -m lpk.host.intake crop <model_dir>/refs/sheet_keyed.png <model_dir> 1 front=40,60,720,1550 --alpha
```

`key` writes `refs/<sheet>_keyed.png` with a record of its seeds, which `sample` reads through the view's
`source`. Each point measures its colour (its patch's median) and tolerance (the ground's own grain in
its patch); the ground is every like pixel 4-connected to a point. Choose the points by the ground:

| Ground | Points |
|---|---|
| One or a few flat colours (the paper, a frame's fill) | one on each colour |
| A grid whose lines must key with the paper | points on the paper, and one on a line keyed with `--radius` below half the line's width |
| A grid whose lines may stay ink | points on the paper farther from the lines than the patch reaches; the lines stay ink, ignore regions take them where they touch the figure |
| A gradient, compression noise, a grid finer than a few patches | `seeds` from a few samples, one on each colour and along the gradient as often as it changes; its `points` go to `key` with the same radius |
| Ground a figure or frame encloses (a pocket between the legs) | one more point inside it |

`seeds` proposes one point per lattice cell (`--step`, default `lpk.stages.imaging.GROUND_STEP`) where a
clear patch of the samples' ground fits; light paint inside an outline gets none. Its `ground` share
says how much of the sheet the samples reach: a stretch left without points takes another sample.

The thin-line rule: a patch holding a line thinner than itself takes the line's contrast with the paper
as its tolerance and keys every colour within it, figure colours included where an outline opens; only a
patch of one ground colour lowers it. Keep paper points clear of the line (the line stays ink, under an
ignore region), or key with a radius below half the line's width, which applies to every point.

Look at the keyed result on a grid (`lpk.stages.imaging.grid` over `imaging.scale(imaging.crop(sheet,
box), k)` with `origin=` the box's corner and `zoom=k` labels a zoomed sheet region in sheet pixels). A
part keyed away means a point lay on the drawing (its tolerance and `pixels` stand out): move it. Ground
left as ink takes another point; labels and frames take ignore regions. Note the keyed copy in each
view's `note`. Stop when another key has no new cause; a boundary that stays inseparable is handled as
[choose the source](#choose-the-source-before-cleaning) says.

### Turned concepts and the camera

- A single three-quarter concept is the main view with `facing` `turned` and a `rows` calibration of the
  height the human confirms. Its depths are guesses, and its torso widths carry part of the depth:
  `measure(..., width_k=)` narrows the horizontal spans together (shoulders, chest, waist; narrowing the
  shoulders alone leaves the chest wider than them). One factor approximates the turn, it does not invert
  it: hold the widths against an orthographic view where there is one, a generated one included
  ([cleaned and generated pictures](#cleaned-and-generated-pictures)). A low camera shrinks the head and
  upper body and lengthens the legs.
- A concept drawn from above or below moves its heights with their depth. Once the blocks stand, fit its
  camera in Blender with `lpk.stages.review.concept_fit`: the yaw and pitch that turn the blocks to its
  outline, and how far that pitch shifts each landmark's row; take those heights from an orthographic
  view where one exists. Fit once, on the blocks: refitting to the build takes its errors into the
  camera. One fit per group of parts that turns as one (a head turned further than the body is fitted on
  its own crop). The fits are orthographic: a perspective drawing gives no exact correspondence.
  `concept_fit(Views(path), view, ['<NAME>_Blocks'], exclude_parts=[...])` returns `fit`, `pitch_limit` and
  each landmark's `shift_px` under `landmarks`.
