"""The stage runner: one model module, the stages a call names, a dict report.

From an MCP execute_blender_code call, after the bootstrap of lpk/__init__.py:

    from lpk import run
    report = run.model(r'<model folder>/<model>.py', stages=('build', 'unwrap', 'pack'))

Every call rebuilds what its stages name, in the order of STAGES, from the model module read again from
disk; nothing is kept between calls but the scene, the model's files and its out/ folder. A long stage
is split by naming it in several calls: 'pack' repeats (list it several times, or call again) until the
face island converges. ARCHITECTURE.md "Model module contract" lists what each stage reads.

A model builds in one of two modes (ARCHITECTURE.md "Build modes"). Parametric (FROZEN absent or False): build
makes the body from build_mesh(P), and the human only moves vertices, which capture_edits stores. Frozen
(FROZEN = True): build copies the frozen mesh '<NAME>_Frozen' of the open .blend into the body, and build_mesh
makes only the colour sources, which build carries onto the frozen body; freeze stores the scene's body,
edited in any way, as that mesh, and adopt makes it from another mesh object (ADOPT). freeze does not switch
the mode: until the module sets FROZEN = True, build stays parametric and rebuilds the body from build_mesh
(the frozen mesh keeps the edit). build, freeze and capture_edits stamp the body with what they wrote
(lpk.stages.zones.stamp); a build that finds the body changed since raises unless the call passes
discard_edits=True. In the frozen mode the zone operations (transform, replace, decimate, subdivide, smooth)
change one part of the body and store it as the frozen mesh in the same call (operate).

The texture is procedural (TEXTURE_FROZEN absent or False: unwrap, pack and bake make it again) or frozen
(TEXTURE_FROZEN = True, only with FROZEN = True): freeze_texture stores the body's UV layer on the frozen
mesh and the atlas as '<NAME>_AtlasFrozen' in the .blend, hand edits included; build brings the UVs back,
unwrap and pack refuse, and bake composites only the SOURCES marked 'over' over the frozen atlas, every
other texel kept. unfreeze_texture drops the frozen texture and says what is lost. As with freeze,
freeze_texture does not switch the mode: the module sets TEXTURE_FROZEN = True. Mesh edits stay allowed
under a frozen texture: check_uvs reports the faces whose UVs an edit broke (the frozen-texture build and
bake, and freeze and the zone operations while they keep the UVs, carry the same report as 'uv_check'),
and repair_uvs, on the human's request, gives them new islands in free atlas space and bakes them."""
import importlib.util
import json
import os
import sys

import bpy

STAGES = ('reference', 'blocks', 'capture_edits', 'adopt', 'freeze', 'unfreeze_texture', 'build', 'unwrap', 'pack',
          'bake', 'freeze_texture', 'rig', 'preview', 'pose_test', 'pose_rest', 'export')
# The stages that read the measurements props() gives.
MEASURED = ('blocks', 'capture_edits', 'adopt', 'freeze', 'build', 'unwrap', 'pack', 'bake', 'rig')
# The options of model(), each passed to the stages that take it.
OPTIONS = {'rescale': (), 'backend': ('rig',), 'discard_edits': ('build', 'bake')}
# The gap between the reference images and between them and the model (m). Front and back views stand to
# the model's right (-X), side views behind it (+Y): each edge-on in the views that look at the others.
REFERENCE_GAP = 0.1


def load(path):
    """The model module at `path`, executed afresh from disk under the module name 'lpk_model_<file
    name>' (replacing an earlier load), so an edit on disk takes effect in the same Blender session. The
    source is compiled on every load, never read from a bytecode cache: the cache is keyed by the file's
    modification time in whole seconds and its size, so a number rewritten within a second at the same
    length would run the stale code."""
    path = os.path.abspath(path)
    name = 'lpk_model_' + os.path.splitext(os.path.basename(path))[0]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None:
        raise ValueError('model %s: not a Python file' % path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    with open(path, 'rb') as f:
        code = compile(f.read(), path, 'exec')
    exec(code, module.__dict__)
    module.__lpk_folder__ = os.path.dirname(path)
    return module


def need(M, name):
    """The model attribute `name`; raises AttributeError naming it and the model when it is missing."""
    if not hasattr(M, name):
        raise AttributeError('model %s defines no %s' % (getattr(M, 'NAME', M.__name__), name))
    return getattr(M, name)


def folder(M, *parts):
    """A path under the model module's folder."""
    return os.path.join(M.__lpk_folder__, *parts)


def out(M, *parts):
    """A path under the model's out/ folder, which is created when missing."""
    os.makedirs(folder(M, 'out'), exist_ok=True)
    return folder(M, 'out', *parts)


def names(M):
    """The scene names of the model's objects: {'body', 'blocks', 'rig', 'atlas' (the atlas image and the
    body's final material), 'collection', 'sources' (the collection of the colour sources, a child of
    'collection'), 'frozen' (the frozen mesh, a mesh datablock), 'atlas_frozen' (the frozen texture's
    image)} and 'source' for the colour sources, a function of the source name."""
    n = need(M, 'NAME')
    return {'body': n, 'blocks': n + '_Blocks', 'rig': n + '_Rig', 'atlas': n + '_Atlas', 'collection': n,
            'sources': n + '_Sources', 'frozen': n + '_Frozen', 'atlas_frozen': n + '_AtlasFrozen',
            'source': lambda key: n + '_' + key}


def frozen(M):
    """Whether the model builds in the frozen mode: its FROZEN is True."""
    return bool(getattr(M, 'FROZEN', False))


def texture_frozen(M):
    """Whether the model's texture is frozen: its TEXTURE_FROZEN is True. Raises ValueError when it is and
    FROZEN is not: the frozen texture lives on the frozen mesh."""
    if not getattr(M, 'TEXTURE_FROZEN', False):
        return False
    if not frozen(M):
        raise ValueError('TEXTURE_FROZEN = True needs the frozen mesh mode: set FROZEN = True as well')
    return True


def texture_stored(M):
    """Whether the open .blend holds a frozen texture of the model: the atlas UV layer on the frozen mesh
    '<NAME>_Frozen' or the image '<NAME>_AtlasFrozen'."""
    from lpk.stages import texture
    n = names(M)
    me = bpy.data.meshes.get(n['frozen'])
    return bool((me is not None and texture.UV_LAYER in me.uv_layers) or bpy.data.images.get(n['atlas_frozen']))


def kept_uv(M, stage):
    """The UV layer a store of the frozen mesh by `stage` keeps (lpk.stages.zones.freeze's uv): the atlas
    UV layer under a frozen texture (the body's UVs, through the edit), else None. Raises ValueError when the
    .blend holds a frozen texture and the module's texture is procedural: the body's UVs are then the
    unwrap's, and storing the mesh without them would drop the frozen UVs."""
    from lpk.stages import texture
    if texture_frozen(M):
        return texture.UV_LAYER
    if texture_stored(M):
        raise ValueError('%s: the frozen mesh carries a frozen texture and the module\'s texture is procedural: set '
                         'TEXTURE_FROZEN = True and build to keep the frozen texture through the edit, or run '
                         'unfreeze_texture to drop it' % stage)
    return None


def require(M, stage, *needs):
    """The scene objects `stage` reads, checked before it runs. needs: any of 'body' (the body '<NAME>'),
    'uv' (the body with the atlas UV layer lpk.stages.texture.UV_LAYER the unwrap makes) and 'rig'
    ('<NAME>_Rig'). Returns {need: its object}, the body for 'uv'. Raises ValueError naming the stage, what
    is missing and the stage to run first: build for the body, unwrap for the UVs, rig for the rig."""
    n = names(M)
    found = {}
    if 'body' in needs or 'uv' in needs:
        ob = bpy.data.objects.get(n['body'])
        if ob is None:
            raise ValueError('%s: no body %s in the scene: run build first' % (stage, n['body']))
        found['body'] = ob
        if 'uv' in needs:
            from lpk.stages import texture
            if texture.UV_LAYER not in ob.data.uv_layers:
                raise ValueError('%s: the body %s has no atlas UV layer %s: run unwrap first'
                                 % (stage, n['body'], texture.UV_LAYER))
            found['uv'] = ob
    if 'rig' in needs:
        rig = bpy.data.objects.get(n['rig'])
        if rig is None:
            raise ValueError('%s: no rig %s in the scene: run rig first' % (stage, n['rig']))
        found['rig'] = rig
    return found


def check_stages(stages):
    """Raises ValueError for a stage STAGES lacks or a repeated stage other than 'pack'."""
    unknown = [s for s in stages if s not in STAGES]
    if unknown:
        raise ValueError('unknown stages %s: use %s' % (', '.join(unknown), ', '.join(STAGES)))
    repeated = sorted({s for s in stages if s != 'pack' and list(stages).count(s) > 1})
    if repeated:
        raise ValueError('stages %s are listed more than once: only pack repeats' % ', '.join(repeated))


def model(path, stages, **options):
    """Run `stages` of the model module at `path` in the order of STAGES ('pack' as many times as it is
    listed) and return {stage: its report}, 'pack' a list of one report per pack. options:
      rescale  the first pack's rescale (lpk.stages.texture.pack_step) when the call does not also unwrap;
               after an unwrap in the same call the first pack never rescales, as pack_step requires;
      backend  the weights backend of the rig stage (lpk.stages.rig.BACKENDS or 'auto'; default the
               model's WEIGHTS, else 'auto');
      discard_edits  True lets build replace a body changed by hand since the kit wrote it (the build
               stamp), and a frozen-texture bake replace an atlas painted by hand since, dropping the change;
               default False: such a build or bake raises (guard, bake).
    Raises ValueError for an unknown stage or an unknown option, before anything runs, ValueError when a
    stage finds the scene without what an earlier stage makes (require), and AttributeError naming a model
    attribute a stage needs and the model lacks."""
    check_stages(stages)
    check_options(options)
    M = load(path)
    P = M.props() if any(s in MEASURED for s in stages) else None
    if P is not None:
        P['edits'] = edits_data(M)
    report = {}
    for stage in STAGES:
        if stage not in stages:
            continue
        if stage == 'pack':
            report['pack'] = packs(M, P, list(stages).count('pack'),
                                   options.get('rescale', True) and 'unwrap' not in stages)
        else:
            report[stage] = RUNNERS[stage](M, P, **{k: v for k, v in options.items() if stage in OPTIONS[k]})
    return report


def check_options(options):
    """Raises ValueError for an option OPTIONS lacks."""
    extra = set(options) - set(OPTIONS)
    if extra:
        raise ValueError('unknown options %s: use %s' % (', '.join(sorted(extra)), ', '.join(OPTIONS)))


def edits_data(M):
    """The model's stored hand edits ({part: entry}, lpk.core.edits.load) from the file EDITS names
    (relative to the model's folder), {} without EDITS. build_mesh passes them to lpk.core.edits.apply
    as P['edits']."""
    from lpk.core import edits
    return edits.load(folder(M, M.EDITS)) if getattr(M, 'EDITS', None) else {}


# -- the stages ------------------------------------------------------------------------------------------

def reference(M, P):
    """Each view of the model's views.json (VIEWS, a path relative to its folder) with an image as an
    image empty beside the model at the model's scale (lpk.stages.reference.place), named
    '<NAME>_Ref_<view>'; REFS, when given, lists the views to show. Returns {view: place's report}."""
    from lpk.core import views as views_mod
    from lpk.stages import reference as ref
    views = views_mod.Views(folder(M, need(M, 'VIEWS')))
    n = names(M)
    shown = getattr(M, 'REFS', None) or [v for v in views.names if views.view(v).get('image')]
    placed = {}
    for view in shown:
        v = views.view(view)
        placed[view] = corners(views.calib(view), v.get('facing', 'front'), views.size(view), v.get('mid_px'))
    report = {}
    for view, shift in layout(placed).items():
        plane, low, high = placed[view]
        report[view] = ref.place(n['body'] + '_Ref_' + view, folder(M, views.image(view)), n['collection'], low,
                                 high, plane=plane, shift=shift)
    return report


def layout(placed):
    """{view: shift (m)} that sets the reference images side by side, clear of the model and of each other:
    front and back views in a row to the model's right (-X), side views in a row behind it (+Y), REFERENCE_GAP
    apart. placed: {view: corners()' (plane, lower-left, upper-right)}, in placing order. A drawing spans
    the figure it shows, so the widest image of a row bounds the model in that row's direction."""
    rows = {'front': 0, 'side': 1}
    out = {}
    for plane, axis in rows.items():
        views = [v for v, (p, _, _) in placed.items() if p == plane]
        if not views:
            continue
        reach = max(max(abs(placed[v][1][axis]), abs(placed[v][2][axis])) for v in views)
        edge = reach + REFERENCE_GAP
        for v in views:
            lo, hi = sorted((placed[v][1][axis], placed[v][2][axis]))
            shift = [0.0, 0.0, 0.0]
            if plane == 'front':
                shift[axis] = -edge - hi
                edge += hi - lo + REFERENCE_GAP
            else:
                shift[axis] = edge - lo
                edge += hi - lo + REFERENCE_GAP
            out[v] = tuple(shift)
    return out


def corners(cal, facing, size, mid_px=None):
    """(plane, lower-left, upper-right) of a view's image in model space: the lpk.stages.reference plane
    it stands in and where its corner pixels land through its calibration `cal` (lpk.core.views), in
    metres. facing: the view's ('front', 'back', 'left' or 'right'); a back view runs its pixels toward -X,
    a side view its pixels along Y as the calibration's side_y reads them. size: (width, height) in pixels;
    mid_px: a front or back view's midline column, None for the image centre."""
    w, h = size
    if facing in ('left', 'right'):
        return 'side', (0.0,) + cal.side(0, h), (0.0,) + cal.side(w, 0)
    mid = w / 2 if mid_px is None else mid_px
    flip = -1.0 if facing == 'back' else 1.0
    return 'front', (flip * cal.m(0 - mid), 0.0, cal.z(h)), (flip * cal.m(w - mid), 0.0, cal.z(0))


def blocks(M, P):
    """The shape blockout blocks(P) as '<NAME>_Blocks' (lpk.stages.blocks.build) in the model's palette."""
    from lpk.stages import blocks as blocks_mod
    n = names(M)
    return blocks_mod.build(n['blocks'], need(M, 'blocks')(P), need(M, 'PALETTE'), n['collection'])


def _write(M, b, name, collection=None):
    """Finish the builder `b` as the object `name` in `collection` (default the model's collection) with the
    model's palette and the painted marks it recorded (the bake's texel readings read them). Returns
    (the object, finish's report)."""
    from lpk.core import builder as builders
    from lpk.stages import texture
    marks = texture.marks_text(b)
    misses = dict(getattr(b, 'misses', None) or {})
    ob, rep = builders.finish(b, name, collection or names(M)['collection'], colours=need(M, 'PALETTE'))
    if marks is not None:
        ob[texture.MARKS] = marks
    if misses:
        rep['misses'] = misses
    return ob, rep


def guard(M, stage):
    """Raise ValueError when the scene's body '<NAME>' was changed since the kit wrote it (its build stamp,
    lpk.stages.zones.edited), naming what changed and the stage that keeps the change, for the model's mode:
    a topology edit belongs to freeze; moved vertices to capture_edits (parametric) or freeze (frozen); a
    body without a stamp was not written by the kit; under a frozen texture, UVs edited by hand belong to
    freeze_texture. Nothing is raised without a body."""
    from lpk.stages import zones
    n = names(M)
    if bpy.data.objects.get(n['body']) is None:
        return
    change = zones.edited(n['body'], uvs=texture_frozen(M))
    if change is None:
        return
    drop = 'or pass discard_edits=True to rebuild over it'
    if change == 'uv':
        raise ValueError("%s: the body's UVs were edited by hand under the frozen texture: run freeze_texture to "
                         "store the edit, %s" % (stage, drop))
    if change == 'unstamped':
        raise ValueError('%s: the body %s in the scene carries no build stamp, so the kit did not write it: rename '
                         'or remove it, %s' % (stage, n['body'], drop))
    if change == 'topology' and frozen(M):
        raise ValueError("%s: the body's topology was edited by hand: run freeze to store the edit, %s" % (stage, drop))
    if change == 'topology':
        raise ValueError("%s: the body's topology was edited by hand: topology edits belong to the frozen mode: run "
                         "freeze to keep the edit (it switches the model to frozen: set FROZEN = True), %s"
                         % (stage, drop))
    if frozen(M):
        raise ValueError('%s: vertices of the body were moved by hand and not stored: run freeze to store the moves, '
                         'or pass discard_edits=True to rebuild over them' % stage)
    raise ValueError('%s: vertices of the body were moved by hand and not stored: run capture_edits, or pass '
                     'discard_edits=True to rebuild over them' % stage)


def build(M, P, discard_edits=False):
    """The body '<NAME>' and each colour source '<NAME>_<source>' with the model's palette; the sources go
    into the collection '<NAME>_Sources' under the model's collection, excluded from the view layer (the
    bake paints them into the atlas, nothing else shows or exports them; lpk.core.builder.hidden_collection).
    An earlier rig '<NAME>_Rig' is removed, since the new body is not bound to it. Parametric mode: the body
    from build_mesh(P). Frozen mode (FROZEN = True): the body a copy of the frozen mesh '<NAME>_Frozen'
    (lpk.stages.zones.body_from_frozen), the sources from build_mesh(P) when SOURCES lists any (a model
    without SOURCES needs no build_mesh), each then carried from the parametric body build_mesh(P) makes
    (a temporary object, removed afterwards) onto the frozen body (lpk.stages.zones.conform_sources), so a
    painted layer follows a part reshaped there, unless its SOURCES entry sets 'conform': False. First
    guard refuses a body changed by hand since the kit wrote it, unless discard_edits; last the body is
    stamped. Under a frozen texture (TEXTURE_FROZEN = True) the frozen mesh's copy brings back the stored
    UV layer. Returns {'body': finish's report (lpk.core.builder.body_report), 'sources': {source:
    triangles}, 'frozen': the mode, 'texture_frozen': the texture mode}, in the frozen mode with sources
    'conform': {source: conform_sources' report, None for a source that does not conform}, and under a
    frozen texture 'uv_check': uv_check's report on the body's UVs. Raises
    ValueError for a 'conform' that is not True or False, and under a frozen texture for a frozen mesh
    without the stored UV layer."""
    from lpk.core import builder as builders
    from lpk.stages import texture, zones
    n = names(M)
    if frozen(M) and bpy.data.meshes.get(n['frozen']) is None:
        raise ValueError('build: the frozen mode (FROZEN = True) needs the frozen mesh %s in the open .blend: run '
                         'freeze or adopt first' % n['frozen'])
    if texture_frozen(M) and texture.UV_LAYER not in bpy.data.meshes[n['frozen']].uv_layers:
        raise ValueError('build: the frozen texture (TEXTURE_FROZEN = True) needs the UV layer %s on %s: run '
                         'freeze_texture (or adopt a textured model) first' % (texture.UV_LAYER, n['frozen']))
    specs = getattr(M, 'SOURCES', None) or {}
    bad = [k for k, spec in specs.items() if not isinstance(spec.get('conform', True), bool)]
    if bad:
        raise ValueError("SOURCES %s: 'conform' is True or False" % ', '.join(bad))
    if not discard_edits:
        guard(M, 'build')
    body, sources = _built(M, P) if specs or not frozen(M) else (None, {})
    old = bpy.data.objects.get(n['rig'])
    if old is not None:
        bpy.data.objects.remove(old, do_unlink=True)
    if frozen(M):
        _, rep = zones.body_from_frozen(n['frozen'], n['body'], n['collection'], need(M, 'PALETTE'))
    else:
        _, rep = _write(M, body, n['body'])
    builders.hidden_collection(n['sources'], n['collection'])
    tris = {}
    for key, b in sources.items():
        tris[key] = _write(M, b, n['source'](key), n['sources'])[1]['tris']
    out = {'body': rep, 'sources': tris, 'frozen': frozen(M), 'texture_frozen': texture_frozen(M)}
    if frozen(M) and sources:
        follow = [k for k in specs if specs[k].get('conform', True)]
        out['conform'] = {k: None for k in specs}
        if follow:
            ref = _write(M, body, n['body'] + '_SourceRef')[0]
            try:
                got = zones.conform_sources(ref.name, n['body'], texture.source_specs(
                    [dict(specs[k], object=n['source'](k)) for k in follow]))
            finally:
                _drop(ref)
            out['conform'].update({k: got[n['source'](k)] for k in follow})
        else:
            body.bm.free()
    zones.stamp(n['body'])
    if texture_frozen(M):
        out['uv_check'] = uv_check(M)
    return out


def _built(M, P):
    """build_mesh(P) checked: (body builder, {source: builder}) with a builder for every SOURCES key."""
    body, sources = need(M, 'build_mesh')(P)
    sources = dict(sources or {})
    missing = [k for k in getattr(M, 'SOURCES', {}) if k not in sources]
    if missing:
        raise ValueError('build_mesh made no colour source %s that SOURCES lists' % ', '.join(missing))
    return body, sources


def capture_edits(M, P):
    """The human's moves on the built body stored as data (lpk.core.edits.capture): a fresh build of the
    body is diffed against the scene's '<NAME>' and the offsets are added to the EDITS file; the body is
    stamped afterwards (its moves are stored). Parametric mode only. Raises ValueError in the frozen mode
    (freeze stores the edits there), and when the body's topology differs from a fresh build: a topology
    edit by hand belongs to freeze; a body whose stamp still matches it was built before the model's build
    changed. Returns capture's report."""
    from lpk.core import edits
    from lpk.stages import zones
    if frozen(M):
        raise ValueError('capture_edits is for the parametric mode: in the frozen mode run freeze')
    n = names(M)
    edited = require(M, 'capture_edits', 'body')['body']
    change = zones.edited(n['body'])
    path = folder(M, need(M, 'EDITS'))
    data = edits.load(path)
    body, sources = _built(M, P)
    for b in sources.values():
        b.bm.free()
    generated, _ = _write(M, body, n['body'] + '_EditGen')
    try:
        mine, fresh = zones.read(edited.data), zones.read(generated.data)
        if (zones.topology_key(len(mine['co']), mine['loop_total'], mine['loop_vert'])
                != zones.topology_key(len(fresh['co']), fresh['loop_total'], fresh['loop_vert'])):
            if change in ('topology', 'unstamped'):
                raise ValueError("capture_edits: the body's topology was edited by hand (%d vertices, a fresh build "
                                 "%d): topology edits belong to the frozen mode: run freeze to keep the edit (it "
                                 "switches the model to frozen: set FROZEN = True), or build with "
                                 "discard_edits=True to drop it" % (len(mine['co']), len(fresh['co'])))
            raise ValueError('capture_edits: the body is the topology the kit built, but a fresh build of the model '
                             'gives another (%d vertices, the body %d): the model changed since the body was built, '
                             'so the moves cannot be matched: capture before changing the build, or build with '
                             'discard_edits=True to drop them' % (len(fresh['co']), len(mine['co'])))
        rep = edits.capture(edited, generated, P, data)
    finally:
        bpy.data.objects.remove(generated, do_unlink=True)
    edits.save(path, data)
    zones.stamp(n['body'])
    return rep


def _reference(M, P, kind, name):
    """A temporary reference object `name` of the zones of kind 'frozen' (over a copy of the frozen mesh,
    lpk.stages.zones.reference_object) or 'parametric' (a fresh build of the body from build_mesh(P),
    finished into the model's collection). Remove it with _drop."""
    from lpk.stages import zones
    if kind == 'frozen':
        return zones.reference_object(names(M)['frozen'], name)
    body, sources = need(M, 'build_mesh')(P)
    for b in (sources or {}).values():
        b.bm.free()
    return _write(M, body, name)[0]


def _drop(ob):
    """Remove a temporary object made by _reference and its mesh."""
    me = ob.data
    bpy.data.objects.remove(ob, do_unlink=True)
    if me.users == 0:
        bpy.data.meshes.remove(me)


def freeze(M, P):
    """The scene's body '<NAME>', edited in any way, stored as the frozen mesh '<NAME>_Frozen'
    (lpk.stages.zones.freeze) and stamped. The zones come from the body's own layers when its topology is
    still the one the kit wrote (the stamp); else from the frozen mesh it replaces, or, on the first freeze,
    from a fresh parametric build (build_mesh(P)), by the nearest surface. freeze does not set FROZEN:
    the model's build stays parametric until its module sets FROZEN = True. Returns zones.freeze's report
    plus 'reference' ('body', 'frozen' or 'parametric'), 'uv_layer' (the UV layer stored with it under a
    frozen texture, else None; kept_uv), with that layer 'uv_check' (uv_check's report on the UVs the edit
    left), 'mode' (the model's mode as it stands) and, in the parametric mode, 'next': what switches build
    to the frozen mesh. Raises what kept_uv raises."""
    from lpk.stages import zones
    n = names(M)
    body = require(M, 'freeze', 'body')['body']
    change = zones.edited(body.name)
    kind = 'body' if change in (None, 'positions') else ('frozen' if bpy.data.meshes.get(n['frozen']) else 'parametric')
    ref = None if kind == 'body' else _reference(M, P, kind, n['body'] + '_ZoneRef')
    uv = kept_uv(M, 'freeze')
    try:
        rep = zones.freeze(n['body'], n['frozen'], None if ref is None else ref.name, uv=uv)
    finally:
        if ref is not None:
            _drop(ref)
    zones.stamp(n['body'])
    rep['reference'] = kind
    rep['uv_layer'] = uv
    if uv is not None:
        rep['uv_check'] = uv_check(M)
    rep.update(_mode(M))
    return rep


def _mode(M):
    """{'mode': the model's build mode} and, in the parametric mode, 'next': what makes build use the
    frozen mesh."""
    if frozen(M):
        return {'mode': 'frozen'}
    return {'mode': 'parametric',
            'next': 'set FROZEN = True in the model module: until then build stays parametric and rebuilds the '
                    'body from build_mesh; %s keeps the edit' % names(M)['frozen']}


def part_names(M, P):
    """The part names an adopted mesh's vertex groups and materials may carry, in this order: the parts of
    blocks(P), the parts of the SKELETON template's binding (lpk.skeletons.part_binding), and the parts
    ALLOWED, FIXED and JOINS name ('{s}' expanded), each once; the names the model defines."""
    from lpk import skeletons
    out = [part for _, part, _, _ in M.blocks(P)] if hasattr(M, 'blocks') else []
    template = getattr(M, 'SKELETON', None)
    if template:
        out += list(skeletons.part_binding(template))
        out += list(skeletons.sided(getattr(M, 'ALLOWED', {}), template))
        out += list(skeletons.sided(getattr(M, 'FIXED', {}), template))
        for parent, child, _ in skeletons.sided(list(getattr(M, 'JOINS', ())), template):
            out += [parent, child]
    return list(dict.fromkeys(out))


def adopt(M, P):
    """The frozen mesh '<NAME>_Frozen' made from the scene's mesh object ADOPT, an existing model
    (lpk.stages.zones.adopt): its parts from vertex groups or materials named like part_names(M, P), else
    from the nearest block of blocks(P); its colours from its materials, its texture or colour attribute
    nearest PALETTE. A textured mesh (a UV map and one image on its materials' Base Color) brings its
    frozen texture: the UV layer on '<NAME>_Frozen' and the image as '<NAME>_AtlasFrozen'. The object ADOPT
    is not changed; build in the frozen mode makes the body from the frozen mesh. An untextured mesh leaves
    no frozen texture: an earlier '<NAME>_AtlasFrozen' is removed, since it belonged to the mesh adopt
    replaces. Returns zones.adopt's report plus 'mode' and, in the parametric mode, 'next', as freeze gives
    them, and the texture mode (_texture_mode)."""
    from lpk.stages import zones
    n = names(M)
    blocks_list = M.blocks(P) if hasattr(M, 'blocks') else None
    rep = zones.adopt(need(M, 'ADOPT'), n['frozen'], part_names(M, P), need(M, 'PALETTE'), blocks_list,
                      texture=n['atlas_frozen'])
    if rep['texture'] is None:
        old = bpy.data.images.get(n['atlas_frozen'])
        if old is not None:
            bpy.data.images.remove(old)
    rep.update(_mode(M))
    rep.update(_texture_mode(M, rep['texture'] is not None))
    return rep


def _texture_mode(M, stored):
    """{'texture_mode': 'frozen' or 'procedural'} and, when a frozen texture is `stored` and the module's
    texture is procedural, 'texture_next': what makes the stages use it."""
    if texture_frozen(M):
        return {'texture_mode': 'frozen'}
    out = {'texture_mode': 'procedural'}
    if stored:
        out['texture_next'] = ('set TEXTURE_FROZEN = True in the model module (with FROZEN = True), then build: '
                               'until then unwrap, pack and bake make the texture again and the frozen one waits '
                               'in the .blend')
    return out


def _atlas_args(M, P):
    """The keyword arguments unwrap, pack_step and bake share: the face island and the strips."""
    face_pred = getattr(M, 'face_pred', None)
    return {'face_part': getattr(M, 'FACE_PART', None), 'face_pred': face_pred(P) if face_pred else None,
            'strips': getattr(M, 'STRIPS', None), 'own': getattr(M, 'OWN', None)}


def refuse_frozen_texture(M, stage):
    """Raise ValueError naming `stage` under a frozen texture: unwrap and pack would replace the frozen UVs."""
    if texture_frozen(M):
        raise ValueError('%s: the texture is frozen (TEXTURE_FROZEN = True): unwrap and pack would replace the frozen '
                         'UVs; run unfreeze_texture first' % stage)


def unwrap(M, P):
    """The atlas UVs of the body, not packed (lpk.stages.texture.unwrap), with seams(P) when the model
    gives it ({'cuts', 'panels', 'hard'}, any of them), else smart projection; the UV digest leaves the
    body's build stamp (lpk.stages.zones.unstamp_uv), as these UVs are the kit's. Returns unwrap's report.
    Raises ValueError under a frozen texture (refuse_frozen_texture)."""
    from lpk.stages import texture, zones
    refuse_frozen_texture(M, 'unwrap')
    require(M, 'unwrap', 'body')
    seams = M.seams(P) if hasattr(M, 'seams') else {}
    bad = sorted(set(seams) - {'cuts', 'panels', 'hard'})
    if bad:
        raise ValueError('seams(P) gives %s: use cuts, panels, hard' % ', '.join(bad))
    rep = texture.unwrap(names(M)['body'], need(M, 'sheet_of'), need(M, 'ATLAS'), boost=getattr(M, 'BOOST', None),
                         **_atlas_args(M, P), **seams)
    zones.unstamp_uv(names(M)['body'])
    return rep


def packs(M, P, count, rescale):
    """Up to `count` packs (pack), the first with `rescale`, the later ones rescaling, stopping after the
    first rescaling pack that settles the face island (lpk.stages.texture.pack_settled); a pack that does
    not rescale never settles it, since the island has not been sized yet. Without a face island
    ('face_area' None) the first pack is final and settled. Returns their reports, each with 'settled'."""
    from lpk.stages import texture
    out = []
    for i in range(count):
        scaled = rescale if i == 0 else True
        r = pack(M, P, rescale=scaled)
        r['settled'] = (bool(scaled) or r['face_area'] is None) and texture.pack_settled(r)
        out.append(r)
        if r['settled']:
            break
    return out


def pack(M, P, rescale=True):
    """One pack of the body's atlas (lpk.stages.texture.pack_step) toward the face island's FACE_AREA or
    FACE_TEXELS, through the pack cache out/<NAME>.pack.json. Returns pack_step's report. Raises ValueError
    under a frozen texture (refuse_frozen_texture)."""
    from lpk.stages import texture, zones
    refuse_frozen_texture(M, 'pack')
    require(M, 'pack', 'uv')
    n = names(M)
    rep = texture.pack_step(n['body'], need(M, 'sheet_of'), need(M, 'ATLAS'), face_area=getattr(M, 'FACE_AREA', None),
                            face_texels=getattr(M, 'FACE_TEXELS', None), rescale=rescale,
                            cache=out(M, n['body'] + '.pack.json'), **_atlas_args(M, P))
    zones.unstamp_uv(n['body'])
    return rep


def bake(M, P, discard_edits=False):
    """The colour atlas '<NAME>_Atlas', saved as out/<NAME>_Atlas.png and stamped with its texel digest
    (lpk.stages.texture.stamp_image), with the print grit of GRIT when the model gives it (None or absent:
    flat colours; else an (r, g, b) or (r, g, b, a) colour, each channel 0 to 1, multiplied in a sparse
    object-space noise; lpk.stages.texture.GRIT is one).

    Procedural texture: baked on the packed UVs (lpk.stages.texture.bake): the body's colours and the
    SOURCES painted over them in their order, each source within its 'mask' parts. Frozen texture
    (TEXTURE_FROZEN = True): the frozen atlas '<NAME>_AtlasFrozen' with only the SOURCES whose entry sets
    'over': True composited over it, every other texel kept (lpk.stages.texture.bake_over); first the
    atlas in the scene is checked against its stamp: one painted by hand since the kit wrote it raises
    (freeze_texture stores the paint), unless discard_edits.

    VARIANTS (variant_palettes): before the atlas, each variant baked the same way from its palette into
    the image '<NAME>_Atlas_<variant>', saved as out/<NAME>_Atlas_<variant>.png on the same UVs; its working
    material is removed, so the body keeps the atlas's.

    Raises ValueError for a GRIT that is not such a colour, an 'over' that is not True or False, VARIANTS
    variant_palettes refuses and VARIANTS under a frozen texture. Returns bake's or bake_over's result, the
    former with 'variants': {variant: its PNG's path}, the latter with 'uv_check': uv_check's report on the
    body's UVs."""
    from lpk.stages import texture
    require(M, 'bake', 'uv')
    n = names(M)
    grit = _grit(M)
    variants = variant_palettes(M)
    if variants and texture_frozen(M):
        raise ValueError('bake: VARIANTS recolour the palette, which a frozen texture (TEXTURE_FROZEN = True) does '
                         'not bake from: drop VARIANTS, or unfreeze the texture')
    specs = getattr(M, 'SOURCES', {})
    bad = [k for k, spec in specs.items() if not isinstance(spec.get('over', False), bool)]
    if bad:
        raise ValueError("SOURCES %s: 'over' is True or False" % ', '.join(bad))
    sources = [dict({'object': n['source'](key)}, **spec) for key, spec in specs.items()]
    if texture_frozen(M):
        if bpy.data.images.get(n['atlas_frozen']) is None:
            raise ValueError('bake: the frozen texture (TEXTURE_FROZEN = True) needs the image %s in the open .blend: '
                             'run freeze_texture (or adopt a textured model) first' % n['atlas_frozen'])
        change = None if discard_edits else texture.image_edited(n['atlas'])
        if change is not None:
            raise ValueError('bake: the atlas %s was painted by hand since the kit wrote it (%s): run freeze_texture '
                             'to keep the paint, or pass discard_edits=True to bake over it'
                             % (n['atlas'], 'no stamp' if change == 'unstamped' else 'its texels changed'))
        rep = texture.bake_over(n['body'], n['atlas_frozen'], [s for s in sources if s.get('over')],
                                colours=need(M, 'PALETTE'), own=getattr(M, 'OWN', None), grit=grit,
                                material=getattr(M, 'MATERIAL', 'base'), save_dir=out(M))
        rep['uv_check'] = uv_check(M)
    else:
        done = {}
        for variant, colours in variants.items():
            image = '%s_%s' % (n['atlas'], variant)
            vrep = texture.bake(n['body'], need(M, 'sheet_of'), need(M, 'ATLAS'), sources=sources, colours=colours,
                                grit=grit, material=getattr(M, 'MATERIAL', 'base'), save_dir=out(M), image=image,
                                **_atlas_args(M, P))
            done[variant] = vrep['files'][0]
            if bpy.data.materials.get(image) is not None:
                bpy.data.materials.remove(bpy.data.materials[image])
        rep = texture.bake(n['body'], need(M, 'sheet_of'), need(M, 'ATLAS'), sources=sources,
                           colours=need(M, 'PALETTE'), grit=grit, material=getattr(M, 'MATERIAL', 'base'),
                           save_dir=out(M), **_atlas_args(M, P))
        rep['variants'] = done
    texture.stamp_image(n['atlas'])
    return rep


def variant_palettes(M):
    """The palettes of the model's VARIANTS, {variant: PALETTE with that variant's colours replaced}, in
    VARIANTS order ({} without VARIANTS). VARIANTS: {name: {palette name: sRGB (r, g, b)}}, each variant
    recolouring some of PALETTE's names, the rest kept. Raises ValueError for a variant name that is not
    a non-empty word of letters, digits and underscores (it names an image and a file), a variant naming a
    colour PALETTE lacks, and a colour that is not three channels from 0 to 1."""
    palette = dict(getattr(M, 'PALETTE', {}))
    out_, problems = {}, []
    for variant, colours in dict(getattr(M, 'VARIANTS', {})).items():
        if not (isinstance(variant, str) and variant and all(c.isalnum() or c == '_' for c in variant)):
            problems.append('VARIANTS[%r]: name a variant with letters, digits and underscores' % (variant,))
            continue
        unknown = [c for c in colours if c not in palette]
        if unknown:
            problems.append('VARIANTS[%r]: %s not in PALETTE' % (variant, ', '.join(map(repr, unknown))))
        bad = [c for c, v in colours.items()
               if not (len(tuple(v)) == 3 and all(isinstance(x, (int, float)) and 0.0 <= x <= 1.0 for x in v))]
        if bad:
            problems.append('VARIANTS[%r]: %s must be (r, g, b), each 0 to 1' % (variant, ', '.join(map(repr, bad))))
        out_[variant] = dict(palette, **{c: tuple(v) for c, v in colours.items()})
    if problems:
        raise ValueError('\n'.join(problems))
    return out_


def _grit(M):
    """The model's GRIT as a tuple, None without it. Raises ValueError for a GRIT that is not None or an
    (r, g, b) or (r, g, b, a) colour, each channel 0 to 1."""
    grit = getattr(M, 'GRIT', None)
    if grit is not None and (len(tuple(grit)) not in (3, 4) or not all(0.0 <= float(c) <= 1.0 for c in grit)):
        raise ValueError('GRIT %r: use None or an (r, g, b) or (r, g, b, a) colour, each channel 0 to 1' % (grit,))
    return None if grit is None else tuple(grit)


def uv_size(M):
    """(width, height) in texels of the atlas the model's UVs are read on: the frozen atlas
    '<NAME>_AtlasFrozen' when the .blend holds it, else the atlas '<NAME>_Atlas', else ATLAS's size."""
    n = names(M)
    for key in ('atlas_frozen', 'atlas'):
        img = bpy.data.images.get(n[key])
        if img is not None:
            return int(img.size[0]), int(img.size[1])
    side = int(need(M, 'ATLAS')[0])
    return side, side


def uv_check(M):
    """The UV check of the scene's body (lpk.stages.texture.uv_check) on the atlas of uv_size, the parts of
    OWN left out: per part the faces whose UVs are broken and why. Returns its report."""
    from lpk.stages import texture
    return texture.uv_check(names(M)['body'], uv_size(M), own=tuple(getattr(M, 'OWN', None) or ()))


def freeze_texture(M, P):
    """The frozen texture stored from the scene, as it stands: the body's atlas UV layer
    (lpk.stages.texture.UV_LAYER) written onto the frozen mesh '<NAME>_Frozen' (lpk.stages.zones.store_uv)
    and a copy of the atlas image '<NAME>_Atlas' as '<NAME>_AtlasFrozen', packed into the .blend with a fake
    user (lpk.stages.texture.store_image): UVs edited in the UV editor and texels painted in Texture Paint
    are what is stored. The atlas and the body are stamped afterwards (their edits are stored). The frozen
    mesh mode only (FROZEN = True), on a body of the frozen mesh's topology. freeze_texture does not set
    TEXTURE_FROZEN: until the module sets it, unwrap, pack and bake make the texture again.

    Returns {'image': '<NAME>_AtlasFrozen', 'size': [width, height], 'packed', 'uv_layer', 'loops': the
    loops whose UVs were stored, 'islands': the UV islands (lpk.stages.texture.island_count)} and
    _texture_mode's keys. Raises ValueError in the parametric mode, without a body with the atlas UV
    layer, without the atlas image (run bake first), and for a body whose topology is not the frozen
    mesh's (run freeze first)."""
    from lpk.stages import texture, zones
    if not frozen(M):
        raise ValueError('freeze_texture: the frozen texture lives on the frozen mesh: freeze the model and set '
                         'FROZEN = True first')
    n = names(M)
    require(M, 'freeze_texture', 'uv')
    if bpy.data.images.get(n['atlas']) is None:
        raise ValueError('freeze_texture: no atlas image %s in the scene: run bake first' % n['atlas'])
    uv = zones.store_uv(n['body'], n['frozen'], texture.UV_LAYER)
    stored = texture.store_image(n['atlas'], n['atlas_frozen'])
    texture.stamp_image(n['atlas'])
    zones.stamp(n['body'])
    rep = {'image': stored['image'], 'size': stored['size'], 'packed': stored['packed'], 'uv_layer': uv['layer'],
           'loops': uv['loops'], 'islands': texture.island_count(n['body'])}
    rep.update(_texture_mode(M, True))
    return rep


def unfreeze_texture(M, P):
    """The frozen texture removed, on the human's explicit request: the image '<NAME>_AtlasFrozen' and the
    stored UV layer on '<NAME>_Frozen' (lpk.stages.zones.drop_uv). The atlas '<NAME>_Atlas' and the body's
    UVs stay as they stand until the next unwrap, pack and bake make them again from the model. Returns
    {'removed': {'image': its name or None, 'uv_layer': its name or None}, 'lost': what the removal loses,
    'texture_mode': the module's} and, while the module still sets TEXTURE_FROZEN, 'texture_next': the
    module change that lets unwrap, pack and bake run again."""
    from lpk.stages import texture, zones
    n = names(M)
    img = bpy.data.images.get(n['atlas_frozen'])
    removed = {'image': None, 'uv_layer': zones.drop_uv(n['frozen'], texture.UV_LAYER)}
    if img is not None:
        bpy.data.images.remove(img)
        removed['image'] = n['atlas_frozen']
    lost = ('nothing: no frozen texture was stored' if removed == {'image': None, 'uv_layer': None} else
            'the frozen texture is gone: every hand edit to the atlas (Texture Paint) and to the UVs it held is '
            'lost; the next unwrap, pack and bake make the UVs and the atlas again from the model')
    rep = {'removed': removed, 'lost': lost}
    if getattr(M, 'TEXTURE_FROZEN', False):
        rep.update({'texture_mode': 'frozen', 'texture_next': 'set TEXTURE_FROZEN = False (or remove it) in the model '
                    'module: until then build, unwrap, pack and bake refuse'})
    else:
        rep['texture_mode'] = 'procedural'
    return rep


def influences(M):
    """The bones per vertex the weights keep: the smallest influence limit of the model's EXPORTS
    profiles (lpk.profiles), the rig kernel's default without EXPORTS."""
    from lpk.stages import rig
    limits = [_profile(M, p).get('influence_limit') for p in getattr(M, 'EXPORTS', ())]
    limits = [x for x in limits if x]
    return min(limits) if limits else rig.MAX_INFLUENCES


def _profile(M, name):
    """The export profile `name`: a shipped profile name, or a JSON path relative to the model's folder."""
    from lpk import profiles
    return profiles.load(folder(M, name) if name.endswith('.json') else name)


def rig(M, P, backend=None):
    """The rig '<NAME>_Rig' of the template SKELETON at the joints bones(P) (lpk.stages.rig.build_rig,
    extra_bones(P) for the model's own) and the body's weights (lpk.stages.rig.skin): the template's part
    binding (lpk.skeletons.part_binding) updated by ALLOWED, FIXED rigid parts, JOINS smoothed, '{s}'
    expanded per side in each; the backend `backend`, else WEIGHTS, else 'auto'; the influence limit of
    influences(M). Returns {'rig': build_rig's report, 'skin': skin's report}."""
    from lpk import skeletons
    from lpk.stages import rig as rig_mod
    require(M, 'rig', 'body')
    n = names(M)
    template = need(M, 'SKELETON')
    extra = M.extra_bones(P) if hasattr(M, 'extra_bones') else None
    rep = rig_mod.build_rig(n['body'], n['rig'], template, need(M, 'bones')(P), extra)
    bones = [b.name for b in bpy.data.objects[n['rig']].data.bones]
    allowed = dict(skeletons.part_binding(template, bones))
    allowed.update(skeletons.sided(getattr(M, 'ALLOWED', {}), template))
    fixed = skeletons.sided(getattr(M, 'FIXED', {}), template)
    joins = skeletons.sided(list(getattr(M, 'JOINS', ())), template)
    skin = rig_mod.skin(n['body'], n['rig'], allowed, fixed=fixed or None, joins=joins or None,
                        backend=backend or getattr(M, 'WEIGHTS', 'auto'), influences=influences(M))
    return {'rig': rep, 'skin': skin}


def preview(M, P):
    """The baked atlas shown on the body in the PREVIEW look (lpk.stages.preview.preview_atlas, default
    'neutral'), saved as out/<NAME>_Atlas_preview.png. Returns preview_atlas' report."""
    from lpk.stages import preview as preview_mod
    require(M, 'preview', 'body')
    n = names(M)
    return preview_mod.preview_atlas(n['body'], n['atlas'], n['atlas'] + 'File', n['body'] + '_Preview',
                                     out(M, n['atlas'] + '_preview.png'), getattr(M, 'PREVIEW', 'neutral'))


def pose_test(M, P):
    """The rig in TEST_POSE ({bone: pose entry}, lpk.stages.pose.set_pose). Returns the names the
    rig lacks."""
    from lpk.stages import pose
    require(M, 'pose_test', 'rig')
    return {'missing': pose.set_pose(names(M)['rig'], need(M, 'TEST_POSE'))}


def pose_rest(M, P):
    """The rig back in its rest pose."""
    from lpk.stages import pose
    require(M, 'pose_rest', 'rig')
    return {'missing': pose.set_pose(names(M)['rig'], None)}


def export(M, P):
    """One file per EXPORTS profile (lpk.stages.export.export_output) in EXPORT_DIR (relative to the
    model's folder, default out/), named '<NAME>_<profile>', each re-imported and compared with the model.
    A model with SKELETON goes out with its rig '<NAME>_Rig', one without as its body alone. The atlas of
    each of VARIANTS, baked as out/<NAME>_Atlas_<variant>.png, goes beside the files as a PNG of that name
    whatever the profile's textures: no material in the file uses it, the engine swaps it in. Raises
    ValueError for a variant whose atlas the bake has not written. Returns {profile: export_output's report
    plus 'variants': the variant PNGs' paths beside the file}."""
    import shutil
    from lpk.stages import export as export_mod
    rigged = hasattr(M, 'SKELETON')
    require(M, 'export', 'body', *(('rig',) if rigged else ()))
    n = names(M)
    target = folder(M, M.EXPORT_DIR) if getattr(M, 'EXPORT_DIR', None) else out(M)
    os.makedirs(target, exist_ok=True)
    variants = []
    for variant in variant_palettes(M):
        png = '%s_%s.png' % (n['atlas'], variant)
        source = os.path.join(out(M), png)
        if not os.path.isfile(source):
            raise ValueError('export: no atlas %s for the variant %r: run bake' % (source, variant))
        dest = os.path.join(target, png)
        if os.path.abspath(dest) != os.path.abspath(source):
            shutil.copyfile(source, dest)
        variants.append(dest)
    report = {}
    for profile in need(M, 'EXPORTS'):
        stem = os.path.splitext(os.path.basename(profile))[0]
        report[profile] = export_mod.export_output(n['body'], n['rig'] if rigged else None, target,
                                                   n['body'] + '_' + stem, _profile(M, profile))
        report[profile]['variants'] = list(variants)
    return report


# -- review calls -----------------------------------------------------------------------------------------

# The frames clip() shows of a clip by default, spread over its action.
CLIP_FRAMES = 6

def capture(path, tag='build', shade='color', views=('front', 'side', 'q34', 'back'), objects=None, part=None):
    """Captures of the model framed on its body (lpk.stages.review.capture over body_views) as
    out/captures/<tag>_<view>.png. shade: lpk.stages.view.set_view's ('color', 'tex', 'material', ...);
    objects: the only meshes shown, default the body ('<NAME>_Blocks' for the blockout). part: a part of
    the body to show alone instead, cut out of the posed body by lpk.stages.review.isolate into
    '<NAME>_Part', framed on itself and captured as out/captures/<tag>_<part>_<view>.png; the copy is
    removed afterwards (part_capture). Returns the paths."""
    from lpk.stages import review
    M = load(path)
    n = names(M)
    if part is not None:
        return part_capture(M, part, tag, shade, views)
    shown = list(objects or [n['body']])
    return review.capture(out(M, 'captures'), tag, review.body_views(shown[0], views, getattr(M, 'EYE', None)),
                          shade=shade, keep=shown)


def part_capture(M, part, tag, shade, views):
    """capture of one part: the copy review.isolate cuts out ('<NAME>_Part' in the model's collection),
    its views (review.body_views on the copy), the capture keeping only the copy, and the copy and its mesh
    removed afterwards, also when the capture raises. Returns the paths."""
    from lpk.stages import review
    n = names(M)
    require(M, 'capture', 'body')
    copy = review.isolate(n['body'], part, out_name=n['body'] + '_Part', collection=n['collection'])
    try:
        return review.capture(out(M, 'captures'), '%s_%s' % (tag, part), review.body_views(copy.name, views),
                              shade=shade, keep=[copy.name])
    finally:
        me = copy.data
        bpy.data.objects.remove(copy, do_unlink=True)
        if me.users == 0:
            bpy.data.meshes.remove(me)


def poses(path, names_=None, views=('front', 'q34', 'side')):
    """The rigged body in the review poses (review_poses) on one sheet, out/captures/poses/poses.png
    (lpk.stages.review.pose_captures); names_: the poses to show, default all; views: the sheet's rows,
    'eye' among them for a model with EYE. Returns pose_captures' report."""
    from lpk.stages import review
    M = load(path)
    n = names(M)
    every = review_poses(M)
    chosen = {k: every[k] for k in (names_ or every)}
    return review.pose_captures(n['body'], n['rig'], out(M, 'captures', 'poses'), chosen, views=views,
                                eye=getattr(M, 'EYE', None))


def review_poses(M):
    """The review poses of a model, {name: {bone: pose entry}}: the SKELETON template's
    (lpk.skeletons.poses), then the model's POSES, then its TEST_POSE as 'test'. Raises ValueError for a
    POSES name the template or 'test' already takes."""
    from lpk import skeletons
    every = skeletons.poses(need(M, 'SKELETON'))
    own = dict(getattr(M, 'POSES', {}))
    clash = [k for k in own if k in every or k == 'test']
    if clash:
        raise ValueError('POSES names %s, which the template %r or TEST_POSE already takes: rename them'
                         % (', '.join(map(repr, clash)), M.SKELETON))
    every.update(own)
    if hasattr(M, 'TEST_POSE'):
        every['test'] = M.TEST_POSE
    return every


def clip(path, clip_path, bone_map=None, frames=None, count=CLIP_FRAMES, ground=None, hips_scale=None, sway=None,
         views=('front', 'q34', 'side')):
    """Frames of a clip of another skeleton on the model's rig, on one sheet (lpk.stages.clips over
    lpk.stages.review.pose_captures): out/captures/clips/<clip file stem>/poses.png, a frame per column.
    Nothing is keyed on the rig and the clip leaves the scene again.

    clip_path: an .fbx, .glb or .gltf file, absolute or relative to the model's folder. bone_map: {rig bone:
    (clip bone, 'delta' or 'dir')} (lpk.stages.clips); None lists the clip instead of sampling it. frames:
    the clip's frames to show, by default `count` spread evenly over its action from the first frame to
    the last. ground: parts of the body to plant on the floor in every frame (lpk.stages.clips.plant), None
    to keep the clip's own heights. hips_scale: the root's travel factor (clips.sample's default without
    it). sway: keyword arguments of lpk.stages.clips.tail_sway, turning the bones the map leaves out on
    that wave, None for none. views: the sheet's rows.

    Returns, without bone_map, {'bones': the clip's bone names, 'frames': its (first, last) frame}; with it,
    pose_captures' report plus 'frames' (the frames shown), 'mapped', 'unmapped', 'anchor' and 'turn'
    (clips.sample's) and 'ground_shift' (plant's range, None without ground). Raises ValueError for a
    missing rig and with the bone map's problems (clips.map_problems)."""
    from lpk.stages import clips, review
    M = load(path)
    n = names(M)
    require(M, 'clip', 'body', 'rig')
    source = clip_path if os.path.isabs(clip_path) else folder(M, clip_path)
    loaded = clips.load_clip(source)
    try:
        if bone_map is None:
            return {'bones': loaded['bones'], 'frames': loaded['frames']}
        first, last = loaded['frames']
        shown = list(frames) if frames else sorted({round(first + (last - first) * i / max(count - 1, 1))
                                                    for i in range(count)})
        sampled = clips.sample(loaded['armature'], n['rig'], shown, bone_map, hips_scale,
                               extra=clips.tail_sway(**sway) if sway is not None else None)
    finally:
        clips.remove_clip(loaded)
    poses = sampled['poses']
    shift = clips.plant(n['body'], n['rig'], poses, sampled['root'], list(ground)) if ground else None
    base = os.path.splitext(os.path.basename(source))[0]
    stem = ''.join(c if c.isalnum() or c in '-_' else '_' for c in base)
    rep = review.pose_captures(n['body'], n['rig'], out(M, 'captures', 'clips', stem),
                               {'f%04d' % f: poses[f] for f in shown}, views=views, eye=getattr(M, 'EYE', None))
    return dict(rep, frames=shown, mapped=sampled['mapped'], unmapped=sampled['unmapped'], anchor=sampled['anchor'],
                turn=sampled['turn'], ground_shift=shift)


def joins(path, pose='test'):
    """How `pose` (a review pose's name, review_poses, or {bone: pose entry})
    deforms each of the model's JOINS (lpk.stages.review.join_metrics). Two joins whose zones share vertices (the
    leg holes of a crotch seam) both read the deformation there: a leg the pose leaves still shows the
    stretch of the other at the seam; its loop_cm stays its own. Returns join_metrics' report."""
    from lpk import skeletons
    from lpk.stages import review
    M = load(path)
    n = names(M)
    template = need(M, 'SKELETON')
    if pose == 'test':
        pose = need(M, 'TEST_POSE')
    elif isinstance(pose, str):
        every = review_poses(M)
        if pose not in every:
            raise ValueError("pose %r: give a review pose (%s) or {bone: pose entry}" % (pose, ', '.join(every)))
        pose = every[pose]
    pairs = [{'parent': p, 'child': c, 'caps': caps}
             for p, c, caps in skeletons.sided(list(need(M, 'JOINS')), template)]
    return review.join_metrics(n['body'], n['rig'], pose, pairs)


def zones(path, reference=None):
    """The body by part (lpk.stages.zones.summary): counts, bounds, neighbours, mirror twin, uncoloured
    faces, and the deviation of each part from a reference: 'frozen' the frozen mesh '<NAME>_Frozen',
    'parametric' a fresh build from build_mesh(P) (the model's measurements and stored edits), None no
    reference. The reference object is temporary and removed afterwards. Returns summary's report."""
    from lpk.stages import zones as zones_mod
    if reference not in (None, 'frozen', 'parametric'):
        raise ValueError("reference %r: use 'frozen', 'parametric' or None" % (reference,))
    M = load(path)
    n = names(M)
    require(M, 'zones', 'body')
    if reference is None:
        return zones_mod.summary(n['body'])
    P = None
    if reference == 'parametric':
        P = M.props()
        P['edits'] = edits_data(M)
    ref = _reference(M, P, reference, n['body'] + '_ZoneRef')
    try:
        return zones_mod.summary(n['body'], ref.name)
    finally:
        _drop(ref)


def assign(path, part, selection='faces'):
    """The part `part` given to what the human selected on the body (lpk.stages.zones.assign: the
    selected faces' vertices, or the selected vertices with selection='verts'). Returns assign's report."""
    from lpk.stages import zones as zones_mod
    M = load(path)
    require(M, 'assign', 'body')
    return zones_mod.assign(names(M)['body'], part, selection)


def paint(path, colour, selection='faces'):
    """The palette colour `colour` (a PALETTE name) given to the selected faces of the body
    (lpk.stages.zones.paint), its corner colours painted again from PALETTE. Returns paint's report."""
    from lpk.stages import zones as zones_mod
    M = load(path)
    require(M, 'paint', 'body')
    palette = need(M, 'PALETTE')
    if colour not in palette:
        raise ValueError('paint: %r is no PALETTE colour; use %s' % (colour, ', '.join(palette)))
    return zones_mod.paint(names(M)['body'], colour, selection, colours=palette)


def select(path, part):
    """The part `part` of the body selected for the human to edit (lpk.stages.zones.select). Returns
    select's report."""
    from lpk.stages import zones as zones_mod
    M = load(path)
    require(M, 'select', 'body')
    return zones_mod.select(names(M)['body'], part)


def check_uvs(path):
    """The UV check of the model's body (uv_check): per part the faces whose atlas UVs are broken, with the
    reason: no UV area ('zero'), a corner outside the atlas ('outside'), an overlap with a larger island of
    another part ('overlap'), a texel density far from the faces round it in its island ('density', with
    each face's 'ratio'); lpk.stages.zones.uv_faults states the limits. It reads the body as it stands,
    after a hand edit as after a stage, and changes nothing. Returns lpk.stages.zones.uv_report's report."""
    M = load(path)
    require(M, 'check_uvs', 'uv')
    return uv_check(M)


def repair_uvs(path, parts=None):
    """The faces whose UVs the UV check lists (only those of `parts`, a list of part names, when given)
    repaired under a frozen texture, on the human's request (lpk.stages.texture.repair_uvs): new islands
    in free atlas space at their part's texel density, existing islands kept where they are, the faces
    baked into the frozen atlas '<NAME>_AtlasFrozen' and the atlas '<NAME>_Atlas' (their palette colours
    and every SOURCES entry within its mask, from the source objects build made; PALETTE, OWN and GRIT as
    the bake reads them), every texel outside the new islands' cells kept, the atlas saved again as
    out/<NAME>_Atlas.png. Then the frozen texture is stored as freeze_texture stores it: the body's UVs on
    '<NAME>_Frozen' (lpk.stages.zones.store_uv), and the body and the atlas stamped.

    When the free space cannot hold every new island nothing changes, and the report's 'next' names the way
    out: unfreeze_texture, which loses the hand edits the frozen texture holds. Returns
    lpk.stages.texture.repair_uvs' report plus, after a repair, 'stored': store_uv's {'layer', 'loops',
    'uv'}. Raises ValueError without TEXTURE_FROZEN = True, without the body's UVs, the frozen atlas or a
    colour source build makes, when the body's mesh changed since the kit wrote it (freeze stores the edit
    first), and when the atlas was painted by hand since its stamp (freeze_texture stores the paint first)."""
    from lpk.stages import texture, zones as zones_mod
    M = load(path)
    if not texture_frozen(M):
        raise ValueError('repair_uvs: the UV repair writes the frozen texture: freeze it and set TEXTURE_FROZEN = True '
                         '(with FROZEN = True) first')
    n = names(M)
    require(M, 'repair_uvs', 'uv')
    if bpy.data.images.get(n['atlas_frozen']) is None:
        raise ValueError('repair_uvs: no frozen atlas %s in the open .blend: run freeze_texture first'
                         % n['atlas_frozen'])
    change = zones_mod.edited(n['body'], uvs=True)
    if change not in (None, 'uv'):
        raise ValueError("repair_uvs: the body's mesh was changed since the kit wrote it (%s): run freeze to store the "
                         "edit first" % change)
    painted = texture.image_edited(n['atlas'])
    if painted is not None:
        raise ValueError('repair_uvs: the atlas %s was painted by hand since the kit wrote it (%s): run freeze_texture '
                         'to keep the paint first' % (n['atlas'], 'no stamp' if painted == 'unstamped' else
                                                     'its texels changed'))
    specs = getattr(M, 'SOURCES', None) or {}
    missing = [n['source'](k) for k in specs if bpy.data.objects.get(n['source'](k)) is None]
    if missing:
        raise ValueError('repair_uvs: no colour source %s in the scene: run build first' % ', '.join(missing))
    if parts is not None:
        parts = [str(p) for p in parts]
    rep = texture.repair_uvs(n['body'], n['atlas_frozen'], n['atlas'],
                             [dict({'object': n['source'](k)}, **spec) for k, spec in specs.items()],
                             colours=need(M, 'PALETTE'), own=getattr(M, 'OWN', None), grit=_grit(M), parts=parts,
                             save_dir=out(M))
    if not rep['placed']:
        rep['next'] = ('no free atlas space holds the new islands of the charts without a cell: nothing changed. The '
                       'way out is unfreeze_texture, on the human\'s word: it loses the hand edits the frozen texture '
                       'holds, and unwrap, pack and bake then make the UVs and the atlas again from the model')
    elif rep['faces']:
        rep['stored'] = zones_mod.store_uv(n['body'], n['frozen'], texture.UV_LAYER)
        zones_mod.stamp(n['body'])
    return rep


def operate(M, operation, tool):
    """One zone operation on the body '<NAME>' of a frozen model, stored: `tool` (a function of the body's
    name returning a lpk.stages.zones operation report) changes the body, then the body is stored as the
    frozen mesh '<NAME>_Frozen' with the zone layers the operation wrote (lpk.stages.zones.freeze with the
    body as its own reference; the body's UV layer too under a frozen texture, kept_uv) and stamped, so one
    call is one stored change. Returns the tool's report
    with 'freeze': zones.freeze's report and, under a frozen texture, 'uv_check' (uv_check's report on the
    UVs the operation left). Raises ValueError in the parametric mode, without a body, and when
    the body's topology was changed by hand since the kit wrote it (its layers would be Blender's
    interpolation, not the zones): freeze stores that edit first; and what kept_uv raises."""
    from lpk.stages import zones as zones_mod
    if not frozen(M):
        raise ValueError('zone operations change the frozen mesh: freeze the model first (FROZEN = True)')
    n = names(M)
    require(M, operation, 'body')
    change = zones_mod.edited(n['body'])
    if change in ('topology', 'unstamped'):
        raise ValueError("%s: the body's topology was changed since the kit wrote it: run freeze first to store "
                         "the edit, or build with discard_edits=True to drop it" % operation)
    uv = kept_uv(M, operation)
    rep = tool(n['body'])
    rep['freeze'] = zones_mod.freeze(n['body'], n['frozen'], uv=uv)
    zones_mod.stamp(n['body'])
    if uv is not None:
        rep['uv_check'] = uv_check(M)
    return rep


def transform(path, part, translate=(0.0, 0.0, 0.0), rotate=(0.0, 0.0, 0.0), scale=1.0, pivot='centre', falloff=2):
    """The part `part` of a frozen model's body moved, turned and scaled (lpk.stages.zones.transform:
    translate in m, rotate in degrees XYZ, scale one factor or (x, y, z), pivot 'centre', 'base' or a point
    in m, the other parts' vertices within `falloff` edge rings following), then stored (operate). Returns
    zones.transform's report with 'freeze'."""
    from lpk.stages import zones as zones_mod
    M = load(path)
    return operate(M, 'transform', lambda body: zones_mod.transform(body, part, translate, rotate, scale, pivot,
                                                                     falloff))


def replace(path, part):
    """The part `part` of a frozen model's body, a separate shell, replaced by the same part of a fresh
    parametric build (build_mesh(P) with the stored edits, a temporary object removed afterwards;
    lpk.stages.zones.replace), its colours painted from PALETTE, then stored (operate): the module's
    numbers for the part reach the frozen body again. Returns zones.replace's report with 'freeze'."""
    from lpk.stages import zones as zones_mod
    M = load(path)

    def tool(body):
        P = M.props()
        P['edits'] = edits_data(M)
        ref = _reference(M, P, 'parametric', names(M)['body'] + '_ZoneRef')
        try:
            return zones_mod.replace(body, part, ref.name, colours=need(M, 'PALETTE'))
        finally:
            _drop(ref)
    return operate(M, 'replace', tool)


def decimate(path, part, ratio):
    """The part `part` of a frozen model's body reduced to about `ratio` of its faces, its border with
    other parts kept (lpk.stages.zones.decimate), then stored (operate). Returns zones.decimate's report
    with 'freeze'."""
    from lpk.stages import zones as zones_mod
    return operate(load(path), 'decimate', lambda body: zones_mod.decimate(body, part, ratio))


def subdivide(path, part, cuts=1):
    """The part `part` of a frozen model's body subdivided, each inner edge cut `cuts` times, its border
    with other parts kept (lpk.stages.zones.subdivide), then stored (operate). Returns zones.subdivide's
    report with 'freeze'."""
    from lpk.stages import zones as zones_mod
    return operate(load(path), 'subdivide', lambda body: zones_mod.subdivide(body, part, cuts))


def smooth(path, part, iterations=1, factor=0.5):
    """The part `part` of a frozen model's body smoothed `iterations` times by `factor`, its border with
    other parts pinned (lpk.stages.zones.smooth), then stored (operate). Returns zones.smooth's report with
    'freeze'."""
    from lpk.stages import zones as zones_mod
    return operate(load(path), 'smooth', lambda body: zones_mod.smooth(body, part, iterations, factor))


RUNNERS = {'reference': reference, 'blocks': blocks, 'capture_edits': capture_edits, 'adopt': adopt,
           'freeze': freeze, 'unfreeze_texture': unfreeze_texture, 'build': build, 'unwrap': unwrap, 'bake': bake,
           'freeze_texture': freeze_texture, 'rig': rig, 'preview': preview, 'pose_test': pose_test,
           'pose_rest': pose_rest, 'export': export}


def dumps(report):
    """The report as JSON text for the MCP reply (sorted keys; values JSON lacks shown as strings)."""
    return json.dumps(report, sort_keys=True, default=str)
