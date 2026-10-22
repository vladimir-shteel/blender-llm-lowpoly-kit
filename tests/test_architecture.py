"""The architecture conformance test (ARCHITECTURE.md, "Conformance checks"), on the host Python: lpk is
parsed with ast, and only the host-importability check imports modules, each in a subprocess of its own
that refuses the Blender modules. The scan covers lpk/; tests/, dev/ and lpk_dev/ are not scanned, so a
test may reach the private names of the module it tests.

Every finding is an exception keyed by (rule, module, name), never by line number, with its count of
sites. The rules:

layers   ARCHITECTURE.md "Layers", rule 1. Every lpk module has a layer in LAYERS or PLANNED, or is an
         inert package (a module with none fails outright, as does a row that names no module). An import
         of an lpk module, at module level or in a function, relative ones resolved, follows MAY_IMPORT of
         the importer's layer. A dynamic import counts too: in a scope that calls
         importlib.import_module or __import__, every string constant that names an lpk module is an
         import of it. L0 also imports nothing outside the standard library and numpy (Blender modules:
         see host). name: the imported module (an external module's top name for L0).
         An inert package (an __init__.py with nothing but a docstring) has no row: importing the package
         itself counts as importing its highest-layer submodule; `from pkg import sub` is an import of
         pkg.sub.
host     rule 5. Each L0 module and lpk.host command (HOST_PATTERNS) imports in a subprocess whose meta-path
         hook refuses bpy, bmesh and mathutils; and no import of them appears anywhere in the module, in
         functions included. name: the Blender module, or '<module> via <lpk module>' when a module that is
         not host-checked, imported by the module, does the import at import time. A module that fails to
         import for another reason fails outright.
private  rule 2. `from lpk.x import _name` and `<binding>._name`, where the binding is a name an import
         bound to an lpk module or to a name of one, across modules. Dunder names are public. Attribute
         access on instances is not seen. name: the dotted private name.
dynamic  rule 6. Calls into importlib, exec, eval, __import__, globals() and a getattr with a computed
         name on an lpk binding appear only in the modules of LOADERS. name: the call.
local    rule 8. No lpk module imports the local library lpk_local: an import or from-import of it, at
         module level or in a function, or a string constant naming it in a scope that calls
         importlib.import_module or __import__. lpk_local is ignored by git and not scanned. name: the
         imported dotted name.

Baseline. tests/architecture_baseline.json lists the permitted exceptions with their counts. A finding the
baseline lacks, or a count above the recorded one, fails. An entry that no longer occurs, or whose count is
above the measured one, fails until --prune removes the entry or lowers the count; --prune never adds an
entry or raises a count. The test fails while the baseline lists an entry, or a count, beyond the baseline
committed at HEAD, for the rules HEAD's baseline lists (a rule new since HEAD lands with its entries); a
baseline not committed at HEAD is accepted. --record writes the baseline from the findings; it is refused
when HEAD holds a baseline and the result would add an entry or raise a count there.

python tests/test_architecture.py            run the checks; exit 1 on a failure
python tests/test_architecture.py --prune    the same, then remove the stale entries and lower the counts
python tests/test_architecture.py --record   write the baseline from the findings (see above)"""
import ast
import collections
import functools
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE_FILE = os.path.join(ROOT, 'tests', 'architecture_baseline.json')
BASELINE_REL = 'tests/architecture_baseline.json'
RULES = ('layers', 'host', 'private', 'dynamic', 'local')

# ARCHITECTURE.md "Layers": the current modules of each layer. A pattern `pkg.*` covers the submodules of
# pkg, not the package itself.
LAYERS = {
    0: ('lpk.core.views', 'lpk.core.sections', 'lpk.skeletons', 'lpk.profiles', 'lpk.stages.imaging',
        'lpk.stages.numerical', 'lpk.intake'),
    1: ('lpk.core.builder', 'lpk.core.shapes', 'lpk.core.edits', 'lpk.stages.checks', 'lpk.stages.view'),
    2: ('lpk.forms.*',),
    3: ('lpk.stages.texture', 'lpk.stages.rig', 'lpk.stages.pose', 'lpk.stages.preview', 'lpk.stages.export',
        'lpk.stages.review', 'lpk.stages.reference', 'lpk.stages.blocks', 'lpk.stages.zones'),
    4: ('lpk', 'lpk.run', 'lpk.setup_check', 'lpk.host.*'),
}
# The planned modules ARCHITECTURE.md names, with their layers: a module created under one of these names
# takes its layer from here until it gets its row above.
PLANNED = {}
# The "May import" column; L0 also imports the standard library and numpy.
MAY_IMPORT = {0: {0}, 1: {0, 1}, 2: {0, 1, 2}, 3: {0, 1, 2, 3}, 4: {0, 1, 2, 3, 4}}
L0_EXTERNAL = ('numpy',)
BLENDER = ('bpy', 'bmesh', 'mathutils')
HOST_LAYERS = (0,)
# Host commands outside L0 that must import on the host as well.
HOST_PATTERNS = ('lpk.host.*',)
# Rule 6: the modules that may load code dynamically: the runner, which loads the model module.
LOADERS = ('lpk.run',)
DYNAMIC_BUILTINS = ('exec', 'eval', '__import__', 'globals')
KEY_FIELDS = ('rule', 'module', 'name')
# ARCHITECTURE.md "Layers", rule 8: the local form library, which no lpk module imports.
LOCAL = 'lpk_local'


def _private(part):
    return part.startswith('_') and not (part.startswith('__') and part.endswith('__'))


def _docstring_only(body):
    return all(isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) and isinstance(s.value.value, str)
               for s in body) and len(body) <= 1


def _matches(name, pattern):
    return name == pattern or (pattern.endswith('.*') and name.startswith(pattern[:-1]))


class Module:
    """One lpk source file: its dotted name, path relative to the kit, source and syntax tree."""

    def __init__(self, name, path, source=None):
        self.name, self.path = name, path
        self.rel = os.path.relpath(path, ROOT).replace(os.sep, '/')
        if source is None:
            with open(path, encoding='utf-8') as f:
                source = f.read()
        self.source = source
        self.tree = ast.parse(self.source, self.rel)
        self.package = os.path.basename(path) == '__init__.py'
        self.inert = self.package and _docstring_only(self.tree.body)


@functools.lru_cache(None)
def modules():
    """{dotted name: Module} of every .py file under lpk/, in path order."""
    out = {}
    for folder, dirs, names in os.walk(os.path.join(ROOT, 'lpk')):
        dirs[:] = sorted(d for d in dirs if d != '__pycache__')
        for f in sorted(names):
            if f.endswith('.py'):
                path = os.path.join(folder, f)
                dotted = os.path.relpath(path, ROOT)[:-3].replace(os.sep, '.')
                name = dotted[:-len('.__init__')] if dotted.endswith('.__init__') else dotted
                out[name] = Module(name, path)
    return out


def table_layer(name):
    """The layer LAYERS or PLANNED gives a module name, or None."""
    for layer, names in LAYERS.items():
        if any(_matches(name, p) for p in names):
            return layer
    return PLANNED.get(name)


def layer(name):
    """The layer of an lpk module: its row, or for an inert package the highest layer of its layered
    submodules; None when it has neither."""
    own = table_layer(name)
    mod = modules().get(name)
    if own is not None or mod is None or not mod.inert:
        return own
    inner = [layer(n) for n in modules() if n.startswith(name + '.')]
    inner = [x for x in inner if x is not None]
    return max(inner) if inner else None


def split_module(dotted):
    """(the longest lpk module prefix of a dotted name, the remaining parts); (None, parts) when no prefix
    is an lpk module."""
    parts = dotted.split('.')
    for i in range(len(parts), 0, -1):
        if '.'.join(parts[:i]) in modules():
            return '.'.join(parts[:i]), parts[i:]
    return None, parts


def _parent(name):
    return name.rpartition('.')[0]


def _shallow(node):
    """The nodes of one scope: node's descendants, not entering nested functions and lambdas."""
    todo = list(ast.iter_child_nodes(node))
    while todo:
        n = todo.pop()
        yield n
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            todo.extend(ast.iter_child_nodes(n))


def _str(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


class Scanner(ast.NodeVisitor):
    """One walk of a module that records, with line numbers, what the checks read: lpk imports (module
    level, in functions, dynamic), external imports, private accesses and dynamic loading calls."""

    def __init__(self, mod):
        self.mod = mod
        self.scopes = []           # [bindings {local name: dotted}], innermost last
        self.depth = 0             # enclosing functions
        self.imports = []          # (target lpk module, 'module' | 'function' | 'dynamic', line)
        self.external = []         # (top-level module name, line)
        self.private = []          # (dotted private name, line)
        self.dynamic = []          # (call name, line)
        self.local = []            # (dotted lpk_local name, line)
        self.visit(mod.tree)

    def _base(self, node):
        """The absolute module an ImportFrom reads from."""
        if not node.level:
            return node.module
        package = self.mod.name if self.mod.package else _parent(self.mod.name)
        for _ in range(node.level - 1):
            package = _parent(package)
        return package + ('.' + node.module if node.module else '')

    def _enter(self, node):
        binds = {}
        nodes = list(_shallow(node))
        for n in nodes:
            if isinstance(n, ast.Import):
                for a in n.names:
                    top = a.name.split('.')[0]
                    binds[a.asname or top] = a.name if a.asname else top
            elif isinstance(n, ast.ImportFrom):
                base = self._base(n)
                for a in n.names:
                    if base and a.name != '*':
                        binds[a.asname or a.name] = base + '.' + a.name
        self.scopes.append(binds)
        if any(isinstance(n, ast.Call) and self._loader_call(n) for n in nodes):
            for n in nodes:
                s = _str(n)
                if s and re.fullmatch(r'lpk(\.\w+)*\.?', s) and s.rstrip('.') in modules():
                    self.imports.append((s.rstrip('.'), 'dynamic', n.lineno))
                elif s and re.fullmatch(r'%s(\.\w+)*\.?' % LOCAL, s):
                    self.local.append((s.rstrip('.'), n.lineno))

    def _loader_call(self, call):
        return self.resolve(call.func) == 'importlib.import_module' or self._builtin(call.func) == '__import__'

    def lookup(self, name):
        for binds in reversed(self.scopes):
            if name in binds:
                return binds[name]
        return None

    def resolve(self, node):
        """The dotted name an expression stands for through the imports in scope, or None."""
        if isinstance(node, ast.Name):
            return self.lookup(node.id)
        if isinstance(node, ast.Attribute):
            base = self.resolve(node.value)
            return base + '.' + node.attr if base else None
        return None

    def _builtin(self, func):
        """The name of a builtin call (a name no import in scope binds), or None."""
        return func.id if isinstance(func, ast.Name) and self.lookup(func.id) is None else None

    def visit_Module(self, node):
        self._enter(node)
        self.generic_visit(node)
        self.scopes.pop()

    def visit_FunctionDef(self, node):
        for d in node.decorator_list + node.args.defaults + [d for d in node.args.kw_defaults if d]:
            self.visit(d)
        self.depth += 1
        self._enter(node)
        for stmt in node.body:
            self.visit(stmt)
        self.scopes.pop()
        self.depth -= 1

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node):
        for d in node.args.defaults + [d for d in node.args.kw_defaults if d]:
            self.visit(d)
        self._enter(node)
        self.visit(node.body)
        self.scopes.pop()

    def visit_Import(self, node):
        where = 'function' if self.depth else 'module'
        for a in node.names:
            top = a.name.split('.')[0]
            if top == LOCAL:
                self.local.append((a.name, node.lineno))
            if top != 'lpk':
                self.external.append((top, node.lineno))
                continue
            self.imports.append((split_module(a.name)[0] or a.name, where, node.lineno))

    def visit_ImportFrom(self, node):
        where = 'function' if self.depth else 'module'
        base = self._base(node)
        if base and not node.level and base.split('.')[0] == LOCAL:
            self.local.append((base, node.lineno))
        if not base or base.split('.')[0] != 'lpk':
            if base and not node.level:
                self.external.append((base.split('.')[0], node.lineno))
            return
        targets = set()
        for a in node.names:
            sub = base + '.' + a.name
            if sub in modules():
                targets.add(sub)
                continue
            module = split_module(base)[0] or base
            targets.add(module)
            if _private(a.name) and module != self.mod.name:
                self.private.append((module + '.' + a.name, node.lineno))
        for target in sorted(targets):
            self.imports.append((target, where, node.lineno))

    def visit_Attribute(self, node):
        inner = node
        while isinstance(inner, ast.Attribute):
            inner = inner.value
        if isinstance(inner, ast.Name):
            binding = self.lookup(inner.id)
            if binding and binding.split('.')[0] == 'lpk':
                self._private_chain(binding, self.resolve(node), node.lineno)
        self.visit(inner)

    def _private_chain(self, binding, dotted, line):
        """The first private name of another module an attribute chain reaches past its binding."""
        parts = dotted.split('.')
        for i in range(len(binding.split('.')), len(parts)):
            if not _private(parts[i]):
                continue
            prefix = '.'.join(parts[:i + 1])
            if prefix not in modules() and split_module(prefix)[0] != self.mod.name:
                self.private.append((prefix, line))
            return

    def visit_Call(self, node):
        func = node.func
        dotted = self.resolve(func)
        builtin = self._builtin(func)
        if dotted and dotted.split('.')[0] == 'importlib':
            self.dynamic.append((dotted, node.lineno))
        elif builtin in DYNAMIC_BUILTINS:
            self.dynamic.append((builtin, node.lineno))
        elif builtin == 'getattr' and len(node.args) >= 2 and _str(node.args[1]) is None:
            target = self.resolve(node.args[0])
            if target and target.split('.')[0] == 'lpk':
                self.dynamic.append(('getattr', node.lineno))
        self.generic_visit(node)


@functools.lru_cache(None)
def scan(name):
    return Scanner(modules()[name])


def scanned():
    """The modules the checks scan."""
    return list(modules())


# -- the checks: each returns {(rule, module, name): {'values': {'count': n}, 'sites': [str]}} ---------------

class Findings(dict):
    def count(self, rule, module, name, site):
        f = self.setdefault((rule, module, name), {'values': {'count': 0}, 'sites': []})
        f['values']['count'] += 1
        f['sites'].append(site)


def unassigned():
    """The modules without a layer: neither a row of LAYERS or PLANNED nor an inert package."""
    return [n for n, m in modules().items()
            if layer(n) is None or (table_layer(n) is None and not m.inert)]


def stale_rows():
    """The rows of LAYERS that name no current module (a planned name may be listed before it
    exists)."""
    rows = [p for names in LAYERS.values() for p in names]
    return [p for p in rows if not any(_matches(n, p) for n in modules())]


def check_layers():
    out = Findings()
    stdlib = sys.stdlib_module_names
    for name in scanned():
        src = layer(name)
        if src is None:
            continue
        s = scan(name)
        for target, where, line in s.imports:
            dst = layer(target)
            if target == name or dst is None or dst in MAY_IMPORT[src]:
                continue
            out.count('layers', name, target, '%s:%d L%d imports L%d %s' % (
                modules()[name].rel, line, src, dst, 'dynamically' if where == 'dynamic' else
                'in a function' if where == 'function' else 'at module level'))
        if src == 0:
            for top, line in s.external:
                if top not in stdlib and top not in L0_EXTERNAL and top not in BLENDER and top != '__future__':
                    out.count('layers', name, top, '%s:%d L0 imports %s' % (modules()[name].rel, line, top))
    return out


CHILD = r'''
import importlib, json, sys
root, name, blocked = sys.argv[1], sys.argv[2], sys.argv[3].split(',')
refused = []


class Refuse:
    """Refuses the Blender modules and records which lpk module asked."""

    def find_spec(self, fullname, path=None, target=None):
        top = fullname.split('.')[0]
        if top not in blocked:
            return None
        frame, via = sys._getframe(1), None
        while frame is not None:
            asker = frame.f_globals.get('__name__', '')
            if asker == 'lpk' or asker.startswith('lpk.'):
                via = asker
                break
            frame = frame.f_back
        refused.append([top, via])
        raise ImportError('%s is refused on the host' % fullname)


sys.meta_path.insert(0, Refuse())
sys.path.insert(0, root)
error = None
try:
    importlib.import_module(name)
except BaseException as e:
    error = '%s: %s' % (type(e).__name__, e)
print(json.dumps({'refused': refused, 'error': error}))
'''


@functools.lru_cache(None)
def hosted():
    """The scanned modules the host check holds: L0 and the host commands."""
    return [n for n in scanned() if layer(n) in HOST_LAYERS or any(_matches(n, p) for p in HOST_PATTERNS)]


@functools.lru_cache(None)
def host_imports():
    """{module: {'refused': [[blender module, asking lpk module]], 'error': str or None}} for every
    host-checked module, each imported in a fresh subprocess that refuses the Blender modules."""
    out = {}
    for name in hosted():
        if not modules()[name].inert:
            run = subprocess.run([sys.executable, '-B', '-c', CHILD, ROOT, name, ','.join(BLENDER)], cwd=ROOT,
                                 capture_output=True)
            text = run.stdout.decode('utf-8', 'replace').strip().splitlines()
            try:
                out[name] = json.loads(text[-1])
            except (IndexError, ValueError):
                out[name] = {'refused': [], 'error': 'no result: %s' % run.stderr.decode('utf-8', 'replace')[-400:]}
    return out


def host_failures():
    """The modules that fail to import on the host for a reason other than a refused Blender module."""
    return {n: r['error'] for n, r in host_imports().items() if r['error'] and not r['refused']}


def check_host():
    out = Findings()
    held = set(hosted())
    for name in sorted(held):
        rel = modules()[name].rel
        static = set()
        for top, line in scan(name).external:
            if top in BLENDER:
                static.add(top)
                out.count('host', name, top, '%s:%d imports %s' % (rel, line, top))
        for top, via in host_imports().get(name, {}).get('refused', ()):
            if via == name or via is None:
                if top not in static:
                    out.count('host', name, top, '%s: imports %s when imported' % (rel, top))
                    static.add(top)
            elif via not in held:
                key = '%s via %s' % (top, via)
                if ('host', name, key) not in out:
                    out.count('host', name, key, '%s: %s imports %s when %s is imported' % (rel, via, top, name))
    return out


def check_private():
    out = Findings()
    for name in scanned():
        for dotted, line in scan(name).private:
            out.count('private', name, dotted, '%s:%d reaches %s' % (modules()[name].rel, line, dotted))
    return out


def check_dynamic():
    out = Findings()
    for name in scanned():
        if name in LOADERS:
            continue
        for call, line in scan(name).dynamic:
            out.count('dynamic', name, call, '%s:%d %s' % (modules()[name].rel, line, call))
    return out


def check_local():
    out = Findings()
    for name in scanned():
        for dotted, line in scan(name).local:
            out.count('local', name, dotted, '%s:%d imports %s' % (modules()[name].rel, line, dotted))
    return out


CHECKS = {'layers': check_layers, 'host': check_host, 'private': check_private,
          'dynamic': check_dynamic, 'local': check_local}
TITLES = {'layers': 'imports follow the layers',
          'host': 'L0 and host commands import on host', 'private': 'no private access across modules',
          'dynamic': 'dynamic loading only in the runner', 'local': 'lpk never imports lpk_local'}


@functools.lru_cache(None)
def findings(rule):
    return CHECKS[rule]()


# -- the baseline ---------------------------------------------------------------------------------------------

def _key(entry):
    return tuple(entry[k] for k in KEY_FIELDS)


def _values(entry):
    return {k: v for k, v in entry.items() if k not in KEY_FIELDS}


def load_baseline(text=None):
    """The baseline as {'about', 'rules', 'exceptions': {key: values}}; raises ValueError when malformed."""
    if text is None:
        with open(BASELINE_FILE, encoding='utf-8') as f:
            text = f.read()
    data = json.loads(text)
    entries = {}
    for e in data.get('exceptions', ()):
        if not set(KEY_FIELDS) <= set(e):
            raise ValueError('%s: malformed entry %r' % (BASELINE_REL, e))
        values = _values(e)
        if set(values) != {'count'} or not isinstance(values['count'], int) or isinstance(values['count'], bool) \
                or values['count'] <= 0:
            raise ValueError('%s: entry %r needs a positive count' % (BASELINE_REL, e))
        if _key(e) in entries:
            raise ValueError('%s: duplicate entry %r' % (BASELINE_REL, _key(e)))
        entries[_key(e)] = values
    rules = data.get('rules')
    if not isinstance(rules, list):
        raise ValueError('%s: "rules" must be a list' % BASELINE_REL)
    return {'about': data.get('about', ''), 'rules': rules, 'exceptions': entries}


def _head():
    """The baseline committed at HEAD, or None when git or the committed file is missing; raises ValueError
    when HEAD's baseline is malformed."""
    try:
        run = subprocess.run(['git', '-C', ROOT, 'show', 'HEAD:' + BASELINE_REL], capture_output=True)
    except OSError:
        return None
    if run.returncode != 0:
        return None
    return load_baseline(run.stdout.decode('utf-8'))


def compare(found, listed_):
    """(new, stale): the found keys or counts beyond the listed ones, and the listed keys or counts beyond
    the found ones, as (key, found count, listed count) tuples."""
    new, stale = [], []
    for key, f in sorted(found.items()):
        had = listed_.get(key, {}).get('count')
        if f['values']['count'] > (had or 0):
            new.append((key, f['values']['count'], had))
    for key, had in sorted(listed_.items()):
        now = found.get(key, {}).get('values', {}).get('count')
        if (now or 0) < had['count']:
            stale.append((key, now, had['count']))
    return new, stale


def growth(entries, head):
    """The entries or counts beyond HEAD's baseline, for the rules HEAD's baseline lists."""
    out = []
    for key, values in sorted(entries.items()):
        if key[0] not in head['rules']:
            continue
        had = head['exceptions'].get(key, {}).get('count')
        if values['count'] > (had or 0):
            out.append('%s %s %s: %d (%s at HEAD)' % (key + (values['count'], had or 'none')))
    return out


ABOUT = ('Permitted exceptions of the architecture conformance test (tests/test_architecture.py), keyed by '
         'rule, module and name with their counts of sites. The list only shrinks: a new exception or a '
         'higher count fails; an entry that no longer occurs, or whose count fell, fails until python '
         'tests/test_architecture.py --prune removes it or lowers the count; the test fails while the list '
         'holds more than the version committed at HEAD.')


def write_baseline(rules, entries):
    """Write the baseline: sorted entries, one per line, LF line ends."""
    rows = []
    for key in sorted(entries):
        e = dict(zip(KEY_FIELDS, key))
        e['count'] = entries[key]['count']
        rows.append('  ' + json.dumps(e, ensure_ascii=False))
    text = ('{\n "about": %s,\n "rules": %s,\n "exceptions": [\n%s\n ]\n}\n'
            % (json.dumps(ABOUT), json.dumps(list(rules)), ',\n'.join(rows)))
    if not rows:
        text = text.replace('[\n\n ]', '[]')
    with open(BASELINE_FILE, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)


def listed(rule):
    return {k: v for k, v in load_baseline()['exceptions'].items() if k[0] == rule}


PRUNE = False


def run_rule(rule):
    """Run one rule against the baseline: a new exception or a higher count fails; a stale entry or count
    fails (a pruning run prunes before the rules run)."""
    found = findings(rule)
    new, stale = compare(found, listed(rule))
    print('%-8s %-38s listed %4d  found %4d  new %3d  stale %3d'
          % (rule, TITLES[rule], len(listed(rule)), len(found), len(new), len(stale)))
    for key, value, had in new:
        print('       NEW   %s %s: %d (baseline %s)' % (key[1], key[2], value, 'none' if had is None else had))
        for site in found[key]['sites'][:5]:
            print('             %s' % site)
    for key, value, had in stale:
        print('       %s %s %s: %s (baseline %d)' % ('pruned:' if PRUNE else 'STALE (run --prune):', key[1], key[2],
                                                     'gone' if value is None else value, had))
    assert not new, '%s: %d new exceptions or counts above the baseline' % (rule, len(new))
    assert PRUNE or not stale, ('%s: %d baseline entries or counts above what the code holds: run python '
                                'tests/test_architecture.py --prune and review the diff' % (rule, len(stale)))


def test_layer_table():
    """Every lpk module has a layer; every row of LAYERS names a current module."""
    missing, rows = unassigned(), stale_rows()
    for name in missing:
        print('       no layer: %s (%s): add it to LAYERS' % (name, modules()[name].rel))
    for row in rows:
        print('       row %s names no module: remove it, or list a planned name in PLANNED' % row)
    assert not missing, '%d lpk modules have no layer in LAYERS' % len(missing)
    assert not rows, '%d LAYERS rows name no module' % len(rows)


def test_layers():
    run_rule('layers')


def test_host_importability():
    failures = host_failures()
    for name, error in sorted(failures.items()):
        print('       %s does not import on the host: %s' % (name, error))
    assert not failures, '%d host modules fail to import for a reason other than Blender' % len(failures)
    run_rule('host')


def test_private_access():
    run_rule('private')


def test_dynamic_loading():
    run_rule('dynamic')


def test_local_library():
    run_rule('local')


def test_local_rule_sees_every_import_form():
    """The local rule's scanner finds a module-level import, a from-import, a function-local one and a
    dynamic one in a module of lpk (parsed from text, never written), and not a name that only starts
    the same."""
    source = ('import lpk_local.forms.a\n'
              'import lpk_localish\n'
              'from lpk_local.forms import b\n'
              'def f():\n'
              '    from lpk_local import forms\n'
              '    import importlib\n'
              '    return importlib.import_module("lpk_local.forms.c")\n')
    probe = Module('lpk.forms.probe', os.path.join(ROOT, 'lpk', 'forms', 'probe.py'), source)
    seen = sorted(Scanner(probe).local)
    assert seen == [('lpk_local', 5), ('lpk_local.forms', 3), ('lpk_local.forms.a', 1),
                    ('lpk_local.forms.c', 7)], seen


def test_baseline_complete():
    """The baseline lists every rule of this test, so that a rule's entries are recorded when it lands."""
    rules = load_baseline()['rules']
    assert sorted(rules) == sorted(RULES), ('%s lists the rules %s, this test has %s: run python '
                                            'tests/test_architecture.py --record' % (BASELINE_REL, rules, list(RULES)))


def test_baseline_only_shrinks():
    """The baseline holds no entry and no count beyond its version at HEAD, for the rules HEAD lists."""
    head = _head()
    if head is None:
        print('     note: %s is not committed at HEAD in this format: growth is not checked' % BASELINE_REL)
        return
    grown = growth(load_baseline()['exceptions'], head)
    for line in grown:
        print('     GROWN %s' % line)
    assert not grown, 'the baseline only shrinks: %d entries or counts added since HEAD' % len(grown)


def prune():
    """Remove the stale entries and lower the counts that fell; never add an entry or raise a count."""
    data = load_baseline()
    kept, removed, lowered = {}, 0, 0
    for key, values in data['exceptions'].items():
        now = findings(key[0]).get(key, {}).get('values', {}).get('count') if key[0] in CHECKS else None
        if not now:
            removed += 1
            continue
        lowered += now < values['count']
        kept[key] = {'count': min(now, values['count'])}
    write_baseline(data['rules'], kept)
    print('pruned: %d entries removed, %d lowered' % (removed, lowered))


def record():
    """Write the baseline from the findings; refused when HEAD holds a baseline the result would exceed.
    Returns True when it wrote."""
    entries = {key: f['values'] for rule in RULES for key, f in findings(rule).items()}
    head = _head()
    grown = growth(entries, head) if head is not None else []
    if grown:
        for line in grown:
            print('     REFUSED %s' % line)
        print('record refused: %d entries or counts beyond the baseline committed at HEAD. Fix the code; a '
              'changed rule changes this test\'s tables, through ARCHITECTURE.md "Changing the architecture"'
              % len(grown))
        return False
    write_baseline(RULES, entries)
    counts = collections.Counter(key[0] for key in entries)
    print('recorded %d entries: %s' % (len(entries), ', '.join('%s %d' % (r, counts[r]) for r in RULES)))
    return True


if __name__ == '__main__':
    import traceback
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')
    args = sys.argv[1:]
    if set(args) - {'--prune', '--record'} or len(args) > 1:
        sys.exit('usage: python tests/test_architecture.py [--prune | --record]')
    if '--record' in args:
        sys.exit(0 if record() else 1)
    PRUNE = '--prune' in args
    if PRUNE:
        prune()
    failed = 0
    tests = [(name, fn) for name, fn in list(globals().items()) if name.startswith('test_') and callable(fn)]
    for name, fn in tests:
        try:
            fn()
        except AssertionError as e:
            failed += 1
            print('FAILED  %s: %s' % (name, e))
        except Exception:
            failed += 1
            print('ERROR   %s' % name)
            traceback.print_exc()
    print('%d passed, %d failed' % (len(tests) - failed, failed))
    sys.exit(1 if failed else 0)
