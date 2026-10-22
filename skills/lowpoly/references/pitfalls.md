# Blender and MCP pitfalls

## The bridge

- Run Blender with its user interface: captures, and the edit-mode, bake and UV operators that take an
  area, need a 3D Viewport, and a background Blender cannot render the viewport. Rig building and heat
  weights need only a window.
- Install the bridge's add-on and allow online access in Preferences > System > Network; one Blender serves
  one bridge port. Nothing of the kit is installed into Blender: the bootstrap puts its folder on the path.
- `execute_blender_code` runs your code with `exec` in a fresh namespace on Blender's main thread, the
  interface frozen for the call, and returns the variable `result`, which must be a dict. Variables do not
  survive between calls; `sys.modules`, `sys.path` and `bpy.data` do, hence the bootstrap's purge.
- **A rejected `result` arrives after its side effects** (not a dict, a response too large), and a call that
  runs past the limit is not cancelled, only its response is lost: inspect the scene before running
  anything again.
- Responses are limited in size: save images and long reports under the model's `out/` and return their
  paths and the few values you need.
- The bridge's area screenshots are black while Blender is minimised or covered and come back downscaled;
  make images with `run.capture`, which renders the viewport offscreen to an exact path.
  `render_viewport_to_path` is a camera render written to Blender's temp folder, not a viewport capture.
- Blender's temp folder is deleted when Blender exits: keep every output under `out/`.

## Your own bpy and bmesh code

- **View transform.** AgX and Filmic grey the baked whites in the viewport and in saved renders. The kit's
  captures and preview switch to Standard themselves; your own renders go through the scene's.
- **Freshly baked images show black in EEVEE**: save to PNG and load the file (the preview does).
- **Mesh edit-mode and UV operators** (those that take an area) need a `temp_override` with the 3D Viewport
  area and its WINDOW region; switching the mode, parenting and other object operators need only the window.
  UV operators act on every visible face regardless of selection: hide what they must not touch.
- **`mode_set` invalidates mesh data references**: fetch `ob.data` and its layers again after a switch.
- **New bmesh faces have no normals** until `bm.normal_update()`; a BVH tree built before that returns
  wrong hit normals (`lpk.core.shapes.bvh_of` updates them).
- **Builder vertex layers** must exist before the first vertex: a layer added later invalidates every
  vertex reference held so far. Pass them to `lpk.core.builder.Builder` (`vert_layers=`).
- **Rigged meshes** are parented to the armature, and their `location` is then the origin: read their
  position from `matrix_world.translation`.
- **Quaternion precision**: single-precision quaternions cannot resolve angles under about 0.05 degrees;
  compare bone axes instead.
- **FBX import axes**: importing with the default primary bone axis leaves bones from other tools pointing
  sideways; match the exporter's bone axes. An animation FBX can import at another scale than its
  skeleton: transfer local transforms with the translations scaled.
- **A wireframe-shaded render is empty**: capture the viewport with the wire overlay instead.
- **Inspecting another .blend** without opening it: `bpy.data.libraries.load(path, link=True)`, read, then
  remove the library.
- **Object names are global** in a file: name your helpers `<NAME>_...` and delete them in the call that
  made them. The kit replaces only objects named after the model; do not edit the ones it makes with `bpy`
  other than the hand edits `capture_edits` stores.
- **The voxel-heat add-on's operator is modal** and never completes through the bridge: the kit runs its
  binary directly (`lpk.stages.rig.vhd_weights`). If that binary hangs, the call loses its response while
  the binary runs on.
- **Unwrap and bake.** Smart project scales each run to its own bounds and `uv.unwrap` packs and rescales
  what it makes: scale islands back to their surface area before applying densities. Smart UV islands
  follow angles, not materials: unwrap each group on its own. `pack_islands(pin=True,
  pin_method='LOCKED')` packs other islands over the pinned one, and `shape_method='AABB'` squeezes them.
  An emission bake writes into each material's active Image Texture node; selected-to-active with
  `use_clear=False` and no bake margin leaves texels whose rays miss at the previous bake. The FBX
  exporter carries a diffuse map only from a Principled Base Color link.
