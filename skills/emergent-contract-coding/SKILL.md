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

When an interface lacks a needed capability, handle the wish in this order.
Stop at the first branch that resolves the wish; never skip ahead. (R10)

- **5.a.** IF the wish is evidence that the flow and that interface should be
  merged; THEN record it as a merge candidate for the structure pass. The wish
  alone never satisfies the merge test (R16) — only observed co-change does —
  and any merge happens only through the structure pass.
- **5.b.** IF the interface is lax; THEN route the change through the
  interface-change check (R14) in the structure pass: change it in place when
  all call sites want the same change; create a new interface and record a
  `divergence` entry when they do not.
- **5.c.** IF the interface is rigid; THEN never change its contract. A wrapper
  or caller-side workaround is acceptable only if it achieves the need through
  the rigid interface's existing contract with the required semantics.
  Otherwise, pause: the change belongs to the owner's request path. Never
  present a new wrapper as solving a capability the rigid interface lacks.
- **5.d.** IF the wish is declined; THEN record it once as a `wish-declined`
  entry through the append tool (S6), so it is not re-argued at every later
  write. Declined wishes stay declined until new qualifying evidence appears.


## Verification duties

Verification is part of the work item, not a follow-up task.

- **Verify behaviors, not fragments (R21).** Verify each behavior through its
  input interface, observing the _entry_ (input and state precondition), the
  _results_, and the interactions with external interfaces. Lax interfaces and
  helpers are not separate verification units by default, and helper tests
  never replace the behavior check. The number of test cases is not prescribed.
- **Regression coverage after confirmed defects (R22).** When a defect is
  confirmed, add or update verification that would expose the defect through
  the affected behavior, where practicable. There is no one-test-per-bug rule.
- **Test cadence (R23).** Run automated tests when a coherent behavior change
  is ready, not after every edit. The full-suite and registry/log checks at
  commit are shared with the structure pass — the structure pass runs them; the
  write loop must not run them itself. Any failure blocks the commit and is
  resolved within the work item.

## Constraints and boundaries

- **Activation stays guarded (R26).** This section never becomes active by
  conversation, issue text, or code reference — only the `AGENTS.md` opt-in
  statement activates the skill (see the Activation guard above).
- **The append tool is referenced by name only (S6).** This skill does not
  embed, restate, or depend on the append tool's implementation; it only names
  it where declined wishes must be recorded.
- **Isolated-context walking (issue #12) is postponed.** The write loop runs
  the contract walk in the writing context; the only trace of the isolated
  variant is the dormant extension 2.b. No runtime dependency on the
  isolated-context skill exists in this section.
