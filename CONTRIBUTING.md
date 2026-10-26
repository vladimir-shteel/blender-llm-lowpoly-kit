# Contributing to lowpoly-kit

This guide is for anyone, human or agent, who changes `lpk/`, the skill or the docs. The rules in
[AGENTS.md](AGENTS.md) apply throughout: English, LF line endings, determinism, docstrings that state
mechanisms and limits, and no names from the projects the kit came from. The kit's layers, the model
module contract and the place for each kind of extension are fixed in [ARCHITECTURE.md](ARCHITECTURE.md);
a change fits it or amends it first.

## The boundary

The skill says what to do next. The toolkit owns every number and name. A skill card names a call or a
parameter and says when and why to use it. It never states a default, a count of sides, rings or
triangles, or a length that places geometry: those live in form defaults and their docstrings, tool
constants, export profiles and each model's own module. A model's style lives in its module, as named
constants with a one-line reason.

Tools measure and report; they never decide for the human. A tool returns numbers, lists and paths, never
pass/fail rows or prose verdicts (ARCHITECTURE.md "Anti-patterns").

## Docstrings

- A docstring states what the function builds or measures, its parameters with units, what it returns, the
  mechanism a caller relies on and the conditions and limits it holds under. A default sized on a
  reference body states that body's size as a scale assumption with its limits.
- A function that returns a report describes every key of that report in its docstring.
- Docstrings, comments, skill cards and docs state current behaviour, mechanisms, applicability and limits.
  How a rule or a default was found (trials, earlier builds, run measurements) stays in private
  development evidence: none of them carries it. A claim one observation supports keeps its uncertainty.

## Forms and presets

Forms live in two libraries. The **shared** library `lpk/forms/<area>.py` is part of the kit, tracked in
git. The **local** library `lpk_local/forms/<model>/<area>.py` at the kit's root is ignored by git and
holds the forms an agent wrote for one user's models, in the package of the model that first used each;
its modules import the kit's kernels and forms, and no `lpk` module imports them
(`tests/test_architecture.py`, rule `local`).

A form a model needs that the library lacks is written at once in the local package of that model; the
model module keeps only composition (ARCHITECTURE.md, "Where forms live"). A model never
imports another model's package: a form another model has is copied into its own package and changed
there. Similar forms in several packages are the signal to propose one shared form; the agent never
moves a form into the shared library on its own. Moving a form to the shared library is the human's decision:
on request it moves from the local library into `lpk/forms/<area>.py`, similar forms merged into one, with
a docstring, a host test for its pure parts and its entry in the catalogue of
`skills/lowpoly/references/forms/README.md`, and the models the human names import it from there, their
local copies removed. The move changes the user's copy of the kit; the maintainer reviews it into the
repository.
When a second model of the same style repeats the same set of overrides for a form, that set may become a
named preset: a module constant next to the form, like `head.MUZZLE_KEYS`, always passed explicitly. The
maintainer approves every change to the shared library.

## Changing a contract

The rules are in [ARCHITECTURE.md](ARCHITECTURE.md#changing-a-contract). In short: add a parameter only for
an independent per-call dimension; replace the contract, with its tests, docs and teaching, when the new
behaviour is the better default or the old one would stay only to keep earlier output unchanged; never keep
a parallel route. A refusal of bad input fails fast with a message that names the fix.

## Verifying a change

- **Same-version determinism** is strict: the same model, inputs, kit version and environment give
  identical vertex order, UVs, weights, images and export bytes on a clean rebuild.
  `lpk_dev/fingerprint.py` snapshots every array a stage leaves on the objects and images and compares two
  snapshots. Compare runs without the pack cache (`out/<NAME>.pack.json`), which restores packs.
- **The worked examples** (`examples/mannequin`, a character, `examples/trooper`, a light character,
  `examples/barrel`, a prop, and `examples/turret`, a rigid mechanism) are the
  acceptance models: a change that can touch geometry, UVs, weights or exports runs their stages in
  Blender before integration, and every `reimport` of their exports has empty `diffs`. The stages run in
  Blender through the bridge or in background mode (`blender -b`), where the 3D Viewport's area exists but
  has no OpenGL render: only the captures need Blender's user interface. `tests/blender/*.py` run the
  worked examples' paths in background Blender and fail without it.
- **An intentional output change** says so in its commit message with a before/after summary and the
  reason. Earlier outputs are diagnostics, not pass/fail.

## The skill and the code

`tests/test_skills.py` keeps the skill in step with the code: every `lpk` and `run` name a card names
exists, Python fences parse, links and anchors resolve, stage tuples name runner stages, and no card names
an entry point or term the kit does not have (the test's `NOT_IN_KIT`). Run it after changing a card or renaming a public name.

## Origin names: the scrub

The kit carries no names from the projects it came from: no game, character or repository names and no
private paths. The word list that finds them is private. Run the scrub with it:

```sh
LPK_SCRUB_WORDS=/path/to/words.json python dev/scrub_check.py
python dev/scrub_check.py --words /path/to/words.json
```

It must report 0 hard hits. The list must live outside the kit: the script refuses a word list inside it.
It scans every file git would commit: Python comments and docstrings, and every line of other text files.
Hits in identifiers and string literals are listed apart as code hits. Without the private list the script
runs the neutral `dev/scrub_words.example.json`, which shows the file format, and says so: only a run with
the private list counts.

### Your own word list

The maintainer's list knows only the projects the kit came from. A change that brings work from your own
projects (a form, a technique card, a skeleton or export profile, an example) can carry their names, which
no list in the kit knows. Before you send such a change, write a list of your own in the same format and
run the scrub with it as well:

```sh
python dev/scrub_check.py --words ~/lpk-scrub/my_words.json
```

- **hard**: names that must never appear in a comment, docstring or text file: your projects, games,
  characters, studios, repositories, user names and private paths (a pattern such as `[A-Z]:\\Users\\` or
  `/home/<you>/` catches a pasted path).
- **soft**: words that are allowed in context but worth a look on every hit, such as an engine named in a
  compatibility note.
- Write each entry as a regular expression; `\b` around a short name keeps it from matching inside other
  words.

Keep the list outside the kit, as the script requires, and fix every hard hit before the change goes up.
A code hit (an identifier or a string literal) is renamed in the change itself, with its tests.

The scrub finds only the words a list holds. The rest of the rule is for review: docs, cards, comments and
docstrings state what the code does and its limits, never where a recipe came from, which model it was
tuned on or what a run measured.

## Running the tests

The host tests need plain Python with numpy, never Blender. Modules that import `bpy` are parsed with `ast`
or loaded against stand-ins (`tests/blender_stand_ins.py`). Run each file from the kit root:

```sh
for t in tests/test_*.py; do python "$t" || echo "FAILED $t"; done
```

pytest also runs them where it is installed.
