"""Skeleton templates: the body plans a model's rig follows.

A template is a JSON file, lpk/skeletons/<name>.json; load() returns it once validate() finds no problem
in it. Its sections:

    name, description  the template's name (its file name) and what it describes
    bones              [{'name', 'role', 'parent', 'connect', 'optional'?}] in creation order: each bone's
                       neutral role ('hips', 'upper_arm.L', ...), its parent (an earlier bone, or None) and
                       whether it is connected to it; an optional bone (a tail, fingers, a neck) may be absent
                       from a rig, and the bones it parents then hang unconnected from its nearest ancestor the
                       rig has
    chains             [{'prefix', 'role_prefix', 'root_parent'}]: bone runs whose length the rig chooses; a
                       chain with prefix 'Tail.' and role prefix 'tail.' gives 'Tail.<i>' the role 'tail.<i>'
                       for any i >= 1
    sides              {label: sign}: the side labels of bone, part and connection names in order, each with
                       the sign of x on its side ('.L' is +X); '{s}' in a name expands over the labels
    parts              the default part binding, {part: [bones]}: the bones that may weight each part when
                       the model gives no binding of its own; '{s}' expands over the sides and
                       '<chain prefix>*' stands for the bones of that chain (part_binding())
    roll               {'default': direction, 'roles': {role prefix: direction}}: the direction each bone's
                       Z axis is aligned to at rest; a bone whose role starts with a listed prefix takes that
                       prefix's direction, every other bone the default (roll())
    poses              {pose: {bone: (x, y, z)}}: the review poses, bone-local Euler XYZ rotations in degrees
                       from the rest pose; a bone a rig lacks is left out of a pose
    options            optional: {option: spec}, the sets of optional bones a rig may have (bones_for(),
                       options_for()): {'chain': a chain prefix, 'default': n} takes a count n >= 0, the
                       chain's first n bones; {'choices': {choice: [bones]}, 'default': a choice} takes one of
                       its choices, whose bones ('{s}' expanded over the sides) it requires
    about              {section: text}: what parts, roll, poses and the options hold, and why

Code reads a template's roles, sides and sections, never its bone names. Export profiles rename bones by
role. Pure Python, no bpy."""
import copy
import json
import math
import os
import re

_DIR = os.path.dirname(os.path.abspath(__file__))
_CACHE = {}
# The sections every template holds.
SECTIONS = ('name', 'description', 'bones', 'chains', 'sides', 'parts', 'roll', 'poses', 'about')
# The optional section of the template's options and the optional bones each requires.
OPTIONS_SECTION = 'options'
# The sections the about texts document: every one of them a template holds.
DOCUMENTED = ('parts', 'roll', 'poses', 'options')

def names():
    """The template names shipped in lpk/skeletons, sorted."""
    return sorted(f[:-5] for f in os.listdir(_DIR) if f.endswith('.json'))


def _template(name):
    if name not in _CACHE:
        path = os.path.join(_DIR, name + '.json')
        if not os.path.isfile(path):
            raise ValueError('unknown skeleton template %r; templates: %s' % (name, ', '.join(names())))
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        problems = validate(data, name)
        if problems:
            raise ValueError('skeleton template %s is invalid:\n%s' % (path, '\n'.join(problems)))
        _CACHE[name] = data
    return _CACHE[name]


def load(name):
    """The template as a dict with the sections of the module docstring, validated. A copy: the caller may
    change it. Raises ValueError for an unknown name and for a template validate() finds problems in."""
    return copy.deepcopy(_template(name))


def role_of(bone_name, template='biped'):
    """The role of a bone name in a template: a listed bone's role, or a chain bone's role prefix plus its
    number ('Tail.7' -> 'tail.7'). None for a bone the template does not know (a model's own bones)."""
    t = _template(template)
    for b in t['bones']:
        if b['name'] == bone_name:
            return b['role']
    for c in t['chains']:
        m = re.fullmatch(re.escape(c['prefix']) + r'([1-9][0-9]*)', bone_name)
        if m:
            return c['role_prefix'] + m.group(1)
    return None


def names_by_role(template='biped'):
    """{role: bone name} for the template's listed bones, in creation order."""
    return {b['role']: b['name'] for b in _template(template)['bones']}


def part_binding(template='biped', bones=None):
    """The template's default part binding: {part: [bone names]} in template order, '{s}' expanded over the
    sides in side order and a chain's '<prefix>*' replaced by the bones of that chain in chain order.

    bones: the bone names of a rig, or None for the template's listed bones. With bones, every part lists
    only the bones the rig has, a chain standing for the rig's bones of that chain (any length)."""
    t = _template(template)
    pool = [b['name'] for b in t['bones']] if bones is None else list(bones)
    out = {}
    for part, tokens in _expanded_parts(t):
        listed = []
        for token in tokens:
            if token.endswith('*'):
                prefix = token[:-1]
                found = [b for b in pool if re.fullmatch(re.escape(prefix) + r'[1-9][0-9]*', b)]
                listed += sorted(found, key=lambda b: int(b[len(prefix):]))
            elif token in pool:
                listed.append(token)
        out[part] = list(dict.fromkeys(listed))
    return out


def roll(bone_name, template='biped'):
    """The direction (x, y, z) the Z axis of a bone points at rest: that of the first role prefix of the
    template's roll rule the bone's role starts with, else the rule's default (also for a bone the template
    does not know)."""
    rule = _template(template)['roll']
    role = role_of(bone_name, template)
    for prefix, direction in rule['roles'].items():
        if role is not None and role.startswith(prefix):
            return tuple(float(v) for v in direction)
    return tuple(float(v) for v in rule['default'])


def poses(template='biped'):
    """The template's review poses, {pose: {bone: (x, y, z) degrees}} in template order: bone-local Euler XYZ
    rotations from the rest pose."""
    return {p: {b: tuple(float(v) for v in e) for b, e in r.items()}
            for p, r in _template(template)['poses'].items()}


def option_values(template, options=None):
    """{option: value} of every option the template declares (its 'options' section, in its order): the
    value `options` ({option: value}) gives, else the option's default. Raises ValueError listing every
    option the template does not declare and every value an option does not take: a chain option takes an
    int from 0, a choice option one of its choices."""
    t = _template(template)
    specs = t.get(OPTIONS_SECTION, {})
    given = dict(options or {})
    problems = ['options[%r]: skeleton template %r declares no option %r; its options: %s'
                % (k, template, k, ', '.join(specs) or 'none') for k in given if k not in specs]
    out = {}
    for name, spec in specs.items():
        value = given.get(name, spec['default'])
        if 'chain' in spec:
            if not (isinstance(value, int) and not isinstance(value, bool) and value >= 0):
                problems.append('options[%r]: %r is not a bone count; write the number of %s bones, 0 for none'
                                % (name, value, spec['chain']))
        elif not (isinstance(value, str) and value in spec['choices']):
            problems.append('options[%r]: %r is not one of %s' % (name, value, ', '.join(map(repr, spec['choices']))))
        out[name] = value
    if problems:
        raise ValueError('\n'.join(problems))
    return out


def bones_for(template, options=None):
    """The bones a rig of the template has under `options` (option_values()): every bone the template does not
    mark optional, and the optional bones the options require, as [{'name', 'role', 'parent', 'connect'}] in
    the template's creation order. A chain option of count n requires its chain's bones 1 to n; a chain bone
    past the ones the template lists follows the chain's last listed bone, parented and connected to the bone
    before it, with the chain's role prefix and its number as its role. A choice option requires the bones of
    its choice, '{s}' expanded over the sides in side order. A bone whose parent the rig lacks hangs from that
    parent's nearest ancestor the rig has, unconnected (a head without a neck hangs from the chest). Raises
    ValueError as option_values()."""
    t = _template(template)
    values = option_values(template, options)
    wanted, extra = set(), {}
    for name, spec in t.get(OPTIONS_SECTION, {}).items():
        if 'chain' in spec:
            chain = next(c for c in t['chains'] if c['prefix'] == spec['chain'])
            listed = {b['name'] for b in t['bones']}
            for i in range(1, values[name] + 1):
                bone = '%s%d' % (chain['prefix'], i)
                wanted.add(bone)
                if bone not in listed:
                    extra.setdefault(chain['prefix'], []).append(
                        {'name': bone, 'role': '%s%d' % (chain['role_prefix'], i),
                         'parent': chain['root_parent'] if i == 1 else '%s%d' % (chain['prefix'], i - 1),
                         'connect': i > 1})
        else:
            wanted.update(_side_names(t, spec['choices'][values[name]]))
    after = {}
    for prefix, more in extra.items():
        listed = [b['name'] for b in t['bones'] if re.fullmatch(re.escape(prefix) + r'[1-9][0-9]*', b['name'])]
        after[max(listed, key=lambda n: int(n[len(prefix):]))] = more
    out = []
    for b in t['bones']:
        if not b.get('optional') or b['name'] in wanted:
            out.append({k: b[k] for k in ('name', 'role', 'parent', 'connect')})
        out.extend(after.get(b['name'], ()))
    parent_of = {b['name']: b['parent'] for b in t['bones']}
    have = {b['name'] for b in out}
    for b in out:
        if b['parent'] is not None and b['parent'] not in have:
            up = b['parent']
            while up is not None and up not in have:
                up = parent_of[up]
            b['parent'], b['connect'] = up, False
    return out


def _side_names(t, tokens):
    """The bone names of tokens, '{s}' expanded over the template's sides in side order."""
    out = []
    for token in tokens:
        out.extend([token] if '{s}' not in token else [token.replace('{s}', s) for s in t['sides']])
    return out


def options_for(template, bone_names):
    """The option values (option_values()) under which a rig of the template has exactly the optional
    bones among bone_names: a chain option counts the chain's bones 1, 2, ... present without a gap; a
    choice option takes the choice whose bones are the ones present of all its choices' bones. Names that
    are no bone of the template are ignored. Raises ValueError, one line per option, for a chain with a gap
    (a bone present after a missing one) and for optional bones that match no choice."""
    t = _template(template)
    have = set(bone_names)
    out, problems = {}, []
    for name, spec in t.get(OPTIONS_SECTION, {}).items():
        if 'chain' in spec:
            prefix = spec['chain']
            numbers = sorted(int(b[len(prefix):]) for b in have
                             if re.fullmatch(re.escape(prefix) + r'[1-9][0-9]*', b))
            if numbers != list(range(1, len(numbers) + 1)):
                problems.append('options[%r]: the chain %s has the bones %s; a chain runs from %s1 without a gap'
                                % (name, prefix, ', '.join('%s%d' % (prefix, i) for i in numbers), prefix))
            out[name] = len(numbers)
            continue
        sets = {choice: set(_side_names(t, tokens)) for choice, tokens in spec['choices'].items()}
        present = have & set().union(*sets.values())
        match = [choice for choice, bones in sets.items() if bones == present]
        if not match:
            problems.append('options[%r]: the bones %s match no choice; the choices: %s'
                            % (name, ', '.join(sorted(present)), '; '.join(
                                '%s: %s' % (c, ', '.join(sorted(b)) or 'none') for c, b in sets.items())))
            continue
        out[name] = match[0]
    if problems:
        raise ValueError('\n'.join(problems))
    return out


def sided(value, template='biped'):
    """Model data with '{s}' expanded over the template's sides in side order: a dict gives, for a key holding
    '{s}', one entry per side with the side filled into the key and into the strings of its value (lists,
    tuples and dicts, recursively), and keeps any other entry as given; a list or tuple gives, for an item
    holding '{s}' anywhere, one item per side, filled, and keeps any other item. So {'arm.{s}':
    ['UpperArm.{s}']} becomes {'arm.L': ['UpperArm.L'], 'arm.R': ['UpperArm.R']}, and [('trunk', 'arm.{s}',
    {})] one join per side. Raises ValueError for a dict entry whose value holds '{s}' under a key without
    it, which no side label would fill."""
    labels = list(_template(template)['sides'])

    def fill(v, label):
        if isinstance(v, str):
            return v.replace('{s}', label)
        if isinstance(v, dict):
            return {fill(k, label): fill(x, label) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return type(v)(fill(x, label) for x in v)
        return v

    def has(v):
        if isinstance(v, str):
            return '{s}' in v
        if isinstance(v, dict):
            return any(has(k) or has(x) for k, x in v.items())
        return isinstance(v, (list, tuple)) and any(has(x) for x in v)

    if isinstance(value, dict):
        out = {}
        for key, inner in value.items():
            if has(key):
                out.update({fill(key, s): fill(inner, s) for s in labels})
            elif has(inner):
                raise ValueError("%r: its value names '{s}' and the key does not; put '{s}' into the key" % (key,))
            else:
                out[key] = inner
        return out
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            out.extend([fill(item, s) for s in labels] if has(item) else [item])
        return type(value)(out)
    return value


# -- validation ------------------------------------------------------------------------------------------------

def validate(data, name=None):
    """The problems of a template's data (its parsed JSON), [str], each naming the section and what to fix;
    empty when the template is usable. name: the template's file name, which data['name'] must equal (None
    skips that check). Checks every section of the module docstring: bones with unique names and roles and
    earlier parents; chains whose listed bones carry the chain's roles; sides with signs +1 and -1; parts
    whose patterns expand to unique parts of template bones or chains; a roll rule and poses over template
    roles and bones; options over chains and optional bones; an about text per documented section."""
    if not isinstance(data, dict):
        return ['the template is %s, not a JSON object' % type(data).__name__]
    optional = (OPTIONS_SECTION,)
    missing = [k for k in SECTIONS if k not in data]
    unknown = [k for k in data if k not in SECTIONS + optional]
    out = ['%s: the section is missing; add it (see lpk.skeletons)' % k for k in missing]
    out += ['%s: not a template section; the sections are %s, and optionally %s'
            % (k, ', '.join(SECTIONS), ', '.join(optional)) for k in unknown]
    if out:
        return out
    if not (isinstance(data['name'], str) and data['name'] and (name is None or data['name'] == name)):
        out.append('name: %r must be the template\'s file name %r' % (data['name'], name))
    if not (isinstance(data['description'], str) and data['description'].strip()):
        out.append('description: write what the template describes')
    out += _bone_problems(data['bones'], data['chains'])
    if out:
        return out
    out += _side_problems(data['sides'])
    if out:
        return out
    out += _part_problems(data) + _roll_problems(data) + _pose_problems(data) + _option_problems(data)
    return out + _about_problems(data)


def _number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _vector(x, n=3):
    return isinstance(x, list) and (n is None or len(x) == n) and len(x) > 0 and all(_number(v) for v in x)


def _text(x):
    return isinstance(x, str) and bool(x) and x == x.strip()


def _bone_problems(bones, chains):
    if not (isinstance(bones, list) and bones):
        return ['bones: a non-empty list of {name, role, parent, connect, optional?}']
    out, seen, roles = [], [], set()
    for i, b in enumerate(bones):
        if not (isinstance(b, dict) and {'name', 'role', 'parent', 'connect'} <= set(b)
                and set(b) <= {'name', 'role', 'parent', 'connect', 'optional'}):
            out.append('bones[%d]: %r must be {name, role, parent, connect, optional?}' % (i, b))
            continue
        where = 'bones[%d] %r' % (i, b['name'])
        if not _text(b['name']) or b['name'] in seen:
            out.append('%s: the name must be non-empty text, unique among the bones' % where)
        if not _text(b['role']) or b['role'] in roles:
            out.append('%s: the role %r must be non-empty text, unique among the bones' % (where, b['role']))
        if b['parent'] is not None and b['parent'] not in seen:
            out.append('%s: the parent %r must be an earlier bone, or null' % (where, b['parent']))
        if not isinstance(b['connect'], bool) or (b['connect'] and b['parent'] is None):
            out.append('%s: connect must be true or false, and false without a parent' % where)
        if not isinstance(b.get('optional', False), bool):
            out.append('%s: optional must be true or false' % where)
        seen.append(b['name'])
        roles.add(b['role'])
    if not isinstance(chains, list):
        return out + ['chains: a list of {prefix, role_prefix, root_parent}']
    for i, c in enumerate(chains):
        if not (isinstance(c, dict) and set(c) == {'prefix', 'role_prefix', 'root_parent'}
                and _text(c['prefix']) and _text(c['role_prefix'])):
            out.append('chains[%d]: %r must be {prefix, role_prefix, root_parent} of text' % (i, c))
            continue
        if c['root_parent'] not in seen:
            out.append('chains[%d]: the root_parent %r must be a bone' % (i, c['root_parent']))
        for b in bones:
            m = isinstance(b, dict) and re.fullmatch(re.escape(c['prefix']) + r'([1-9][0-9]*)', str(b.get('name')))
            if m and b.get('role') != c['role_prefix'] + m.group(1):
                out.append('chains[%d]: bone %r must have the role %r' % (i, b['name'], c['role_prefix'] + m.group(1)))
    return out


def _side_problems(sides):
    if not isinstance(sides, dict):
        return ['sides: {label: sign} with the sign of x on each side, +1 or -1']
    return ['sides: %r -> %r must be a label without ".", "{" or "}" and a sign, 1 or -1' % (label, sign)
            for label, sign in sides.items()
            if not (_text(label) and not set(label) & set('.{}') and sign in (1, -1) and not isinstance(sign, bool))]


def _expanded_parts(t):
    """[(part, [bone tokens])] of the template's parts, '{s}' expanded over the sides in side order."""
    out = []
    for pattern, tokens in t['parts'].items():
        labels = tuple(t['sides']) if '{s}' in pattern else (None,)
        for label in labels:
            if label is None:
                out.append((pattern, list(tokens)))
            else:
                out.append((pattern.replace('{s}', label), [tok.replace('{s}', label) for tok in tokens]))
    return out


def _part_problems(t):
    parts = t['parts']
    if not (isinstance(parts, dict) and all(isinstance(v, list) and all(isinstance(b, str) for b in v)
                                            for v in parts.values())):
        return ['parts: {part: [bone names]} of text']
    bones = {b['name'] for b in t['bones']}
    chains = {c['prefix'] + '*' for c in t['chains']}
    out = []
    for pattern, tokens in parts.items():
        if '{s}' in pattern and not t['sides']:
            out.append('parts: %r expands over the sides, but the template has none' % pattern)
        if '{s}' not in pattern and any('{s}' in tok for tok in tokens):
            out.append('parts: %r names bones with {s}; put {s} into the part name too' % pattern)
    if out:
        return out
    seen = set()
    for part, tokens in _expanded_parts(t):
        if part in seen or not _text(part):
            out.append('parts: %r is empty or bound twice; every part has one binding' % part)
        seen.add(part)
        unknown = [tok for tok in tokens if tok not in bones and tok not in chains]
        if unknown or not tokens:
            out.append('parts: %r names %s; name template bones, or a chain as <prefix>*'
                       % (part, ', '.join(map(repr, unknown)) or 'no bone'))
    return out


def _roll_problems(t):
    rule = t['roll']
    if not (isinstance(rule, dict) and set(rule) == {'default', 'roles'} and isinstance(rule['roles'], dict)):
        return ['roll: {"default": direction, "roles": {role prefix: direction}}']
    out = []
    roles = [b['role'] for b in t['bones']] + [c['role_prefix'] for c in t['chains']]
    for where, direction in [('default', rule['default'])] + [('roles[%r]' % p, d) for p, d in rule['roles'].items()]:
        if not (_vector(direction) and any(direction)):
            out.append('roll %s: %r must be a direction (x, y, z), not zero' % (where, direction))
    for prefix in rule['roles']:
        if not (_text(prefix) and any(r.startswith(prefix) for r in roles)):
            out.append('roll roles: %r is no prefix of a role of the template' % prefix)
    return out


def _pose_problems(t):
    poses = t['poses']
    if not isinstance(poses, dict):
        return ['poses: {pose: {bone: (x, y, z) degrees}}']
    bones = {b['name'] for b in t['bones']}
    out = []
    for pose, rotations in poses.items():
        if not (_text(pose) and isinstance(rotations, dict) and rotations):
            out.append('poses: %r must name a pose with {bone: (x, y, z)}' % (pose,))
            continue
        for bone, euler in rotations.items():
            if bone not in bones or not _vector(euler):
                out.append('poses[%r]: %r -> %r must be a template bone and (x, y, z) degrees' % (pose, bone, euler))
    return out


def _option_problems(t):
    if OPTIONS_SECTION not in t:
        return []
    options = t[OPTIONS_SECTION]
    if not isinstance(options, dict):
        return ['options: {option: {"chain", "default"} or {"choices", "default"}}']
    optional = {b['name'] for b in t['bones'] if b.get('optional')}
    chains = {c['prefix'] for c in t['chains']}
    out, claimed = [], {}
    for name, spec in options.items():
        where = 'options[%r]' % (name,)
        if not (_text(name) and isinstance(spec, dict) and set(spec) in ({'chain', 'default'}, {'choices', 'default'})):
            out.append('%s: %r must be {"chain", "default"} or {"choices", "default"}' % (where, spec))
            continue
        if 'chain' in spec:
            if spec['chain'] not in chains:
                out.append('%s: chain %r is not a chain prefix of the template' % (where, spec['chain']))
            d = spec['default']
            if not (isinstance(d, int) and not isinstance(d, bool) and d >= 0):
                out.append('%s: the default %r must be a count from 0' % (where, d))
            continue
        choices = spec['choices']
        if not (isinstance(choices, dict) and choices
                and all(_text(c) and isinstance(b, list) for c, b in choices.items())):
            out.append('%s: choices must be {choice: [bones]}' % where)
            continue
        if spec['default'] not in choices:
            out.append('%s: the default %r must be one of its choices' % (where, spec['default']))
        for choice, tokens in choices.items():
            bones = _side_names(t, [x for x in tokens if isinstance(x, str)])
            wrong = [b for b in bones if b not in optional] + [x for x in tokens if not isinstance(x, str)]
            if wrong:
                out.append('%s: choice %r names %s; an option requires optional template bones only'
                           % (where, choice, ', '.join(map(repr, wrong))))
            for b in bones:
                if claimed.setdefault(b, name) != name:
                    out.append('%s: bone %r is required by option %r too; one option requires each bone'
                               % (where, b, claimed[b]))
    return out


def _about_problems(t):
    about = t['about']
    wanted = [k for k in DOCUMENTED if k in t]
    if not (isinstance(about, dict) and set(about) == set(wanted) and all(isinstance(v, str) and v.strip()
                                                                         for v in about.values())):
        return ['about: {section: text} documenting exactly %s' % ', '.join(wanted)]
    return []
