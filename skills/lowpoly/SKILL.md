---
name: lowpoly
description: Model a low-poly character or prop in Blender through Blender MCP with lowpoly-kit (lpk) - read the references, write one model module (measurements, blocks, build_mesh, atlas, bones when rigged), run its stages with lpk.run, review each step with the human, and export when the human asks. Use for any new character or prop, a revision of one, or a question about the kit's forms, atlas, rig or export.
---

# Low-poly models with lowpoly-kit

A model, a character or a prop, is one Python file, its **model module**: measurements read off the
references, the blocks, the mesh composed of the kit's forms, the atlas settings, the bones of a rigged
model and, once the human asks for files, the export targets. `lpk.run` runs the stages a call names and returns a dict; every call
rebuilds what it names. The human reviews in the conversation: nothing in code waits for an answer, so
stop at the points the kind's card marks **Review**, show them what the step made in the open `.blend`, say
what to look at, and wait for their answer before the next step. A part goes through at most a few passes; if it still
does not read right, say what is off and ask how to go on. Throughout: one runner or review call per
bridge call, a short report back, and the human's corrections turned into numbers in the model file. The
agent checks shapes by the numbers, the human by eye in the viewport; a capture is made only for what the
viewport cannot show ([checking a step](references/running.md#checking-a-step)).

Choose the kind of model with the human at the brief; its card is the route of steps, and the topic cards
below hold what every kind shares. The kind is a choice of the workflow: the code reads only the module's
attributes.

| Kind | Card |
|---|---|
| A character on two legs, rigged | [biped](references/kinds/biped.md) |
| An object without a rig: a barrel, a crate, a lamp, a weapon held whole | [prop](references/kinds/prop.md) |

| When | Card |
|---|---|
| First call of a session; running stages; a call that runs long; reading a report | [running](references/running.md) |
| Reading the reference sheet into views, landmarks and widths; a cluttered sheet, a missing view, a cleaned or generated picture, a model without references; an object | [intake](references/intake.md) |
| Writing or changing the model module; the human's vertex moves (`capture_edits`) | [the model file](references/model-file.md) |
| The forms by body area, hard-surface pieces and the joins between parts; a form the library lacks: the model's local package, another model's form, a shared form proposed | [forms](references/forms/README.md) |
| Style axes, the triangle budget and the optimisation pass | [style](references/style.md) |
| Topology edits by hand, adopting an existing model, zones by part: the two build modes; a frozen texture painted by hand; mesh edits under it, the UV check and repair | [the frozen mode](references/frozen.md) |
| The atlas: groups, texel density, the face island, packs, seams, colour sources, the bake, the preview | [atlas](references/atlas.md) |
| The rig of a rigged model: skeleton, joints, weights backends, welded joins, poses | [weights](references/weights.md) |
| Export profiles and the re-import comparison | [export](references/export.md) |
| Writing your own `bpy` or `bmesh` code; the bridge's limits | [Blender and MCP pitfalls](references/pitfalls.md) |

Each kind's card names its worked example: read it before writing a model of that kind.

Delivery: the model, built and reviewed in the open `.blend`, its model module and folder, and a short
message with their paths and any blocker. Export only when the human asks for it
([export](references/export.md)): the model is finished without exported files.
