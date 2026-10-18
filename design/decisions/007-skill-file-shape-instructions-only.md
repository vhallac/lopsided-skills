# 007 — Skill files are instructions only

**Status:** accepted

## Context

Review of PR #14 (round 1, F3) found `emergent-contract-coding/SKILL.md`
carrying an explanatory preamble ("source for this section is
`design/requirements/…`; this skill presents them as executable
instructions") and inline requirement tags (`(R6)`, `(R26)`, …). A skill
file is a set of instructions, not a users' manual; commentary wastes
tokens, dilutes attention, and invites more prose in later edits.

## Decision

A `SKILL.md` contains only instructions: triggers, steps, constraints,
verification. It must not contain:

- explanatory preamble or commentary about where content came from or why
  it exists;
- references to requirements documents, issues, or other non-instruction
  artifacts in the file body;
- inline traceability tags (e.g. `(R6)`), banned outright — the
  one-to-one clause mapping is checked at review time, not embedded as
  annotations.

Traceability, if needed, is carried outside the skill file: in the design
decision / requirements docs and the review's traceability audit, never
inside the skill itself. Supersedes the tagging style used in decision
006's audit protocol where they conflict.

## Consequences

Skill files get smaller and read as pure procedure. Traceability lives in
one place (the review audit / requirements docs); editing a skill never
requires touching tags. Reviewers must check clause mapping externally.

## Enforced by

review (traceability audit; no automated gate)
