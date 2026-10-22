"""Live-shading preview of a colour atlas: what the model may look like under a runtime shader
with one key light. Review only; nothing here is exported. The presets are plain data that
preset_problems checks on any Python; the functions that build a preview need Blender.

The preview (preview_atlas) shows its material through the body's object-level slot link and never
changes the mesh's material, which stays the bake's final material that the export exports;
mesh_materials holds the slot links on the mesh's materials for a kernel that bakes or exports the body
and puts the display back."""
from contextlib import contextmanager
import os

# The looks a preview takes: 'light' the direction toward the key light (world space, normalised by the
# preview); 'ramp' the Blender colour ramp interpolation over N.L; 'tones' ((N.L, RGBA), ...) in rising N.L
# from -1 to 1, each colour where its tone starts. 'neutral' shades grey to white with no tint and no steps;
# 'toon' is a hard three-tone cel ramp: a shadow tone below N.L -0.15, a mid tone up to 0.30, lit above.
PRESETS = {
    'neutral': {'light': (-0.55, -0.55, 0.63), 'ramp': 'LINEAR',
                'tones': ((-1.0, (0.6, 0.6, 0.6, 1.0)), (1.0, (1.0, 1.0, 1.0, 1.0)))},
    'toon': {'light': (-0.55, -0.55, 0.63), 'ramp': 'CONSTANT',
             'tones': ((-1.0, (0.50, 0.46, 0.60, 1)), (-0.15, (0.74, 0.71, 0.80, 1)), (0.30, (1, 1, 1, 1)))},
}
# The slot link that shows the mesh's own material, and the one that shows the object's.
DATA_LINK, OBJECT_LINK = 'DATA', 'OBJECT'


def preset_problems(preset):
    """Why `preset` cannot shade a preview: [message], empty for a name of PRESETS."""
    if isinstance(preset, str) and preset in PRESETS:
        return []
    return ['preset %r: use one of %s' % (preset, ', '.join(PRESETS))]


def _atlas_file(atlas_image, file_image, path):
    """The image `file_image` loaded from the PNG `path`, which the image `atlas_image` is saved to first
    through the render settings under the Standard view transform (lpk.stages.view.standard_view): EEVEE
    shows a freshly baked generated image as black, and the Standard transform keeps the atlas colours
    exact whatever the scene's transform."""
    import bpy
    from lpk.stages.view import standard_view
    with standard_view():
        bpy.data.images[atlas_image].save_render(path)
    img = bpy.data.images.get(file_image)
    if img:
        img.filepath = path; img.reload()
    else:
        img = bpy.data.images.load(path); img.name = file_image
    return img


def _preview_material(name, img, preset):
    """The material `name` showing the image `img` times the preset's colour ramp over N.L, as an emission
    (nodes built on N.L alone, so the look ports to a Unity Shader Graph)."""
    import bpy
    from mathutils import Vector
    p = PRESETS[preset]
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True; nt = m.node_tree; nt.nodes.clear()
    N = nt.nodes.new; L = nt.links.new
    tex = N('ShaderNodeTexImage'); tex.image = img; tex.interpolation = 'Closest'
    geo = N('ShaderNodeNewGeometry')
    light = N('ShaderNodeCombineXYZ'); light.label = 'Light direction (world, toward the light)'
    for i, v in enumerate(Vector(p['light']).normalized()):
        light.inputs[i].default_value = v
    dot = N('ShaderNodeVectorMath'); dot.operation = 'DOT_PRODUCT'
    L(geo.outputs['Normal'], dot.inputs[0]); L(light.outputs[0], dot.inputs[1])
    remap = N('ShaderNodeMath'); remap.operation = 'MULTIPLY_ADD'
    remap.inputs[1].default_value = 0.5; remap.inputs[2].default_value = 0.5
    L(dot.outputs['Value'], remap.inputs[0])
    ramp = N('ShaderNodeValToRGB'); cr = ramp.color_ramp; cr.interpolation = p['ramp']
    for k, (t, c) in enumerate(p['tones']):
        e = cr.elements[k] if k < 2 else cr.elements.new(t * 0.5 + 0.5)
        e.position = t * 0.5 + 0.5
        e.color = c
    L(remap.outputs[0], ramp.inputs['Fac'])
    mul = N('ShaderNodeMix'); mul.data_type = 'RGBA'; mul.blend_type = 'MULTIPLY'; mul.inputs[0].default_value = 1.0
    L(tex.outputs['Color'], mul.inputs[6]); L(ramp.outputs['Color'], mul.inputs[7])
    em = N('ShaderNodeEmission'); out = N('ShaderNodeOutputMaterial')
    L(mul.outputs[2], em.inputs['Color']); L(em.outputs[0], out.inputs['Surface'])
    return m


def preview_atlas(obj_name, atlas_image, file_image, material, path, preset):
    """The preview on the body `obj_name`: the atlas image `atlas_image` (the bake's '<Name>_Atlas')
    saved to the PNG `path` and loaded as the image `file_image` ('<Name>_AtlasFile'), the material
    `material` ('<Name>_Preview') showing it in the look of `preset` (a name of PRESETS), and
    that material shown on the body through the object-level link of its material slot 0. The mesh's own
    material (the bake's final material, which the export exports) is never changed, and nothing is written
    on the object besides the slot's link and material. path: out/<Name>_Atlas_preview.png. Raises
    ValueError for an unknown preset and for a body without a material slot (run the bake first). Returns
    {'material': material, 'image': file_image, 'file': path, 'preset': preset, 'shown': the mesh material
    the slot links over}."""
    import bpy
    problems = preset_problems(preset)
    if problems:
        raise ValueError('preview: ' + '; '.join(problems))
    ob = bpy.data.objects[obj_name]
    if not ob.material_slots:
        raise ValueError('%s has no material slot: run the bake first' % obj_name)
    os.makedirs(os.path.dirname(str(path)) or '.', exist_ok=True)
    img = _atlas_file(atlas_image, file_image, str(path))
    m = _preview_material(material, img, preset)
    slot = ob.material_slots[0]
    slot.link = OBJECT_LINK
    slot.material = m
    return {'material': material, 'image': file_image, 'file': str(path), 'preset': preset,
            'shown': ob.data.materials[0].name if ob.data.materials and ob.data.materials[0] else None}


@contextmanager
def mesh_materials(ob):
    """Hold every material slot of the object `ob` on its mesh's material for the block (a bake or an
    export sees what the mesh carries, the bake's final material, never the preview's display): on entry
    each slot's link and object-level material are kept and the links set to the mesh's; on exit, also after
    an error, every slot that still exists gets its link and object-level material back."""
    kept = []
    for slot in ob.material_slots:
        kept.append((slot.link, slot.material if slot.link == OBJECT_LINK else None))
        slot.link = DATA_LINK
    try:
        yield ob
    finally:
        for slot, (link, material) in zip(ob.material_slots, kept):
            if link == OBJECT_LINK:
                slot.link = OBJECT_LINK
                slot.material = material
