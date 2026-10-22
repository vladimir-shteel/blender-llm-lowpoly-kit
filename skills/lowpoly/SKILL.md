---
name: lowpoly
description: Model a low-poly character in Blender through Blender MCP with lowpoly-kit (lpk) - read the references, write one model module (measurements, blocks, build_mesh, atlas, bones), run its stages with lpk.run, review each step with the human, and export. Use for any new character, a revision of one, or a question about the kit's forms, atlas, rig or export.
---

# Low-poly character with lowpoly-kit

A character is one Python file, its **model module**: measurements read off the references, the blocks,
the mesh composed of the kit's forms, the atlas settings, the bones and the export targets. `lpk.run`
runs the stages a call names and returns a dict; every call rebuilds what it names. The human reviews
in the conversation: nothing in code waits for an answer, so stop and ask where the process says so.

| When | Card |
|---|---|
| First call of a session; running stages; a call that runs long; reading a report | [running](references/running.md) |
| A new character, or what to do next | [the process](references/process.md) |
| Reading the reference sheet into views, landmarks and widths; a cluttered sheet, a missing view, a cleaned or generated picture, a character without references | [intake](references/intake.md) |
| Writing or changing the model module; the human's vertex moves (`capture_edits`) | [the model file](references/model-file.md) |
| The forms by body area and the joins between parts; a form the library lacks: the model's local package, another model's form, a shared form proposed | [forms](references/forms/README.md) |
| Style axes, the triangle budget and the optimisation pass | [style](references/style.md) |
| Topology edits by hand, adopting an existing model, zones by part: the two build modes; a frozen texture painted by hand; mesh edits under it, the UV check and repair | [the frozen mode](references/frozen.md) |
| The atlas: groups, texel density, the face island, packs, seams, colour sources, the bake, the preview | [atlas](references/atlas.md) |
| The rig: skeleton, joints, weights backends, welded joins, poses | [weights](references/weights.md) |
| Export profiles and the re-import comparison | [export](references/export.md) |
| Writing your own `bpy` or `bmesh` code; the bridge's limits | [Blender and MCP pitfalls](references/pitfalls.md) |

The worked example is `examples/mannequin/mannequin.py`: read it before writing a model of your own.

Delivery: the requested model files and a short message with their paths and any blocker.
