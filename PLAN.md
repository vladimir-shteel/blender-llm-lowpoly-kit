# lowpoly-kit plan

The kit's structure is in [ARCHITECTURE.md](ARCHITECTURE.md). Open work:

## Further kinds of model

The skill branches by kind of model (`skills/lowpoly/references/kinds/`: `biped`, `prop`, `rigid`,
`quadruped`, `first_person`). Each further kind lands as one card there with what it needs in `lpk` and its
own worked example; the kind stays a notion of the skill, never read by `lpk`. None is planned now.

## Deferred

- The hand unwrap: on the mannequin example, right after `freeze_texture` and before any edit,
  `run.check_uvs` lists hand faces on both hands with a texel density far below the rest of their
  island. The procedural unwrap squashes them, not the check. Fix the hand's
  seams or unwrap so a fresh frozen texture reports no hand faces; an intentional UV change, stated with
  a before/after in its commit.
- **Environment** (modular rooms with door sockets, collision boxes, a palette texture shared by a set of
  rooms): needs its own design before it enters the kit.
- **A set of props in one module**: one model module holds one prop today.
- **The eye view following the head**: the view `'eye'` stands at `EYE` on the rest pose; a clip that turns
  the head (a look, a bob) is seen from where the head rested.
