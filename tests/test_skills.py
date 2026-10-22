"""Keeps the skills in step with the code, on the host Python (the kit's modules are parsed with ast, never
imported): every `lpk.<module>.<name>` and `run.<name>` a card names exists, every Python fence parses,
every relative link reaches a file and, with an anchor, one of its headings, every stage a `stages=` tuple
names is one of lpk.run.STAGES, and no card names an entry point or term the kit does not have.

python tests/test_skills.py"""
import ast
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS = os.path.join(ROOT, 'skills')
DOTTED = re.compile(r'(?<![\w./])(lpk(?:\.\w+)+|run\.\w+)')
FENCE = re.compile(r'^```python\n(.*?)^```', re.S | re.M)
LINK = re.compile(r'\]\(([^)\s]+)\)')
STAGE_TUPLE = re.compile(r"stages=\(([^)]*)\)")
# Entry points and terms the kit does not have, which a card must not teach.
NOT_IN_KIT = re.compile(
    r'lpk\.(ensure|status|plan|resume|inputs|check|presentation|handoff|review_step|executor|state)\b'
    r'|\bctx\.\w|BuildContext|ShapeRef|(?<![/\w])(shape|build|uv|rig|project|refine)\.py\b'
    r'|decision log|\bgate\b')


def cards():
    """[(path relative to the kit, text)] of every Markdown file under skills/, in path order."""
    out = []
    for folder, dirs, files in os.walk(SKILLS):
        dirs.sort()
        for f in sorted(files):
            if f.endswith('.md'):
                path = os.path.join(folder, f)
                with open(path, encoding='utf-8') as fh:
                    out.append((os.path.relpath(path, ROOT).replace(os.sep, '/'), fh.read()))
    return out


def _module_path(parts):
    """The source file of the lpk module `parts` (['lpk', 'core', 'views']), or None."""
    base = os.path.join(ROOT, *parts)
    for path in (base + '.py', os.path.join(base, '__init__.py')):
        if os.path.isfile(path):
            return path
    return None


_NAMES = {}


def top_names(path):
    """The names a module defines at its top level: functions, classes, assignments and imports."""
    if path not in _NAMES:
        with open(path, encoding='utf-8') as f:
            tree = ast.parse(f.read())
        names = set()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for t in targets:
                    for n in ast.walk(t):
                        if isinstance(n, ast.Name):
                            names.add(n.id)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                names.update((a.asname or a.name).split('.')[0] for a in node.names)
        _NAMES[path] = names
    return _NAMES[path]


def resolves(dotted):
    """Whether a dotted name is an lpk module, or a module followed by a name it defines at its top level
    (a class's attribute after it is not checked)."""
    parts = dotted.split('.')
    if parts[0] == 'run':
        parts = ['lpk'] + parts
    for i in range(len(parts), 0, -1):
        path = _module_path(parts[:i])
        if path is not None:
            return i == len(parts) or parts[i] in top_names(path)
    return False


def slug(heading):
    """The anchor a Markdown renderer gives a heading."""
    return re.sub(r'[^\w\- ]', '', heading.strip().lower()).replace(' ', '-')


def anchors(path):
    with open(path, encoding='utf-8') as f:
        return {slug(m.group(1)) for m in re.finditer(r'^#+ (.+)$', f.read(), re.M)}


def test_lpk_names_resolve():
    bad = []
    for rel, text in cards():
        for m in DOTTED.finditer(text):
            name = m.group(1).rstrip('.')
            if not resolves(name):
                bad.append('%s: %s' % (rel, name))
    assert not bad, '\n'.join(bad)


def test_python_fences_parse():
    bad = []
    for rel, text in cards():
        for m in FENCE.finditer(text):
            try:
                ast.parse(m.group(1))
            except SyntaxError as e:
                bad.append('%s: %s' % (rel, e))
    assert not bad, '\n'.join(bad)


def test_links_reach_files_and_headings():
    bad = []
    for rel, text in cards():
        here = os.path.dirname(os.path.join(ROOT, rel))
        for m in LINK.finditer(text):
            target = m.group(1)
            if re.match(r'[a-z]+:', target):
                continue
            path, _, anchor = target.partition('#')
            full = os.path.normpath(os.path.join(here, path)) if path else os.path.join(ROOT, rel)
            if not os.path.exists(full):
                bad.append('%s: %s (no file)' % (rel, target))
            elif anchor and full.endswith('.md') and anchor not in anchors(full):
                bad.append('%s: %s (no heading)' % (rel, target))
    assert not bad, '\n'.join(bad)


def _stages():
    with open(os.path.join(ROOT, 'lpk', 'run.py'), encoding='utf-8') as f:
        tree = ast.parse(f.read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, 'id', None) == 'STAGES' for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError('lpk/run.py has no STAGES')


def test_named_stages_are_the_runners():
    stages, bad = set(_stages()), []
    for rel, text in cards():
        for m in STAGE_TUPLE.finditer(text):
            for name in re.findall(r"'(\w+)'", m.group(1)):
                if name not in stages:
                    bad.append('%s: stage %r' % (rel, name))
    assert not bad, '\n'.join(bad)


def test_no_card_teaches_names_the_kit_lacks():
    bad = ['%s:%d: %s' % (rel, text[:m.start()].count('\n') + 1, m.group(0))
           for rel, text in cards() for m in NOT_IN_KIT.finditer(text)]
    assert not bad, '\n'.join(bad)


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
            print('ok', name)
