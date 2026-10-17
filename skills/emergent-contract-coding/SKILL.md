---
name: emergent-contract-coding
description: NOT for auto-selection. The write-loop section of the emergent contract coding methodology. Activates only via an explicit opt-in statement in the repository's AGENTS.md (or equivalent) — see the activation guard below. Conversation mentions, issue text, or code references do not activate this skill.
---

# Emergent Contract Coding — Write Loop

The write loop is the set of steps an agent executes for one work item — one
specification implemented or changed, ending in one commit. The normative
source for this section is `design/requirements/emergent-contract-coding-req.md`
(§3, R6–R10 and R21–R23); this skill presents them as executable instructions.

## Activation guard (R26)

This skill MUST NOT become active during ordinary day-to-day development. It
activates only when the repository's `AGENTS.md` (or equivalent) contains an
explicit opt-in statement, for example:

> This project uses emergent contract coding; always use the
> `emergent-contract-coding` skill for development.

Mentions of the style in conversation, issue text, or code do not activate the
skill. Activation requires the `AGENTS.md` statement, nothing else. If the
statement is absent, stop: do not apply any instruction in this section.

## Main scenario

<!-- unit-002: steps 1–7 + extensions 2.a / 2.b / 3.a (R6–R9) — to be authored -->

## Capability wishes

<!-- unit-003: extensions 5.a–5.d + wish-declined record (R10, R14, R16, S6) — to be authored -->

## Verification duties

<!-- unit-004: R21–R23 verification and regression-coverage duties — to be authored -->

## Constraints and boundaries

<!-- unit-004: constraints (R26 guard, S6 by name, #12 postponed) — to be authored -->
