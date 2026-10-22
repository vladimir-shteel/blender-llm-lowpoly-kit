# Forms: the shape vocabulary

A model's `build_mesh(P)` composes its parts from three layers: the primitives of `lpk.core.builder.Builder`
(`loft`, `box`, `pyramid`, `decal`, `mirror_part`, `move_part`, `scale_part`, `ground_part`), the surface
and join operations of `lpk.core.shapes`, and the body-part forms of `lpk.forms.<area>`. A form is a
parametric blank: start from its defaults, change a parameter for a reason you can name from the
references, and never bend a preset made for another species until it fits. Every function's docstring
holds its units, defaults, triangle cost and limits: read it in the source file before the call (the
forms import `bmesh` and `mathutils`, so `help()` on them works only inside a Blender call).

One card per body area says which form fits which look, how to measure it, how to call it from
`build_mesh(P)` and what it cannot do:

| Area | Card |
|---|---|
| Heads, ears, muzzles, profile keys | [head.md](head.md); a worked example of keys traced off a drawn head: [snout-keys.md](snout-keys.md) |
| Eyes, mouths, facial hair | [eyes-face.md](eyes-face.md) |
| Hair caps, locks, fur masses, tufts | [hair-fur.md](hair-fur.md) |
| Hands | [hands.md](hands.md) |
| Feet, paws, boots, toes | [feet.md](feet.md) |
| Tails | [tails.md](tails.md) |
| The trunk and clothing | [torso-clothing.md](torso-clothing.md) |
| Straps, plates and hard parts | [gear.md](gear.md) |
| Markings and painted decals | [markings-decals.md](markings-decals.md) |
| Limbs, welded joins and separate shells | [joins.md](joins.md) |

## Where a new form goes

There are two libraries. The **shared** library is `lpk.forms.<area>`, part of the kit and listed in the
catalogue below. The **local** library is `lpk_local.forms.<model>.<area>`: the folder `lpk_local/forms/`
at the kit's root, ignored by git, one package per model, for the forms you write for this user's models.

The model module holds composition: a part built by calling the kit's forms and kernels (lofts, sections,
casts, lobes, welds) with the model's values stays there, as the mannequin's part functions do. A
function that makes a part's own rings, faces or vertex layout is a form. A form a part needs that
neither library has goes at once into the local package of the model that first uses it,
`lpk_local/forms/<model>/<area>.py`, `<model>` being the model module's file name without `.py` (a
Python identifier, unique among the user's models and unlike any module directly under `lpk_local/forms/`:
name the model file so): a public
function with a docstring like the shared forms' (what it builds, its parameters with units, what it
returns, its causal limits), taking the builder, a part name and measurements, imported by the model
(`from lpk_local.forms.hero import gear`). A local form imports the kit's kernels and forms and the
other forms of its own package, never a model module or another model's package.

A form another model's package already has is a start, never a dependency: copy it into this model's
package and change the copy as this model needs, without asking. Forms change only for their own model,
so nothing else on the disk moves. Then you may tell the human that another model holds a similar form:
similar forms in the packages of several models are the signal to merge them, and you propose one shared
form that covers them.

Never move a form into the shared library on your own. Moving it is the human's decision: on their
request, move it from the local library into `lpk/forms/<area>.py`, merging the similar forms into one
function with a parameter per difference, with a docstring, a host test for its pure parts and its line
in this catalogue (ARCHITECTURE.md, "Extending the kit"); change the models the human names to import it
from there and delete their local copies; any other model keeps its own copy. The move changes the
user's copy of the kit; into the kit's repository it goes through the maintainer's review.

The local library is not in the kit's files: create it on first use as packages `lpk_local/`,
`lpk_local/forms/` and `lpk_local/forms/<model>/`, each with an `__init__.py` that holds a one-line
docstring (the model's package names its model module), and the form's module in the last. The
bootstrap's purge removes `lpk_local` with the kit, so every call reads its forms again. Keep the folder
when the kit is replaced by a new copy: nothing else holds it.

## Catalogue

### `lpk.forms.head`

- `profile_head`: a head facing -Y lofted from `ProfileKey` records at their exact extents, closed on nose and skull apexes.
- `snout_head`: a muzzled head from side-view keys in head units or metres (`MUZZLE_*` and `REPTILE_*` presets).
- `muzzle_keys`: `snout_head` keys, nose apex and stop built from a few measured proportions.
- `side_key`, `side_point`: one key, or one apex, in metres read off a calibrated side view.
- `front_half_width`: half the width of a front outline at a model height.
- `traced_keys`: every key in metres from a side outline and a front outline, at the columns you choose.
- `front_envelope`: the front outline a set of keys makes, compared with a drawn one height by height.
- `profile_key_deviation`: how far each inner key sits off the line between its neighbours.
- `taper_below`: narrows a built head below a height toward the chin.
- `wedge_muzzle`: turns round muzzle sections into wedges, a ridged bridge and a triangular nose.
- `lift_muzzle`: raises a muzzle's front, keeping the topology the hand edits were captured on.
- `human_head`: a stylised human head from horizontal slices at a fixed density (`HUMAN_HEAD`).
- `face_decals`: crisp facial features as flat polygons just off a `human_head` face.
- `face_shell`: a beard or moustache as a shell hugging the face.

### `lpk.forms.eyes`

- `socket_eyes`: round lidded eyes in a raised lid ring, both sides, with optional brow tuft and mask patch.
- `traced_eye`: a drawn eye as flat colour layers cast onto the head, one builder per layer.
- `bevel_eye`: an almond eye cast from one direction both the front and the side view agree on.

### `lpk.forms.hair`

- `hair_cap`: hair as a shell over the skull with a tucked hairline; returns the `covered` test.
- `remove_covered`: deletes the faces of a part wholly under a shell.
- `hair_strand`: a loose flat lock draped over the head and cap.
- `hair_bun`: a lumpy bun with wisps.
- `hair_locks`: spiky locks cast straight down onto the scalp, optionally mirrored exactly.
- `hair_mantle`: long hair falling down the back, ending in sealed spikes.
- `long_beard`: a long beard rooted along the jaw, hanging to a pointed, blunt or forked tip; refuses collapsing faces.

### `lpk.forms.fur`

- `tuft`: one straight spike, shard or blade.
- `tuft_fan`: tufts fanning from one buried root (epaulettes).
- `fur_fringe`: a shaggy edge of tufts round a loft ring.
- `fur_mass`: a huge smooth mass of fur or hair with fringes where the outline needs them.
- `flame_locks`: a mane of flat curved locks from one root.

### `lpk.forms.hands`

- `chunky_hand`: a broad heavy hand with short closed clawed fingers.
- `slender_hand`: a long thin hand with few jointed fingers and pointed nails.
- `talon`: one long curved claw or hooked lock.
- `talon_hand`: a long hand ending in curved talons.
- `fist_points`: the key points (and bone ends) of `fist_mitten`.
- `fist_mitten`: a mitten fist with a split index finger and a thumb grown from the palm.
- `mitten_finger_lines`: the painted finger gaps of a `fist_mitten`, for a colour source.

### `lpk.forms.feet`

- `platform_boot`: a boxy sole slab and a rounded upper, grounded.
- `work_boot`: a lace-up boot to mid-calf with lug sole, shaft and toe cap, grounded.
- `work_boot_points`: the key points of `work_boot` (ankle, top, heel, ball, toe) without building it.
- `strap_paw`: a long hind paw on a raised ankle with a strap ring and clawed toes.
- `paw_toes`: a row of clawed mammal digits.
- `mitt_paw`: a puffy paw standing on the floor with claws peeking out.
- `talon_toes`: bird- or raptor-like toes fanning from the ball of a digitigrade foot.

### `lpk.forms.tails`

- `straight_tail`: a tail at rest as one straight loft, its root and tip closes chosen.
- `lock_fan`: a tail of long flat locks fanning from a buried knot.

### `lpk.forms.torso`

- `trunk`: the trunk as one surface of fixed rings from the crotch to the neck (`SIDES`, `FLAT`, `ARMHOLE_COLS`).
- `section_at`: the trunk's `Section` at a height, interpolated between its sections; where a garment starts.
- `skirt`: a skirt or tunic hem as a separate open shell hanging off the widest body, flaring to its hem.
- `belt`: a hoop round the trunk at a height, sealed into the body, with an optional box buckle on its front.

### `lpk.forms.limbs`

- `arm_frame`: the A-pose arm's shoulder, elbow, wrist, `d` and `out` from P.
- `limb`: a loft along a joint path by an arc-length profile.

### `lpk.forms.joins`

- `armholes`: cuts the two armholes between a pair of trunk rings and tags their loops (`LAYER`).
- `leg_holes`: splits the trunk's bottom ring into two leg holes round a crotch seam (`LEG_TILT`).
- `weld_limb`: an arm grown out of an armhole: socket section, welded corners, bridged front and back.
- `weld_leg`: a leg grown out of a leg hole, its first ring bridged to it.

### `lpk.forms.markings`

- `wrapped_stripes`: tiger-like stripes across a segment, both sides, recorded for the texel readings.

### `lpk.core.shapes`

Lofts and rings:

- `path_rings`: `Builder.loft` rings placed along a polyline by arc length.
- `profile_loft`: a loft from a side silhouette and a width curve, sections perpendicular to its axis.
- `point_loft`: a loft through explicit point rings, for sections no ellipse describes.
- `polygon_rings`: point rings of `Builder.loft`'s n-gon sections with chosen vertices dropped.
- `jitter_rings`: seeded radius noise on loft rings, crumpled cloth.
- `lobe`: a thick pointed cupped lobe (ear, fin, leaf).
- `tilt_section`: slides a limb ring so it meets its parent in a tilted section.
- `lift_rings`: pushes ring vertices out from their centres, a loft copy as a colour source.

Casting and joining:

- `bvh_of`: a BVH over chosen parts only, the surface casts land on.
- `cast_point`: the first hit of a ray, sunk into the surface; counts a miss.
- `snap_ring`: lands a loft's ring on another surface along a direction.
- `hug_rings`: lays ring vertices just proud of another surface.
- `cut_loop`: deletes the faces between two rings over chosen columns and returns the hole loop.
- `split_bottom_ring`: two leg holes out of an open bottom ring.
- `matched_loop`: a loop re-ordered to lie closest to given points.
- `bridge`: faces from a hole loop to a limb's first ring.
- `ridge_flip`: rotates the valley-folding edges round a join on its parent parts.
- `join_report`: wire, non-manifold and open edges, buried child vertices and intersections of a join.
- `miss`, `mark`: record a missed probe, or a painted mark for the texel readings, on the builder.

Painted and in-mesh decals:

- `surface_strip`: a ribbon along a polyline snapped to the nearest surface.
- `surface_patch`: an n x n grid patch snapped to the surface.
- `surface_fill`: a region of any outline, triangulated in its best-fit plane and snapped.
- `surface_star`: a flat star decal.
- `surface_blotches`: seeded irregular blotches, each lifted above the last.
- `fan_decal`: a polygon cast along a direction and fanned through rings so it follows the curvature.
- `axis_fill`: a region wrapped round a body segment, cast toward its axis.
- `ray_grid`: a patch of first hits from outside, for a layer lying over another.
- `ring_band`: a colour band round a loft at one of its rings.
- `band_source`: equal colour bands along a loft, its boundaries on a strip's texel lines.

Hard parts:

- `conform_plate`: an armour or panel plate projected onto a curved surface, chamfered or chipped.
- `star_prism`: a star badge, buckle or framed lens standing off a surface.
