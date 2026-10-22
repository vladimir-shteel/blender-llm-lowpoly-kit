# lowpoly-kit architecture

This document fixes the structure of `lpk`: its layers, the model module contract, the runner, what the
kit keeps between calls, the one place for each kind of extension, the invariants, and the procedure by
which the structure itself may change. Every change to `lpk/`, `lpk_dev/`, `dev/` or `tests/` either fits this
document or amends it first ([Changing the architecture](#changing-the-architecture)).

Precedence: [AGENTS.md](AGENTS.md) rules come first, this document second,
[CONTRIBUTING.md](CONTRIBUTING.md) mechanics (docstrings, scrub, tests) third.

A name marked *(planned)* does not exist yet and is binding: a change that introduces the role uses that name
or amends this document; none is planned at present. [Transition](#transition) lists the current code that
does not follow the rules yet, or has not run where it must; do not copy its patterns.

## Shape of the system

- A **model module** is one Python file per model, a character or a prop: data and composition only
  (measurements, blocks, the mesh built from library forms, colour sources, atlas settings, seam rules,
  the bones and the test pose of a rigged model, export targets). Its reference views, hand-edit file and outputs sit next to it.
- The **runner** (`lpk.run`) loads a model module and runs the stages a call names, in fixed order, and
  returns a plain dict report. It holds no state: every call rebuilds what its stages name.
- **Tools** do the work: the builder and shape operations, the form library, texture, rig, pose,
  preview, export, captures, contact sheets, overlay, join and mesh reports. Each takes plain arguments
  and returns plain data; each is callable without a model module.
- **Host commands** (`lpk.host`) are command lines over the pure tools on plain Python: intake (crop,
  grid, ground key and seeds, colour samples, cleaning, comparing a copy with its original), contact
  sheets and the overlay.
- **Skills** carry the workflow in prose: what to run, in what order, and what the human looks at.
  Review is conversational: the human looks and answers in the conversation; nothing in code holds a
  stage for an answer or records an approval.
- **Development tools** stay outside the kit a user runs: `lpk_dev` (the fingerprints, imported inside
  Blender), `dev/` (host scripts such as the scrub) and `tests/` (the host tests). Nothing in `lpk` imports
  them, and `.gitattributes` marks them `export-ignore`, so `git archive` and release archives leave them
  out.

## Runtime

- Blender code runs inside one bridge call. Each call starts with the bootstrap the docstring of
  `lpk/__init__.py` gives, which removes `lpk`, its submodules and every `lpk_*` package (the local
  library `lpk_local`, `lpk_dev`) from `sys.modules`, so edits on disk are read again; nothing survives a
  call except `bpy.data` and files. The runner reads the model module from disk on every call
  (`run.load`).
- One call stays within the bridge limit. A long stage is split by naming it in several calls (`pack`
  repeats until the face island converges); the runner never resumes a half-run stage.
- Host Python runs the pure layer with the standard library and numpy. Host code never imports `bpy`,
  `bmesh` or `mathutils`.
- Host commands use Pillow for PNG input and output only (`lpk.host.png`, imported when a file is read or
  written); every image operation they run is the L0 implementation. Inside Blender, PNG input and output
  go through `stages.view`. L0 decodes no image file; it reads and writes JSON only, and reads a PNG's
  size from its header (`core.views.image_size`).

## Layers

| Layer | Contents | May import | Runtime |
|---|---|---|---|
| L0 Pure tools and data | calibration and views reader (`core.views`), section kernel (`core.sections`), skeleton templates (`skeletons`), export profiles (`profiles`), image tools on arrays (`stages.imaging`), mask metrics (`stages.numerical`), intake on arrays and views.json dicts: crop, grids, calibrations, colour samples, comparing a copy with its original (`intake`) | stdlib, numpy, L0 | host and Blender |
| L1 Kernels | `core.builder`, `core.shapes`, `core.edits`, `stages.checks`, `stages.view` | L0, L1 | Blender |
| L2 Forms | `forms.*` | L0–L2 | Blender |
| L3 Stage tools | `stages.texture`, `stages.rig`, `stages.pose`, `stages.preview`, `stages.export`, `stages.review`, `stages.reference`, `stages.blocks`, `stages.zones` | L0–L3 | Blender |
| L4 Runner and entry points | the `lpk` package bootstrap, the runner (`run`), the Blender setup check (`setup_check`) | any layer | Blender |
| L4 Host commands | `lpk.host`: the commands and their PNG reader (`host.png`) | L0, `lpk.host` | host |

Rules:

1. A module imports only from the layers its row allows, at module level and inside functions alike.
2. No module imports or calls a name that starts with `_` from another module. A helper needed elsewhere
   becomes public in its owning module, with a docstring.
3. L0–L3 functions take plain arguments: object names, numbers, strings, lists, dicts, builders, and
   callables the model module passes (`sheet_of`, `face_pred`). They never load or read a model module.
4. L0–L3 functions return plain data: numbers, lists, dicts of them, file paths. They never return a
   verdict: no pass/fail rows, check ids, severity classes or prose that decides for the human. A tool may
   raise on input it cannot work with; a measurement is reported, not judged.
5. L0 imports no Blender module, at module level or in a function.
6. `importlib`, `exec`, `eval`, `__import__` and `globals()` lookups, and a computed `getattr` on an `lpk`
   module, appear only in the runner (`lpk.run`), to load a model module.
7. A module is not split for size alone.
8. Local forms (`lpk_local.forms.<model>.<area>`, at the kit's root, ignored by git) are forms outside
   `lpk`: they import L0–L2 and the other forms of their model's package, and follow rules 2–6 like the
   kit's forms. No `lpk` module imports `lpk_local`, at module level, in a function or dynamically; a
   model module may import the kit and its own package.
9. No `lpk` module imports the development tools `lpk_dev`, at module level, in a function or
   dynamically: the kit runs without them ([Shape of the system](#shape-of-the-system)).

## The runner

`lpk.run.model(path, stages=(...), **options)` loads the model module at `path` and runs the named
stages. `run.STAGES` is the only list of stage names and fixes their order:

`reference`, `blocks`, `capture_edits`, `adopt`, `freeze`, `unfreeze_texture`, `build`, `unwrap`, `pack`,
`bake`, `freeze_texture`, `rig`, `preview`, `pose_test`, `pose_rest`, `export`.

- An unknown stage or option raises before anything runs. Only `pack` may be listed several times (any
  other repeat raises): it runs up to that many packs and stops after the first rescaling pack that
  settles the face island; without a face island the first pack is final.
- The runner evaluates `P = props()` once, only when a named stage needs measurements (`run.MEASURED`),
  and adds the stored hand edits as `P['edits']`.
- Each stage but `pack` is one function of the runner (`run.RUNNERS`) that calls tools with the model
  module's attributes and stores its report under the stage's name; `pack` runs through `run.packs` and
  stores a list, one report per pack, each with `'settled'`.
- The options of `model` (`run.OPTIONS`) each reach the stages that take them: `rescale` (the first
  pack's rescale; the first pack after an `unwrap` in the same call never rescales the face island, so it
  applies only to a call that packs without unwrapping), `backend` (the weights backend of `rig`, over the model's
  `WEIGHTS`) and `discard_edits` (`build` and `bake` over the build stamp, [Build modes](#build-modes)).
- The runner keeps nothing between calls. A stage that needs another
  stage's output reads it from the scene by object name and raises with the missing name when it is
  absent.
- Review calls are functions of the runner beside `model` (`capture`, `poses`, `joins`, `zones`, `select`,
  `assign`, `paint`, the zone operations `transform`, `replace`, `decimate`, `subdivide`, `smooth`, and
  the UV calls `check_uvs` and `repair_uvs`): they take a model path and arguments, read the model module
  again, and return the paths and numbers they made. `run.dumps` gives a report as JSON text for the
  bridge's reply. Contact sheets and the overlay are the review tools' and host commands' own functions.

### Build modes

A model builds in one of two mesh modes, chosen by its `FROZEN` attribute, and keeps its texture in one
of two texture modes, chosen by its `TEXTURE_FROZEN` attribute. The two axes are independent except that
a frozen texture needs the frozen mesh; each is switched only on the human's request.

- **Parametric** (`FROZEN` absent or False): `build` makes the body from `build_mesh(P)`. The human may
  move vertices (stored by `capture_edits` and replayed by every build) and never changes the topology.
- **Frozen** (`FROZEN = True`): `build` copies the frozen mesh `<NAME>_Frozen`, held in the open `.blend`,
  into the body; `build_mesh` makes only the colour sources, which `build` then carries from the
  parametric body they were built on onto the frozen body by the nearest surface, part by part
  (`zones.conform_sources`), so a painted layer follows a reshaped part. The human may change the topology
  freely.
  `freeze` snapshots the scene's body into `<NAME>_Frozen`; `adopt` makes it from another mesh in the
  scene (`ADOPT`), a model that exists already. Every stage after `build` reads the body as it stands and
  works the same in both modes.
- **Zones travel with the mesh.** The frozen mesh carries the zone layers every later stage reads: the
  part of each vertex (`part`), the palette colour of each face (`pal`), the joins' hole loops
  (`join_loop`), and the object's `parts`, `palette` and painted marks. Blender interpolates integer
  attributes through topology operators, so `freeze` never trusts them on a mesh whose topology changed
  since its stamp: it transfers the zones from the snapshot it replaces (on the first freeze, the
  parametric body as built) by the nearest surface, and reports the vertices it placed far from that
  surface. `adopt` takes the zones from vertex groups or materials named like the parts, else from the
  nearest block of `blocks(P)`.
- **The build stamp guards hand edits.** Every stage that writes the body (the build stamp's row in [What
  the kit keeps between calls](#what-the-kit-keeps-between-calls)) writes on it the topology key and the
  position digest of what it holds. A `build` that finds the body's
  topology changed since raises (parametric: run `freeze` to keep the edit; frozen: run `freeze` to store
  it), one that finds vertices moved since raises until `capture_edits` (parametric) or `freeze` (frozen)
  stores them, which updates the stamp, and one that finds a body without a stamp raises, since the kit
  did not write it; option `discard_edits=True` rebuilds over them. The stamp also holds the digest of the
  body's UVs (`unwrap` and `pack` drop it: their UVs are the kit's), and the bake stamps the atlas image
  with the digest of its texels; under a frozen texture a `build` over UVs edited since, or a `bake` over
  an atlas painted since, raises until `freeze_texture` stores the edit (or `discard_edits=True`). The
  stamp decides nothing else.
- **Zone tools** (`stages.zones`) read and change the body by part: a summary per part (counts, bounds,
  neighbours and border lengths, mirror twin, deviation from a reference), a part selected for the human
  to edit, a selection assigned to a part or painted a palette colour, and operations on a whole part; a
  part's capture is `run.capture` with `part`, over `stages.review.isolate`. An operation runs only in the
  frozen mode, changes the body and stores it as the frozen mesh with the zones it wrote, stamped, in the
  same call.
- **Procedural texture** (`TEXTURE_FROZEN` absent or False): `unwrap`, `pack` and `bake` make the UVs and
  the atlas `<NAME>_Atlas` again on every run, from the body's palette colours and every colour source.
- **Frozen texture** (`TEXTURE_FROZEN = True`, valid only with `FROZEN = True`): the body's UV layer and
  the atlas image are held in the `.blend` and kept. `freeze_texture` stores the body's UV layer
  (`stages.texture.UV_LAYER`) on `<NAME>_Frozen` and a copy of the atlas `<NAME>_Atlas` as the image
  `<NAME>_AtlasFrozen`, packed into the `.blend` with a fake user, both as they stand: hand edits made in
  Blender (Texture Paint, UV editing) are what is stored. `build` brings the UVs back with the frozen
  mesh; `unwrap` and `pack` refuse; `bake` starts from `<NAME>_AtlasFrozen` each time and composites over
  it only the colour sources whose `SOURCES` entry sets `'over': True`, each where its bake rays hit and
  in the bake margin round those texels outside every island, writing `<NAME>_Atlas`: every other texel
  keeps the frozen image's value exactly. The agent only adds on top: it never rewrites the frozen UVs or
  a texel a new source does not reach, except through the UV repair below. `adopt` of a mesh with a UV map
  and an image on its material's Base Color stores both as the frozen texture and takes each face's
  palette colour from that image.
- **Unfreezing the texture** is the stage `unfreeze_texture`, run only on the human's request: it removes
  `<NAME>_AtlasFrozen` and the stored UV layer, and its report says that the hand edits to the atlas and
  the UVs are lost; the next `unwrap`, `pack` and `bake` make them from the model again once the module
  drops `TEXTURE_FROZEN`.
- **Mesh edits under a frozen texture** are not refused. `freeze` and the zone operations store the body's
  UV layer with the frozen mesh while `TEXTURE_FROZEN` is set, as Blender's operators left it; while a
  frozen texture is stored and the module's texture is procedural they refuse, since the body's UVs are
  then the unwrap's.
- **The UV check** (`check_uvs`, and `'uv_check'` in the reports of `freeze`, the zone operations and the
  frozen-texture `build` and `bake`) reads the body's UVs on the atlas and lists per part the faces whose
  UVs are broken, with the reason: no UV area, a corner outside the atlas, an overlap with an island of
  another part, a texel density far from its neighbours'. The limits are named constants of the kit; the
  check reports, it decides nothing.
- **The UV repair** (`repair_uvs`, on the human's request, frozen texture only) unwraps only the faces
  the check lists as new islands at their part's texel density and places them in free atlas space,
  found on an occupancy map of every other island and its bake margin, so no existing island moves. It
  bakes only those faces (their palette colours and every colour source within its mask that reaches
  them) into the frozen atlas and the atlas `<NAME>_Atlas`, writing no texel outside the new islands'
  cells, then stores the UVs and the image as `freeze_texture` does and stamps the body and the atlas.
  When the free space cannot hold every new island it changes nothing, and its report says so and names
  the way out: `unfreeze_texture`, on the human's word.

## Model module contract

A model module is one Python file; its paths are relative to its folder, and its outputs go to `out/`
beside it. It defines, by stage and review call:

| Stage or review call | Reads |
|---|---|
| every stage and review call | `NAME` (objects are `<NAME>`, `<NAME>_<source>`, `<NAME>_Blocks`, `<NAME>_Rig`, `<NAME>_Ref_<view>`; the images `<NAME>_Atlas` and `<NAME>_AtlasFrozen`; the collection is `<NAME>`, and the colour sources `<NAME>_<source>` sit in its child collection `<NAME>_Sources`, excluded from the view layer and never exported) |
| `blocks`, `build`, `adopt`, `bake`; `paint`, `replace`, `repair_uvs` | `PALETTE` ({name: sRGB}) |
| `reference` | `VIEWS` (the views.json); optional `REFS` (the views to show, default every view with an image) |
| measurements (`blocks`, `capture_edits`, `adopt`, `freeze`, `build`, `unwrap`, `pack`, `bake`, `rig`; `zones` with a parametric reference, `replace`) | `props()`: measurements in metres, a dict; it may read `VIEWS` through `core.views`. The runner adds `P['edits']`, the stored hand edits of the file `EDITS` names ({} without `EDITS`) |
| `blocks` | `blocks(P)`: a list of `(kind, part, colour, args)`; kinds `box`, `wedge`, `ellipsoid`, `tube`, `loft`, `profile` (`stages.blocks`) |
| `capture_edits`, `build`; `freeze` of a topology edited since the stamp while no frozen mesh exists; `zones` with a parametric reference, `replace` | `build_mesh(P)` → `(body builder, {source: builder})` with a builder for every `SOURCES` key, each part passed to `core.edits.apply` with `P['edits']` right after it is made (frozen: only the sources are used, and a model without sources needs no `build_mesh`); `EDITS`: the hand-edit file (`capture_edits` needs it; parametric mode only) |
| `build` | optional `SOURCES` (the colour sources it writes, each carried onto the frozen body unless its entry sets `'conform': False`) |
| `adopt`, `freeze`, `build`, `capture_edits`, `freeze_texture`; the zone operations | optional `FROZEN` (True: the frozen mode; `capture_edits` refuses it, `freeze_texture` and the zone operations need it); `adopt` reads `ADOPT` (the name of the mesh object to adopt), the part names its vertex groups and materials may carry from `blocks(P)`, the `SKELETON` template's binding, `ALLOWED`, `FIXED` and `JOINS` (each optional), and `blocks(P)` for the parts they do not give |
| `build`, `unwrap`, `pack`, `bake`, `adopt`, `freeze`, `freeze_texture`, `unfreeze_texture`; the zone operations, `repair_uvs` | optional `TEXTURE_FROZEN` (True: the frozen texture; raises unless `FROZEN = True`); `repair_uvs` needs it |
| `unwrap`, `pack`, `bake` | `sheet_of(colour, part)`, `ATLAS` (`(size, {group: density})`); optional `FACE_PART`, `face_pred(P)`, `STRIPS`, `OWN` |
| `unwrap` | optional `seams(P)` (`{'cuts', 'panels', 'hard'}`), `BOOST` |
| `pack` | optional `FACE_AREA` or `FACE_TEXELS` |
| `bake` | optional `SOURCES` (below), `MATERIAL`, `GRIT` (the print grit colour, None for flat colours); the frozen-texture bake reads only `SOURCES`, `OWN`, `MATERIAL` and `GRIT` |
| `rig` | `SKELETON` (template name), `bones(P)` (`{bone: (head, tail)}` in metres); optional `EXTRA_BONES`, `ALLOWED` (bones per part over the template's binding), `FIXED`, `JOINS` (`[(parent, child, caps)]`), `WEIGHTS` (backend), `EXPORTS` (the influence limit, below); `'{s}'` expands per side |
| `preview` | optional `PREVIEW` (look) |
| `pose_test` | `TEST_POSE` |
| `poses` | optional `TEST_POSE` (the pose `'test'`) |
| `joins` | `JOINS`, `SKELETON`; `TEST_POSE` for the pose `'test'`, its default |
| `check_uvs`, and the `'uv_check'` of other stages | optional `OWN` (its parts left out), `ATLAS`'s size while the scene holds no atlas image |
| `repair_uvs` | optional `SOURCES`, `OWN` and `GRIT` as the frozen-texture bake reads them |
| `export` | `EXPORTS` (profile names or JSON paths); optional `EXPORT_DIR` (default `out/`); optional `SKELETON`: with it the body goes out with the rig `<NAME>_Rig`, whose influence limit is the smallest of the profiles', without it the body alone, the profiles' skeleton keys acting on no bone |

`SOURCES` is `{source: entry}` in bake order, a later source covering an earlier one. An entry's keys:

| Key | Meaning |
|---|---|
| `mask` | the parts the source paints |
| `cage`, `ray` | its bake reach, in metres |
| `conform` | False: the frozen mode keeps the source where `build_mesh` put it |
| `over` | True: the frozen-texture bake composites it over the frozen atlas |

A missing attribute raises when a stage that reads it runs, naming the attribute. A budget (triangles,
atlas size) is prose in the module's docstring or the brief; no code checks it.

## What the kit keeps between calls

| Item | Written by | Where | Notes |
|---|---|---|---|
| Model module, `views.json`, reference images | the author (the agent), `intake` | beside the model module | the inputs |
| Local forms | the agent | `lpk_local/forms/<model>/<area>.py` at the kit's root, ignored by git | every form this user's models need beyond the shared library, in the package of the model that first used it; read again by every call's bootstrap; inside the kit's folder, so lost with it unless the user keeps it |
| Hand edits | `capture_edits` (`core.edits`) | the file `EDITS` names | per-vertex offsets per part with a topology key (parametric mode) |
| Frozen mesh | `freeze`, `adopt`, the zone operations | the mesh `<NAME>_Frozen` in the open `.blend`, with a fake user | the body of the frozen mode with its zone layers; kept when the `.blend` is saved |
| Frozen texture | `freeze_texture`, `adopt`, `repair_uvs`; the UV layer also by `freeze` and the zone operations under a frozen texture; removed by `unfreeze_texture` | the UV layer `UVMap` on the mesh `<NAME>_Frozen` and the image `<NAME>_AtlasFrozen`, packed into the open `.blend` with a fake user | the UVs and atlas of the frozen texture, hand edits included; kept when the `.blend` is saved |
| Build stamp | `build`, `freeze`, `capture_edits`, `freeze_texture`, `bake`, `repair_uvs`, the zone operations (`unwrap` and `pack` drop its UV digest) | properties of the body object and of the image `<NAME>_Atlas` | the topology key, position digest and UV digest of what the kit last wrote on the body, the texel digest of the atlas it last wrote; read only to refuse overwriting hand edits |
| Scene objects | the stages | the open `.blend` | named `<NAME>` or `<NAME>_*` |
| Captures, sheets, overlays, baked atlas, atlas preview | the tools that make them | `out/` beside the model module | outputs |
| Pack cache | `stages.texture` | `out/<NAME>.pack.json` | a speed-up keyed by the unwrap and the pack settings; deleting it changes only the time a pack takes |
| Exports | `stages.export` | `EXPORT_DIR` or `out/` | `<NAME>_<profile>` |

Nothing else is persisted. JSON is written UTF-8 with LF line ends and sorted keys where order carries no
meaning.

## Where forms live

- **The model module holds composition.** Code that places vertices or faces itself (`Builder.vert` and
  `Builder.face`, ring points it computes) is a form. Code that only passes the model's values to the
  kit's functions or its package's forms, rings they return included, is composition and stays in the
  module.
- **Every form the shared library lacks is local, by model.** It is written at once in the package of
  the model that first uses it, `lpk_local/forms/<model>/<area>.py` at the kit's root, ignored by git,
  where `<model>` is the model module's file name without `.py`, a Python identifier. The package is this
  model's alone and no module `lpk_local/forms/<model>.py` exists; when either name is taken, the agent
  asks the human to rename the model file.
- **A model's forms change only for that model.** A model and its package import the kit and that
  package only ([Layers](#layers), rule 8). A form another model already has is copied into this model's
  package and changed there as this model needs, without asking: the agent cannot know which models on
  the user's disk import a form, so a shared local form would change models no one looks at.
- **Similar forms across packages are the signal for one shared form.** The agent points them out and
  proposes the merge; the move into `lpk/forms/<area>.py` is the human's decision, on the user's copy of
  the kit, and reaches the kit's repository through the maintainer's review
  ([Extending the kit](#extending-the-kit)).

## Extending the kit

| Extension | Place | Also required |
|---|---|---|
| Form | a public function in the package of the model that first uses it, `lpk_local/forms/<model>/<area>.py` ([Where forms live](#where-forms-live)) | a docstring like the shared forms' |
| Shared form, on the human's request | `lpk/forms/<area>.py`, moved there from the local library, similar forms of several models merged into one | a docstring, its entry in the forms catalogue, a host test when it has pure parts; the models the human names import it from there |
| Shape operation | a public function in `core.shapes` | a test |
| Stage | one name in `run.STAGES` and one function in the runner (`run.RUNNERS`; `run.MEASURED` when it reads `P`), over a tool in L3 | the model attributes it reads in [Model module contract](#model-module-contract); skill lines |
| Tool option | a parameter of the tool, with a neutral default | docstring with units |
| Weights backend | one entry of the backend table in `stages.rig` | a test of the pure parts |
| Export profile, skeleton template | one JSON file that passes its loader | loader test |
| Host command | one command in `lpk.host` over an L0 tool | no second implementation of the tool |

A new kind of extension, or a second place for an existing kind, is an architecture change.

## Changing a contract

1. Add a parameter only for a new, independent dimension of the same operation that callers choose per
   call, with a neutral default that is the documented normal behaviour.
2. Replace the contract instead of adding to it when the new behaviour is the better default, when an
   option would select between two algorithms for the same result, or when the old behaviour would stay
   only to keep earlier output unchanged.
3. No parallel route. A replacement removes the old route, its tests, its documentation and its teaching
   in the same pull request.
4. One pull request lands the whole contract: code, skills, example and tests.
5. Verification follows [Verifying a change](CONTRIBUTING.md#verifying-a-change): same-version
   determinism is strict; earlier outputs are diagnostics, not pass/fail.

## Changing the architecture

A change alters the architecture when it needs a new layer or dependency direction, a new kind of state
kept between calls, a new kind of extension, a process-global, an entry point outside L4, or a second way
to do a job this document assigns. Then:

1. Change this document first, in its own commit: edit the sections the change touches so they state
   the new rules as the current ones. The document keeps no record of the rules it replaced; the commit
   message gives the rule replaced, why the existing mechanism cannot serve, and how existing code
   migrates.
2. Update `tests/test_architecture.py` and its baseline in the same commit.
3. Implement the change and migrate every instance in the same pull request; the old mechanism is
   removed, not kept beside the new one. What cannot migrate in it is listed under
   [Transition](#transition) until it does.
4. A reviewer who did not write the change (a human, or an agent in a session of its own) checks the
   architecture commit and the diff against this document before the merge.
5. The pull request states the consequence for the human in plain language.

## Invariants

- **Determinism.** The same model module, inputs, kit version and environment give the same vertex
  order, UVs, weights, images and export bytes. Every random choice is seeded; no geometry is iterated in
  hash order.
- **Scene safety.** The kit creates and replaces only objects named `<NAME>` or `<NAME>_*` of the model
  it runs, in its collection `<NAME>` and the child collection `<NAME>_Sources`, and temporary data the
  same call removes (the export's re-import collection `lpk_reimport`, working images and proxies).
- **Edit safety.** No stage overwrites a hand edit it has not stored ([Build modes](#build-modes), the
  build stamp). In parametric mode `build_mesh` replays stored vertex moves through `core.edits.apply`
  right after making each part, and a stored edit whose topology key no longer matches its part stops the
  build, naming the part. Under a frozen texture the only rewrite of the stored UVs and texels is
  `repair_uvs`, on the human's request.
- **Review in the conversation.** No code waits for, records or infers a human approval; a successful
  build is not an approval.
- **Data, not verdicts.** Tools measure and report; the skills say what to look at; the human decides.
- **Units and axes.** Metres, Z up, models face -Y, `.L` is +X. Builders carry a face palette index
  (`pal`) and a vertex part index (`part`); `finish` triangulates and writes them to the object.
- **Host and Blender.** The pure layer stays host-importable; Blender reads sit in thin functions.
- **Encoding.** Files are written with LF line endings and UTF-8.
- **Neutral names.** The kit carries no names from the projects it came from.

## Anti-patterns

| Anti-pattern | Recognise it by |
|---|---|
| A verdict in a tool | pass/fail rows, check ids, severity classes, thresholds that decide instead of reporting |
| State between calls | receipts, freshness flags, digests compared to decide what to rebuild, run journals, continuations (the build stamp only refuses to overwrite hand edits; the frozen texture is the human's work, not a cache; the pack cache memoises a pure step keyed by all its inputs) |
| A gate in code | a stage that refuses to run until a human answer is recorded |
| Restating the stage list | a literal list of stage names outside `run.STAGES` |
| Reaching into another module | `other._name` across modules |
| Hidden upward import | a function-local import of a higher layer |
| Synthesised argument | building a fake report or record to call a function |
| Process-global for convenience | a module or class attribute set during a call to reach state |
| Duplicate kernel | a second implementation of a crop, pose setter, frame transport, model loader or digest |
| Name heuristics for semantics | deciding a part's or bone's role from its spelling |
| Output preservation | a parameter or branch that only keeps earlier output unchanged |

## Conformance checks

`tests/test_architecture.py` with `tests/architecture_baseline.json` runs on the host Python. It parses
`lpk/` with `ast` and imports modules only in the subprocesses of the host check. The baseline lists the
permitted exceptions, each keyed by rule, module and name, never by line number, with its count of sites.
The test fails when an exception the baseline lacks appears or a count grows, and when the baseline holds
an entry or a count above what the code holds, until `python tests/test_architecture.py --prune` removes
or lowers it; `--prune` never adds. It also fails while the baseline holds more than its version committed
at HEAD. `--record` writes the baseline from the findings and is refused when that would exceed HEAD's.

1. **Layers** (`layers`). Every `lpk` module has a layer; a module without one fails outright. A package whose
   `__init__.py` holds at most a docstring has no layer of its own: importing it counts as importing its
   highest-layer submodule. Imports, module-level and function-local, relative ones resolved, follow
   [Layers](#layers) rule 1; in a scope that calls `importlib.import_module` or `__import__`, a string
   naming an `lpk` module counts as an import of it. L0 imports nothing outside the standard library and
   numpy.
2. **Host-importability** (`host`). L0 modules and `lpk.host` commands import in a subprocess whose import hook
   refuses `bpy`, `bmesh` and `mathutils`, and contain no import of them.
3. **Private access** (`private`). No `from lpk.x import _name` and no `name._private` through a name bound to another
   `lpk` module. Dunder names are public.
4. **Dynamic loading** (`dynamic`). Calls into `importlib`, `exec`, `eval`, `__import__` and `globals()`, and a computed
   `getattr` on an `lpk` module, appear only in the runner.
5. **Local library** (`local`). No `lpk` module imports `lpk_local`: no `import` or `from` of it, at module level or
   in a function, and no string naming it in a scope that calls `importlib.import_module` or
   `__import__`. `lpk_local` itself is not in the tree and is not scanned.
6. **Development tools** (`dev`). [Layers](#layers) rule 9: no `lpk` module imports `lpk_dev`, in the same
   forms as `local`. `lpk_dev` itself is not scanned.

No check holds the rest, which review holds: [Layers](#layers) rules 3, 4 and 7; rule 8's local forms
(`lpk_local` is not in the tree), including a model or a local form importing another model's package;
"Nothing else is persisted" ([What the kit keeps between calls](#what-the-kit-keeps-between-calls)); the
[Anti-patterns](#anti-patterns). The test's `LAYERS` mirrors the Layers table: a change edits both in the
same commit. The stage names the skill gives are held to `run.STAGES` by `tests/test_skills.py`.

## Transition

What does not follow the rules yet ([PLAN.md](PLAN.md) holds the deferred work):

- **Captures unverified**: the runner and the example run end to end in Blender, but `run.capture` (its
  part captures included) and `run.poses` need the user interface and have not run there yet.
- **Name heuristics**: review poses keyed by biped bone names in `stages.review`.
- **Flat local forms**: a module directly under `lpk_local/forms/`, outside every model's package, stays
  importable until the human removes it, since only the human sees every model that may import it; a
  model still importing it gets its own copy when next worked on, and its forms in the model module move
  to its package then too. A model is not named like such a module: its package would take the
  module's imports.
