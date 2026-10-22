# Export

The `export` stage writes one file per entry of `EXPORTS` into `EXPORT_DIR` (relative to the model's folder,
default `out/`), named `<NAME>_<stem>` after the stem of the profile's name or file (`fbx_generic` and
`profiles/engine.json` give `<NAME>_fbx_generic` and `<NAME>_engine`), re-imports each and compares it with
the model (`lpk.stages.export.export_output`). It exports in the rest pose with the bake's final material, and
puts back the pose and the preview display it found.

```python
EXPORTS = ('glb_generic', 'fbx_generic')      # shipped profile names, or JSON paths beside the module
```

It reads the body, the rig and the atlas from the scene: after a `build` (which removes the rig), run
`unwrap`, the packs, `bake` and `rig` again before exporting ([running](running.md)).

## Profiles

A profile is the target's contract: the file format, the axes, the bone names by role, deform-only and
leaf bones, the influence limit and the texture handling. `lpk.profiles.names()` lists the shipped ones and
`lpk.profiles.load(name)['description']` says what each writes; the module docstring of `lpk.profiles`
lists every key. Take the one the target's importer expects.

- **A profile of the model's own**, when no shipped one fits: copy the nearest shipped JSON
  (`lpk.profiles.path_of(name)`) beside the model module, add the key `"schema"` with the value
  `lpk.profiles.SCHEMA` (`load` refuses a profile of the model's own without it), edit the keys and name
  the file in `EXPORTS` by its path. `lpk.profiles.load(path)` validates it on host Python and lists every
  problem; the summary keys (`deform_only`, `leaf_bones`, `influence_limit`, `axes`) and the exporter's
  arguments must agree.
- **Bone names.** The model keeps its own names; a profile renames bones by role on a temporary copy
  during the export only (`lpk.profiles.bone_renames`). Two roles mapped to one name are refused. A bone
  of the model's own (`EXTRA_BONES`) has no role and keeps its name; a deform-only profile leaves out a
  bone that deforms nothing unless a deform bone hangs from it, so a target that needs a prop socket
  needs a profile that writes it.
- **The influence limit** of the rig is the smallest `influence_limit` of the `EXPORTS` profiles
  ([weights](weights.md#the-influence-limit)); a profile added with a lower limit needs `rig` again.

## The re-import comparison

`report['export'][entry]`, keyed by the `EXPORTS` entry as written (a path stays a path), gives the
export's `path`, `bytes`, `images` (PNGs beside an FBX, or the names a `.glb` embeds), `renamed` and
`reimport`, the result of `lpk.stages.export.compare_import`: the file read back with Blender's importer
into a scratch collection, compared with the model, and deleted.
`reimport['diffs']` lists one `{'kind', 'text'}` per difference, in the order of
`lpk.stages.export.DIFF_KINDS`, and is empty when the file matches:

| Kind | What differs | Where to look |
|---|---|---|
| `influences` | the model's bones per vertex exceed the profile's limit | `rig` was run before a lower-limit profile was added: run it again |
| `import` | the importer failed | the text holds the importer's error |
| `armatures`, `meshes` | not exactly one armature and one mesh came back | stray objects in the export, a split mesh |
| `bones`, `parents` | bone names (after renames), count or hierarchy | the profile's `bone_map`, `deform_only`, `leaf_bones` |
| `triangles` | the triangle count | modifiers applied on export, faces lost |
| `uv layers` | the UV layer count | an extra or missing UV map |
| `images` | image names (without extension and `.001` suffixes) | the material's connected Image Texture nodes; the FBX exporter carries a diffuse map only from a Principled Base Color link |
| `skin` | the mesh came back without weights or not deformed by the armature | the Armature modifier, the exporter's skin settings |
| `size` | the world-space size along an axis beyond `lpk.stages.export.SIZE_METRES` plus `SIZE_SHARE` of it | a unit or scale error: a centimetre or inch unit, a scale left unapplied |

A difference means the file is not the model: fix the cause, never the profile to quiet it. `bones` and
`triangles` in the report are the counts read back from the file; `influences` is the model's own largest
number of bones weighting one vertex, the count the profile's limit is held against.

## Checking the import in the engine

The comparison reads the file with Blender's importer; it cannot see how the target engine imports, maps
or plays it. A claim that the model is ready for a named engine needs the human's import check there:

- the engine and importer version and the import settings or preset, and which exported file was tested
  (a later export is a different test);
- height and scale, forward and up;
- the mapped rig and its reference-pose settings, a named test clip, and how the shoulders, hips and any
  tail deform in it (a retargeting importer measures poses from its own reference pose, so posture
  authored only into the rest can vanish);
- the material and texture assignment, the shader, filtering and mipmaps, and the colours at the read
  size.

Without access to the target, say which checks were not made. Deliver the files from `out/` (or
`EXPORT_DIR`) with a short message naming their paths and any blocker.
