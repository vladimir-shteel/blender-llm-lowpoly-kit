# Running

## Bootstrap

Every `execute_blender_code` call starts with the bootstrap: Blender keeps imported modules between
calls, and the purge makes the call read the kit, the local form library `lpk_local` and the model
module from disk again.

```python
import sys
KIT = r'<path to the lowpoly-kit folder>'
if KIT not in sys.path:
    sys.path.insert(0, KIT)
for name in [n for n in sys.modules if n == 'lpk' or n.startswith(('lpk.', 'lpk_'))]:
    del sys.modules[name]
from lpk import run
MODEL = r'<model folder>/<model>.py'
result = run.model(MODEL, stages=('reference', 'blocks'))
```

Before the first heavy call on a machine, run `from lpk import setup_check` and
`result = {'next': setup_check.check()['next']}` after the bootstrap, and fix what it lists (a 3D Viewport,
Cycles, the unit scale; the voxel-heat add-on and the view transform are optional). `result` must be a
dict: the bridge rejects anything else.

## Stages

`run.STAGES` fixes the order; a call runs the ones it names in that order, whatever order it lists them
in, and raises on an unknown stage before anything runs.

| Stage | Makes |
|---|---|
| `reference` | the views of `VIEWS` as image empties beside the model, `<NAME>_Ref_<view>`; `REFS` lists the views to show (default every view with an image); a view without a metric calibration (mode `none`, a swatch strip) cannot be placed and raises, so list `REFS` without it |
| `blocks` | the shape blockout `<NAME>_Blocks` from `blocks(P)` |
| `capture_edits` | the human's vertex moves on `<NAME>` stored in the `EDITS` file (parametric mode) |
| `adopt` | the frozen mesh `<NAME>_Frozen` from the scene's mesh object `ADOPT`, with its zones |
| `freeze` | the frozen mesh `<NAME>_Frozen` from the scene's body as the human left it, with its zones ([the frozen mode](frozen.md)) |
| `unfreeze_texture` | removes the frozen texture (`<NAME>_AtlasFrozen` and the UVs stored on `<NAME>_Frozen`); only on the human's request, the hand painting is lost ([frozen texture](frozen.md#frozen-texture)) |
| `build` | the body `<NAME>` from `build_mesh(P)`, or from `<NAME>_Frozen` when `FROZEN = True`, and the colour sources `<NAME>_<source>` in the excluded collection `<NAME>_Sources` (frozen: carried onto the frozen body, `report['build']['conform']`); raises when the body was edited since the kit wrote it (`discard_edits=True` rebuilds over it) |
| `unwrap` | the atlas UVs, not packed; refuses when `TEXTURE_FROZEN = True` |
| `pack` | one pack of the atlas; repeat it; refuses when `TEXTURE_FROZEN = True` |
| `bake` | the atlas image `<NAME>_Atlas`, saved as `out/<NAME>_Atlas.png`; with `TEXTURE_FROZEN = True` the frozen atlas with only the `'over'` sources baked over it (`discard_edits=True` bakes over an atlas painted by hand since) |
| `freeze_texture` | the frozen texture from the body's UVs and `<NAME>_Atlas` as they stand, hand edits included: the UVs on `<NAME>_Frozen`, the image `<NAME>_AtlasFrozen` packed in the `.blend` (`FROZEN = True` only) |
| `rig` | the armature `<NAME>_Rig` and the body's weights (a model with `SKELETON`) |
| `preview` | the atlas shown on the body in the `PREVIEW` look |
| `pose_test`, `pose_rest` | the rig in `TEST_POSE`, back at rest |
| `export` | one file per `EXPORTS` profile, re-imported and compared; without `SKELETON` the body alone; run only when the human asks for an export |

`run.model` returns `{stage: its report}`; `pack` gives a list, one report per pack. Return the few values
you need in `result`, not whole reports: a response has a size limit.

## Splitting calls

One call must finish within the bridge's limit (about a minute for the Blender MCP bridge). A build with
its unwrap fits one call, and so do the bake, rig and preview. A pack on a full body takes a large share of
the limit: list a few per call and repeat the call until a pack reports `settled`. A long stage is split
by naming it in several calls:

```python
run.model(MODEL, stages=('build', 'unwrap', 'pack'))
run.model(MODEL, stages=('pack',) * 4)       # repeat until a pack reports settled
run.model(MODEL, stages=('bake', 'rig', 'preview'))
run.model(MODEL, stages=('export',))
```

Listed packs stop at the first one that reports `settled` ([how packs settle](atlas.md#how-packs-settle)).
After a call that only unwraps, the first pack call takes `rescale=False`
(`run.model(MODEL, stages=('pack',) * 4, rescale=False)`). A determinism comparison runs without the pack
cache `out/<NAME>.pack.json`.

`bake` bakes on the UVs as they stand: it does not check that the packs settled, so read the last pack's
`settled` before baking.

Every call rebuilds what it names and keeps nothing else: after editing the model module, run the stages
from the first one the edit changes. `build` removes `<NAME>_Rig` (the new body is not bound to it), so a
build is followed by `unwrap`, the packs, `bake` and, for a rigged model, `rig` again before an export.

## Review calls

- `run.capture(MODEL, tag='build', shade='color')`: PNGs of the body in the front, side, three-quarter and
  back views, `out/captures/<tag>_<view>.png`; `objects=['<NAME>_Blocks']` for the blockout,
  `shade='tex'` for the atlas after the bake, `shade='material'` for the `preview` look. `objects` are whole
  objects; `part='head'` cuts one part out of the (posed) body with `lpk.stages.review.isolate`, frames it
  alone as `out/captures/<tag>_<part>_<view>.png` and removes the copy
  ([hands](forms/hands.md#judge-hands-where-they-read)). Needs Blender's user interface (no OpenGL render in
  background mode).
- The frozen body: `run.zones` reports it by part; `run.select`, `run.assign` and `run.paint` change a
  part or a colour over the human's selection ([fixing a zone](frozen.md#fixing-a-zone));
  `run.transform`, `run.replace`, `run.decimate`, `run.subdivide` and `run.smooth` change a whole part
  ([operations on a part](frozen.md#operations-on-a-part)); `run.check_uvs` and `run.repair_uvs` find and
  repair UVs an edit broke ([mesh edits under a frozen texture](frozen.md#mesh-edits-under-a-frozen-texture)).
- `run.poses(MODEL)`: the rigged body in the review poses and `TEST_POSE` on one sheet.
- `run.joins(MODEL, pose='test')`: how a pose stretches each of `JOINS`
  ([reading the joins](weights.md#reading-the-poses-and-the-joins)).
- The overlay of the build on a reference view: `lpk.stages.review.calib_fit` or `view_fit`, then
  `lpk.stages.review.project` to a JSON, then `python -m lpk.host.overlay` on the host. Over the same fit
  `lpk.stages.review.outline_diff` gives where the build's outline leaves the drawing's, in pixels.
- Contact sheets of captures beside the references: `python -m lpk.host.sheets`.

## Host commands

Intake and sheets run on plain Python with numpy and Pillow, outside Blender: `python -m lpk.host.intake`
(crop, grid, key, seeds, sample, clean, compare), `python -m lpk.host.sheets`, `python -m lpk.host.overlay`. The
[intake card](intake.md) gives their use.
