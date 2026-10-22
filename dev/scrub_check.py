"""List names from the projects this toolkit came from that are left in its files.

The kit carries no game, character or repository names and no private paths. The patterns that find them
are private as well: a JSON file {"hard": [regex, ...], "soft": [regex, ...]} (an "about" string may
describe it) whose path is given by --words or by the environment variable LPK_SCRUB_WORDS. Without
either, the neutral illustration dev/scrub_words.example.json is used and the run says the real list is
missing: a clean result then proves nothing.

Every file git would commit is scanned, from the kit root: the tracked files that exist, plus new files
git does not ignore. Binary files are skipped, and so is the neutral example list while it is the list in
use (it would find its own words). A word list inside the kit is refused unless it is the example: git
would commit it with every name it holds. In a Python file a hard
pattern in a comment or docstring is a hard hit, while one in an identifier or a string literal is listed
apart as a code hit: renaming code changes behaviour and belongs to a reviewed change, not to the scrub.
Every other text file (Markdown, JSON, ...) is read line by line, and any hard pattern in it is a hard
hit. Soft patterns are words allowed in context (an engine-compatibility note, for example); each soft
hit is listed for review and never fails the run.

python dev/scrub_check.py [--words PATH] [path ...]   (default: the whole kit)
Exit status 1 when there is a hard hit, 2 when the word list or a path is unusable or git fails."""
import argparse
import ast
import io
import json
import os
import re
import subprocess
import sys
import tokenize

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE_REL = 'dev/scrub_words.example.json'
EXAMPLE = os.path.join(ROOT, *EXAMPLE_REL.split('/'))
ENV = 'LPK_SCRUB_WORDS'
TEXT_MAX = 110

# f-string and t-string bodies are tokens of their own from Python 3.12 and 3.14 on.
CODE_TOKENS = {tokenize.STRING, tokenize.NAME} | {getattr(tokenize, name) for name in
                                                  ('FSTRING_MIDDLE', 'TSTRING_MIDDLE') if hasattr(tokenize, name)}


def words_path(path=None):
    """(path, source) of the word list to use: path itself when given (source '--words'), else the
    LPK_SCRUB_WORDS environment variable (source 'LPK_SCRUB_WORDS'), else the shipped neutral example
    (source 'example')."""
    if path:
        return path, '--words'
    if os.environ.get(ENV):
        return os.environ[ENV], ENV
    return EXAMPLE, 'example'


def load_words(path):
    """(hard, soft): the patterns of the word list at path, each list compiled into one regex, or None for
    an empty list (an empty alternation would match everywhere).

    Raises ValueError naming the file when a key is missing or unknown, a list holds anything but strings
    or a pattern does not compile."""
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError('%s: expected {"hard": [...], "soft": [...]}' % path)
    if {'hard', 'soft'} - set(data) or set(data) - {'about', 'hard', 'soft'}:
        raise ValueError('%s: keys %s; expected hard, soft and optionally about' % (path, sorted(data)))
    out = []
    for key in ('hard', 'soft'):
        patterns = data[key]
        if not isinstance(patterns, list) or not all(isinstance(p, str) for p in patterns):
            raise ValueError('%s: %s must be a list of regex strings' % (path, key))
        for p in patterns:
            try:
                re.compile(p)
            except re.error as e:
                raise ValueError('%s: %s pattern %r does not compile: %s' % (path, key, p, e)) from None
        out.append(re.compile('|'.join('(?:%s)' % p for p in patterns)) if patterns else None)
    return tuple(out)


def _same_file(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _inside(path, root):
    try:
        rel = os.path.relpath(os.path.abspath(path), os.path.abspath(root))
    except ValueError:
        return False
    return rel != os.pardir and not rel.startswith(os.pardir + os.sep)


def files(paths=(), root=ROOT):
    """Kit-relative paths with forward slashes, sorted, of the files git would commit under paths (the
    whole kit when paths is empty): tracked files that exist, plus untracked files git does not ignore.

    paths: files or folders, relative to the current directory or absolute. Raises ValueError for a path
    outside the kit; git failing raises subprocess.CalledProcessError."""
    specs = []
    for p in paths:
        if not _inside(p, root):
            raise ValueError('%s is outside the kit (%s)' % (p, root))
        specs.append(os.path.relpath(os.path.abspath(p), root).replace(os.sep, '/'))
    listed = subprocess.run(['git', '-C', root, 'ls-files', '-z', '--cached', '--others', '--exclude-standard',
                             '--'] + specs, capture_output=True, check=True).stdout
    names = sorted({n for n in listed.decode('utf-8').split('\0') if n})
    return [n for n in names if os.path.isfile(os.path.join(root, n))]


def _docstrings(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                yield body[0].lineno, body[0].value.value


def _matches(out, line, text, context, pairs):
    for rx, kind in pairs:
        if rx is not None:
            for m in rx.finditer(text):
                out.append((line, kind, m.group(0), context.strip()))


def _scan_python(src, hard, soft):
    """Raises SyntaxError or tokenize.TokenError when src is not Python."""
    out = []
    doc_lines = set()
    for line, text in _docstrings(ast.parse(src)):
        for k, t in enumerate(text.splitlines()):
            doc_lines.add(line + k)
            _matches(out, line + k, t, t, ((hard, 'doc'), (soft, 'doc-soft')))
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            pairs = ((hard, 'comment'), (soft, 'comment-soft'))
        elif tok.type in CODE_TOKENS and tok.start[0] not in doc_lines:
            pairs = ((hard, 'code'), (soft, 'code-soft'))
        else:
            continue
        _matches(out, tok.start[0], tok.string, tok.line, pairs)
    return out


def _scan_text(src, hard, soft):
    out = []
    for n, line in enumerate(src.split('\n'), 1):
        _matches(out, n, line, line, ((hard, 'text'), (soft, 'text-soft')))
    return out


def scan_file(path, hard, soft):
    """(mode, hits) for one file.

    mode: 'python', 'text', 'binary' (a NUL byte or not UTF-8: not scanned) or 'python-as-text' (a .py
    file that does not parse, scanned line by line so that every hit is hard). hits: sorted, unique
    (line, kind, word, line text) tuples; kind is 'doc', 'comment', 'code' or 'text', with '-soft'
    appended for a soft pattern."""
    with open(path, 'rb') as f:
        data = f.read()
    if b'\0' in data:
        return 'binary', []
    try:
        src = data.decode('utf-8')
    except UnicodeDecodeError:
        return 'binary', []
    if path.endswith('.py'):
        try:
            return 'python', sorted(set(_scan_python(src, hard, soft)))
        except (SyntaxError, tokenize.TokenError):
            return 'python-as-text', sorted(set(_scan_text(src, hard, soft)))
    return 'text', sorted(set(_scan_text(src, hard, soft)))


def severity(kind):
    """'soft' for a soft pattern, 'code' for a hard pattern in Python code, 'hard' otherwise."""
    if kind.endswith('-soft'):
        return 'soft'
    return 'code' if kind == 'code' else 'hard'


def scan(paths=(), words=None, root=ROOT):
    """Scan the kit with the word list words_path(words) names.

    Returns {'words': path, 'source': see words_path, 'files': number of files scanned, 'binary': [file],
    'as_text': [unparsed .py file], 'hits': [(file, line, kind, word, line text)], 'hard', 'code',
    'soft': hit counts by severity}. Files are kit-relative with forward slashes, in the order files()
    gives. Raises ValueError for a word list other than the example that lies inside root."""
    path, source = words_path(words)
    example = _same_file(path, EXAMPLE)
    if not example and _inside(path, root):
        raise ValueError('%s: the private word list must live outside the kit, or git would commit it' % path)
    hard, soft = load_words(path)
    report = {'words': path, 'source': source, 'files': 0, 'binary': [], 'as_text': [], 'hits': [],
              'hard': 0, 'code': 0, 'soft': 0}
    for name in files(paths, root):
        full = os.path.join(root, name)
        if example and name == EXAMPLE_REL:
            continue
        mode, hits = scan_file(full, hard, soft)
        if mode == 'binary':
            report['binary'].append(name)
            continue
        report['files'] += 1
        if mode == 'python-as-text':
            report['as_text'].append(name)
        for hit in hits:
            report['hits'].append((name,) + hit)
            report[severity(hit[1])] += 1
    return report


GROUPS = (('hard', 'hard hits (comments, docstrings, text files)'),
          ('code', 'code hits (identifiers and string literals: rename only in a reviewed change)'),
          ('soft', 'soft hits (allowed in context: review each)'))


def main(argv):
    parser = argparse.ArgumentParser(prog='dev/scrub_check.py',
                                     description='List names from the origin projects left in the kit.')
    parser.add_argument('--words', metavar='PATH', help='the private word list (default: $%s)' % ENV)
    parser.add_argument('paths', nargs='*', metavar='path', help='files or folders to scan (default: the kit)')
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')
    try:
        report = scan(args.paths, args.words)
    except (OSError, ValueError, subprocess.CalledProcessError) as e:
        print('scrub_check: %s' % e, file=sys.stderr)
        return 2
    if report['source'] == 'example':
        print('the real word list is missing (set %s or pass --words PATH); using the neutral example %s, '
              'so a clean result proves nothing' % (ENV, os.path.relpath(EXAMPLE, ROOT).replace(os.sep, '/')))
    else:
        print('words: %s (from %s)' % (report['words'], report['source']))
    for group, title in GROUPS:
        rows = [h for h in report['hits'] if severity(h[2]) == group]
        if rows:
            print('%s:' % title)
            for name, line, kind, word, text in rows:
                print('  %s:%d [%s] %s | %s' % (name, line, kind, word, text[:TEXT_MAX]))
    for name in report['as_text']:
        print('not valid Python, scanned as text: %s' % name)
    print('%d files scanned, %d binary skipped; hard hits: %d, code hits: %d, soft hits: %d'
          % (report['files'], len(report['binary']), report['hard'], report['code'], report['soft']))
    return 1 if report['hard'] else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
