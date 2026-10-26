"""The skeleton templates' loader on the host Python: every shipped template validates, and validate()
names the problem of each kind of broken section; the biped's body-plan sections (part binding, roll rule,
review poses) hold the data the rig and review stages use; part_binding(), roll() and poses() read them; the
options give the bones a rig has (bones_for()), a light rig hanging the children of a bone it leaves out from
the nearest bone it has, and are read back from a rig's bone names (options_for()); sided()
expands '{s}' in model data.

python tests/test_skeletons.py"""
import ast
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lpk import skeletons  # noqa: E402

RIG = ROOT / 'lpk' / 'stages' / 'rig.py'
REVIEW = ROOT / 'lpk' / 'stages' / 'review.py'
DEFAULTS = {'tail': 0, 'hands': 'plain', 'neck': 'bone', 'shoulders': 'bones', 'toes': 'bones'}
LIGHT = {'neck': 'none', 'shoulders': 'none', 'toes': 'none'}


def _functions(path, *names):
    """Execute the named top-level functions of a module's source (it imports bpy) in a namespace of
    their own."""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    mod = ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names],
                     type_ignores=[])
    ns = {}
    exec(compile(mod, str(path), 'exec'), ns)
    return [ns[n] for n in names]


def _constant(path, name):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    node = next(n for n in tree.body if isinstance(n, ast.Assign) and [t.id for t in n.targets] == [name])
    return ast.literal_eval(node.value)


def _broken(edit):
    """validate()'s problems of a copy of the biped template that edit(data) changed."""
    data = skeletons.load('biped')
    edit(data)
    return skeletons.validate(data, 'biped')


def test_every_shipped_template_validates():
    assert skeletons.names() == ['biped', 'quadruped', 'rigid']
    for name in skeletons.names():
        data = skeletons.load(name)
        assert skeletons.validate(data, name) == [], name
        assert set(skeletons.SECTIONS) <= set(data), name
        assert set(data['about']) == {s for s in skeletons.DOCUMENTED if s in data}, name
        assert data == skeletons.load(name) and data is not skeletons.load(name), 'load returns a copy'


def test_validate_names_each_broken_section():
    cases = {
        'extra': lambda d: d.update(extra=1),
        'bones parent': lambda d: d['bones'][1].update(parent='Head'),
        'bones role': lambda d: d['bones'][1].update(role='hips'),
        'chains': lambda d: d['chains'][0].update(role_prefix='tails.'),
        'sides': lambda d: d['sides'].update(L=2),
        'parts bone': lambda d: d['parts'].update(head=['Skull']),
        'parts twice': lambda d: d['parts'].update({'arm.L': ['Chest']}),
        'parts {s}': lambda d: d['parts'].update(head=['Hand.{s}']),
        'roll prefix': lambda d: d['roll']['roles'].update({'wing.': [0, 0, 1]}),
        'roll zero': lambda d: d['roll'].update(default=[0, 0, 0]),
        'poses': lambda d: d['poses']['grip'].update({'Pinky.L': [0, 0, 1]}),
        'about': lambda d: d['about'].pop('poses'),
    }
    for label, edit in cases.items():
        problems = _broken(edit)
        assert problems, '%s: accepted' % label
        section = label.split()[0]
        assert any(p.startswith(section) for p in problems), (label, problems)
    assert skeletons.validate([], 'biped')
    assert skeletons.validate(skeletons.load('biped'), 'other'), 'the name is the file name'
    assert any(p.startswith('sketch') for p in _broken(lambda d: d.update(sketch={}))), 'no sketch section'


def test_the_biped_part_binding_names_template_bones():
    binding = skeletons.part_binding('biped')
    names = set(skeletons.names_by_role('biped').values())
    assert all(set(bones) <= names for bones in binding.values())
    rig = ['Hips', 'Spine', 'Chest', 'Tail.1', 'Tail.2', 'Tail.3', 'Tail.8', 'Hand.L']
    short = skeletons.part_binding('biped', bones=rig)
    assert short['tail'] == ['Hips', 'Tail.1', 'Tail.2', 'Tail.3', 'Tail.8'], 'a chain of any length'
    assert short['hand.L'] == ['Hand.L'] and short['hand.R'] == [], 'only the bones the rig has'
    assert list(short) == list(binding)


def test_the_biped_roll_rule_and_poses_are_the_stage_data():
    for bone in skeletons.load('biped')['bones']:
        expected = (0.0, 0.0, 1.0) if bone['name'].startswith('Tail') else (0.0, -1.0, 0.0)
        assert skeletons.roll(bone['name'], 'biped') == expected, bone['name']
    assert skeletons.roll('Tail.12') == (0.0, 0.0, 1.0) and skeletons.roll('Ear.L') == (0.0, -1.0, 0.0)
    poses = skeletons.poses('biped')
    assert list(poses) == list(skeletons.load('biped')['poses']), 'in template order'
    assert poses['side75'] == {'UpperArm.L': (0.0, 0.0, 75.0), 'UpperArm.R': (0.0, 0.0, -75.0)}
    assert 'POSES' not in REVIEW.read_text(encoding='utf-8'), 'the template is the one source of the review poses'


def test_options_give_the_bones_a_rig_of_the_template_has():
    assert skeletons.option_values('biped') == DEFAULTS
    plain = skeletons.bones_for('biped')
    listed = {b['name']: b for b in skeletons.load('biped')['bones']}
    by_default = {'Neck', 'Shoulder.L', 'Shoulder.R', 'Toes.L', 'Toes.R'}
    assert [b['name'] for b in plain] == [n for n, b in listed.items() if not b.get('optional') or n in by_default]
    assert all(b == {k: listed[b['name']][k] for k in ('name', 'role', 'parent', 'connect')} for b in plain)
    names = [b['name'] for b in skeletons.bones_for('biped', {'tail': 2, 'hands': 'mitten'})]
    assert names[-8:] == ['Tail.1', 'Tail.2', 'Index.L', 'Middle.L', 'Thumb.L', 'Index.R', 'Middle.R', 'Thumb.R']
    long = skeletons.bones_for('biped', {'tail': 8})
    assert [b['name'] for b in long][-3:] == ['Tail.6', 'Tail.7', 'Tail.8'], 'a chain longer than its listed bones'
    assert long[-1] == {'name': 'Tail.8', 'role': 'tail.8', 'parent': 'Tail.7', 'connect': True}
    for options in ({'wings': 2}, {'tail': -1}, {'tail': True}, {'hands': 'claw'}):
        try:
            skeletons.bones_for('biped', options)
        except ValueError as e:
            assert "options[" in str(e), e
        else:
            raise AssertionError('options %r accepted' % (options,))
    cases = {
        'options choice': lambda d: d['options']['hands']['choices']['mitten'].append('Hand.{s}'),
        'options chain': lambda d: d['options']['tail'].update(chain='Wing.'),
        'options default': lambda d: d['options']['hands'].update(default='claw'),
        'options shape': lambda d: d['options'].update(ears={'count': 2}),
        'about': lambda d: d['about'].pop('options'),
    }
    for label, edit in cases.items():
        problems = _broken(edit)
        assert any(p.startswith(label.split()[0]) for p in problems), (label, problems)
    without = skeletons.load('biped')
    del without['options'], without['about']['options']
    assert skeletons.validate(without, 'biped') == [], 'the options are optional'


def test_a_light_rig_hangs_children_from_the_nearest_bone_it_has():
    light = {b['name']: b for b in skeletons.bones_for('biped', LIGHT)}
    assert len(light) == 16 and not {'Neck', 'Shoulder.L', 'Toes.R'} & set(light)
    assert light['Head'] == {'name': 'Head', 'role': 'head', 'parent': 'Chest', 'connect': False}
    assert light['UpperArm.L']['parent'] == 'Chest' and light['UpperArm.L']['connect'] is False
    assert light['LowerArm.L']['parent'] == 'UpperArm.L' and light['LowerArm.L']['connect'] is True, 'the rest stays'
    with_tail = skeletons.bones_for('biped', dict(LIGHT, tail=2))
    assert [b['name'] for b in with_tail][-2:] == ['Tail.1', 'Tail.2'] and len(with_tail) == 18
    binding = skeletons.part_binding('biped', bones=list(light))
    assert binding['trunk'] == ['Hips', 'Spine', 'Chest', 'UpperArm.L', 'UpperArm.R', 'UpperLeg.L', 'UpperLeg.R']
    assert binding['foot.L'] == ['LowerLeg.L', 'Foot.L']


def test_the_rigid_template_is_a_root_the_model_builds_on():
    assert [b['name'] for b in skeletons.bones_for('rigid')] == ['Root']
    assert skeletons.part_binding('rigid') == {} and skeletons.poses('rigid') == {}
    assert skeletons.options_for('rigid', ['Root', 'Turret', 'Barrel']) == {}, 'model bones are no template bones'
    assert skeletons.role_of('Turret', 'rigid') is None and skeletons.roll('Turret', 'rigid') == (0.0, -1.0, 0.0)
    assert skeletons.sided({'leg.{s}': {'Leg.{s}': 1.0}}, 'rigid') == {'leg.L': {'Leg.L': 1.0},
                                                                       'leg.R': {'Leg.R': 1.0}}


def test_the_quadruped_rolls_its_body_up_and_its_legs_forward():
    bones = [b['name'] for b in skeletons.bones_for('quadruped', {'tail': 3, 'jaw': 'bone'})]
    assert len(bones) == 27 and bones[-3:] == ['Tail.1', 'Tail.2', 'Tail.3'] and 'Jaw' in bones
    assert len(skeletons.bones_for('quadruped', {'toes': 'none'})) == 19
    for bone, roll in (('Spine', (0.0, 0.0, 1.0)), ('Tail.5', (0.0, 0.0, 1.0)), ('HindToes.L', (0.0, 0.0, 1.0)),
                       ('Scapula.R', (0.0, -1.0, 0.0)), ('Shin.L', (0.0, -1.0, 0.0))):
        assert skeletons.roll(bone, 'quadruped') == roll, bone
    binding = skeletons.part_binding('quadruped', bones=bones)
    assert binding['front_paw.L'] == ['Forearm.L', 'FrontFoot.L', 'FrontToes.L'] and binding['head'] == ['Head', 'Jaw']
    assert set(skeletons.poses('quadruped')) >= {'front_step', 'hind_step', 'head_turn', 'tail_up'}


def test_full_hands_and_the_standard_rest():
    full = [b['name'] for b in skeletons.bones_for('biped', {'hands': 'full'})]
    assert len(full) == 51 and 'Little3.R' in full and 'Index.L' not in full
    bones = {b['name']: b for b in skeletons.bones_for('biped', {'hands': 'full'})}
    assert (bones['Index2.L']['parent'], bones['Index2.L']['connect']) == ('Index1.L', True)
    assert skeletons.part_binding('biped', bones=full)['thumb.L'] == ['Hand.L', 'Thumb1.L', 'Thumb2.L', 'Thumb3.L']
    rest = skeletons.rest('biped', 'standard', {'hands': 'full'})
    assert list(rest) == full and all(rest[b][0] != rest[b][1] for b in rest)
    assert math.isclose(rest['Head'][1][2], 1.75) and rest['Hand.L'][0][0] > 0 > rest['Hand.R'][0][0]
    assert rest['Hand.R'][0] == (-rest['Hand.L'][0][0],) + rest['Hand.L'][0][1:], 'the sides mirror'
    for options, needle in (({'tail': 2}, 'covers no joint'), ({'hands': 'mitten'}, 'covers no joint')):
        try:
            skeletons.rest('biped', 'standard', options)
        except ValueError as e:
            assert needle in str(e), e
        else:
            raise AssertionError('%r accepted' % (options,))
    for edit in (lambda d: d['rests']['standard'].update(Wing=[[0, 0, 0], [0, 0, 1]]),
                 lambda d: d['rests']['standard'].update(Hips=[[0, 0, 1], [0, 0, 1]])):
        assert any(p.startswith('rests') for p in _broken(edit))


def test_options_for_reads_the_options_back_from_a_rigs_bones():
    for options in ({}, {'tail': 3}, {'tail': 8, 'hands': 'mitten'}, {'hands': 'mitten'}, LIGHT,
                    dict(LIGHT, tail=2, neck='bone')):
        names = [b['name'] for b in skeletons.bones_for('biped', options)]
        assert skeletons.options_for('biped', names) == skeletons.option_values('biped', options), options
    plain = [b['name'] for b in skeletons.bones_for('biped')]
    assert skeletons.options_for('biped', plain + ['Socket', 'Ear.L']) == DEFAULTS
    for extra, needle in ((['Tail.1', 'Tail.3'], 'gap'), (['Index.L'], 'no choice')):
        try:
            skeletons.options_for('biped', plain + extra)
        except ValueError as e:
            assert needle in str(e), e
        else:
            raise AssertionError('%s accepted' % extra)


def test_sided_expands_model_data_over_the_sides():
    assert skeletons.sided({'arm.{s}': ['Chest', 'UpperArm.{s}'], 'head': ['Head']}) == {
        'arm.L': ['Chest', 'UpperArm.L'], 'arm.R': ['Chest', 'UpperArm.R'], 'head': ['Head']}
    assert skeletons.sided({'belt.{s}': {'UpperLeg.{s}': 1.0}}) == {'belt.L': {'UpperLeg.L': 1.0},
                                                                   'belt.R': {'UpperLeg.R': 1.0}}
    joins = [('trunk', 'arm.{s}', {'UpperArm.{s}': 0.1}), ('trunk', 'neck', {})]
    assert skeletons.sided(joins) == [('trunk', 'arm.L', {'UpperArm.L': 0.1}), ('trunk', 'arm.R', {'UpperArm.R': 0.1}),
                                      ('trunk', 'neck', {})]
    try:
        skeletons.sided({'trunk': ['Shoulder.{s}']})
    except ValueError as e:
        assert 'trunk' in str(e), e
    else:
        raise AssertionError("'{s}' in a value under a plain key accepted")

if __name__ == '__main__':
    import traceback
    failed = 0
    tests = [(name, fn) for name, fn in list(globals().items()) if name.startswith('test_') and callable(fn)]
    for name, fn in tests:
        try:
            fn()
            print('ok      %s' % name)
        except Exception:
            failed += 1
            print('FAILED  %s' % name)
            traceback.print_exc()
    print('%d passed, %d failed' % (len(tests) - failed, failed))
    sys.exit(1 if failed else 0)
