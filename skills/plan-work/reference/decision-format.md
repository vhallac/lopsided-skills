# Decision record format

Project-level decisions live under `design/decisions/`. Each decision is a
single markdown file with a numeric ID and a topic slug. The index
(`README.md`) lists every decision on one line.

## Directory layout

```
design/decisions/
  README.md            — index: one line per decision
  NNN-topic-slug.md    — individual decision record
```

## README.md

One indexed line per decision, newest at the top:

```
NNN — topic — Status
```

Example:

```
003 — use-postgres-as-primary-store — accepted
002 — rest-api-versioning — superseded by 004
001 — git-branching-model — accepted
```

## Decision record (`NNN-topic-slug.md`)

```markdown
# NNN — Topic

**Status:** accepted | proposed | superseded (by NNN) | amended (by NNN)

## Context
What is the issue, constraint, or force that demands a decision?
What alternatives were considered?

## Decision
What was chosen and why? Be specific — name the choice, not the process.

## Consequences
What becomes easier, harder, or impossible as a result?
What new constraints does this decision impose on future work?
```

## Enforced by

```markdown
## Enforced by
type | invariant (<script>) | golden (<fixture>) | bug-lock test (<file>) | review only
```

Attaches checks to intent rather than to the implementation. review-change's
decision matrix can verify that the named check exists and runs.

## Status lifecyle

| Status | Meaning |
|--------|---------|
| `proposed` | Suggested but not yet accepted; future plans treat it as advisory |
| `accepted` | In force; plans must consult and comply |
| `superseded (by NNN)` | Replaced by a newer decision; the record stays as provenance |
| `amended (by NNN)` | Modified by a newer decision; read both together |

When a plan changes behavior covered by an accepted decision, the promotion
step must mark the old record `superseded (by NNN)` or `amended (by NNN)`.
Never leave two accepted decisions in conflict — stale decisions make review
flag correct code.

Plans reference decisions by this stable handle: the `NNN-topic-slug`
filename (a plan-work `decision-ref` entry).

## Assignment

The next available NNN is `max(existing IDs) + 1`. If no decisions exist, start
at `001`. Never renumber — IDs are stable references.