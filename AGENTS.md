# lowpoly-kit - instructions for agents

lowpoly-kit (package `lpk`) is a toolkit for AI agents that model low-poly characters in Blender through
Blender MCP: parametric shape blanks, primitives, surface tools, a colour atlas, rigging and skinning,
review tools and export, run as the stages of one model module, plus one skill for the steps of building a model.

## Status

The toolkit (version 0.3) is one model module per character run by a stateless stage runner, `lpk.run`;
the worked example is `examples/mannequin/mannequin.py` and the skill `skills/lowpoly`.
The structure, the one place for each kind of extension and the areas that do not yet conform are in
[ARCHITECTURE.md](ARCHITECTURE.md).
Verification follows [CONTRIBUTING.md](CONTRIBUTING.md#verifying-a-change): same-version determinism is
strict, the worked example run in Blender is the acceptance model, and earlier outputs are diagnostics,
not pass/fail.

## Rules

- Read [ARCHITECTURE.md](ARCHITECTURE.md) before changing `lpk/`, `lpk_dev/`, `dev/` or `tests/`. A change fits it
  or amends it first through its procedure. Never add a local workaround, a parallel route, or a
  parameter or branch that only keeps earlier output unchanged.
- Production delivery defaults to requested model files and a short message with paths/blockers.
  Detailed reports are opt-in. Keep the character's folder (model module, views, references, edits)
  and its local forms (`lpk_local/forms/<model>/`).
- English everywhere: code, comments, docstrings, docs, commit messages.
- No names from projects this toolkit came from: no game, character or repository names, no private
  paths. `python dev/scrub_check.py` with `LPK_SCRUB_WORDS` set to the maintainer's word list must report
  0 hard hits over every tracked file (CONTRIBUTING.md); without the list it proves nothing. A change that
  brings work from a contributor's own projects is also scrubbed with that contributor's own list
  (CONTRIBUTING.md, "Your own word list").
- Skills carry the workflow only; every number and name lives in `lpk` and its data.
  `python tests/test_skills.py` keeps the skills in step with the code.
- Blender space: metres, Z up, models face -Y, `.L` is +X. Builders carry a face palette index (`pal`)
  and a vertex part index (`part`); `finish` triangulates and writes them to the object.
- Determinism is part of the contract: the same model and inputs give the same vertex order, UVs and
  weights. Seed every random choice; never iterate geometry in hash order.
- A docstring states what a function builds, its parameters with units, what it returns and the
  non-obvious causal limits the code does not show. Docs, skills, comments and generated references state
  operational facts, mechanisms, conditions and limits, never how they were found: development history
  and run measurements stay private (CONTRIBUTING.md). Keep comments only for non-obvious ordering, implicit
  behaviour, interacting math or an algorithm that must stay exact; delete comments that restate code.
- Write files as bytes or with `newline='\n'` on Windows: the repository uses LF.
- Commit messages explain why for non-trivial decisions.
