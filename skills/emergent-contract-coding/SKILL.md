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

Execute these steps for one work item — one specification implemented or changed,
ending in one commit. Steps 5's extensions are listed under Capability wishes.

1. **Read the specification.** Identify the _input interface_ it names and the
   _output interfaces_ it must reach.
2. **Walk the contracts backwards.** Starting from those output interfaces, walk
   backwards through the interfaces that lead to them, collecting _contracts
   only, never bodies_. The result is the relevant interface set and the call
   order between those interfaces. How to compose a route from the set is up to
   you. The walk runs in the writing context; an isolated-context walk is a
   postponed optimization and is not required. (R6)
3. **Judge whole-contract fit for each interface you want to reuse.** Reuse an
   existing _lax_ interface only when its whole contract fits the need: results,
   error results and side effects together. Resemblance of names or code is not
   evidence of fit. (R8)
4. **Write the flow as one linear function, check-then-act.** Validate everything
   before the first external call that changes anything. Keep external effects
   late. Return error outcomes inline. Call other flows only through their
   interfaces. (R9)
5. **Handle any capability wish** per the order in Capability wishes (R10);
   record declined wishes as `wish-declined` once.
6. **Author the flow's behavior-level verification and regression coverage as
   part of the work item** — see Verification duties (R21–R22).
7. **Hand off to the structure pass** at the end of the work item; the commit
   checks (full suite + registry/log) are shared with the structure pass (R23).

Extensions to step 2:

- **2.a.** IF a _contract_ is too thin to judge fit; THEN flag it for repair or
  deliberately inspect the body — and record which you did. Never judge
  suitability from an interface's name. (R7)
- **2.b.** IF the isolated-context walk is in use and the isolated-context skill
  is unavailable; THEN pause for the operator — R6 cannot be satisfied without
  the isolated walk, and unattended fallback is absent by design. (Dormant
  while the walk runs in the writing context.)

Extensions to step 3:

- **3.a.** IF no existing lax interface fits the need; THEN call the _output
  interfaces_ directly; do not reuse on name or code resemblance. (R8)

## Capability wishes

<!-- unit-003: extensions 5.a–5.d + wish-declined record (R10, R14, R16, S6) — to be authored -->

## Verification duties

<!-- unit-004: R21–R23 verification and regression-coverage duties — to be authored -->

## Constraints and boundaries

<!-- unit-004: constraints (R26 guard, S6 by name, #12 postponed) — to be authored -->
