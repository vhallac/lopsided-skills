---
name: emergent-contract-coding
description: NOT for auto-selection. The write-loop and structure-pass sections of the emergent contract coding methodology. Activates only via an explicit opt-in statement in the repository's AGENTS.md (or equivalent) — see the activation guard below. Conversation mentions, issue text, or code references do not activate this skill.
---

# Emergent Contract Coding

The write loop is the set of steps an agent executes for one work item — one
specification implemented or changed, ending in one commit. The structure
pass is the set of steps that ends every work item after the flow is written.

## Activation guard

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
   postponed optimization and is not required.
3. **Judge whole-contract fit for each interface you want to reuse.** Reuse an
   existing _lax_ interface only when its whole contract fits the need: results,
   error results and side effects together. Resemblance of names or code is not
   evidence of fit.
4. **Write the flow as one linear function, check-then-act.** Validate everything
   before the first external call that changes anything. Keep external effects
   late. Return error outcomes inline. Call other flows only through their
   interfaces.
5. **Handle any capability wish** per the order in Capability wishes.
6. **Author the flow's behavior-level verification and regression coverage as
   part of the work item** — see Verification duties.
7. **Hand off to the structure pass** at the end of the work item; the commit
   checks (full suite + registry/log) are shared with the structure pass — the
   structure pass runs them; the write loop must not run them itself.

Extensions to step 2:

- **2.a.** IF a _contract_ is too thin to judge fit; THEN flag it for repair or
  deliberately inspect the body — and record which you did. Never judge
  suitability from an interface's name.
- **2.b.** IF the isolated-context walk is in use and the isolated-context skill
  is unavailable; THEN pause for the operator — the walk cannot be satisfied
  without the isolated skill, and unattended fallback is absent by design. (Dormant
  while the walk runs in the writing context.)

Extensions to step 3:

- **3.a.** IF no existing lax interface fits the need; THEN call the _output
  interfaces_ directly; do not reuse on name or code resemblance.

## Capability wishes

When an interface lacks a needed capability, handle the wish in this order.
Stop at the first branch that resolves the wish; never skip ahead.

- **5.a.** IF the wish is evidence that the flow and that interface should be
  merged; THEN record it as a merge candidate for the structure pass. The wish
  alone never satisfies the merge test — only observed co-change does —
  and any merge happens only through the structure pass.
- **5.b.** IF the interface is lax; THEN route the change through the
  interface-change check in the structure pass: change it in place when
  all call sites want the same change; create a new interface and record a
  `divergence` entry when they do not.
- **5.c.** IF the interface is rigid; THEN never change its contract. A wrapper
  or caller-side workaround is acceptable only if it achieves the need through
  the rigid interface's existing contract with the required semantics.
  Otherwise, pause: the change belongs to the owner's request path. Never
  present a new wrapper as solving a capability the rigid interface lacks.
- **5.d.** IF the wish is declined; THEN record it once as a `wish-declined`
  entry through the append tool, so it is not re-argued at every later
  write. Declined wishes stay declined until new qualifying evidence appears.


## Verification duties

Verification is part of the work item, not a follow-up task.

- **Verify behaviors, not fragments.** Verify each behavior through its
  input interface, observing the _entry_ (input and state precondition), the
  _results_, and the interactions with external interfaces. Lax interfaces and
  helpers are not separate verification units by default, and helper tests
  never replace the behavior check. The number of test cases is not prescribed.
- **Regression coverage after confirmed defects.** When a defect is
  confirmed, add or update verification that would expose the defect through
  the affected behavior, where practicable. There is no one-test-per-bug rule.
- **Test cadence.** Run automated tests when a coherent behavior change
  is ready, not after every edit. The full-suite and registry/log checks at
  commit are covered in step 7.

## Constraints and boundaries

- **Activation stays guarded.** This section never becomes active by
  conversation, issue text, or code reference — only the `AGENTS.md` opt-in
  statement activates the skill (see the Activation guard above).
- **The append tool is referenced by name only.** This skill does not
  embed, restate, or depend on the append tool's implementation; it only names
  it where declined wishes must be recorded.
- **Isolated-context walking (issue #12) is postponed.** The write loop runs
  the contract walk in the writing context; the only trace of the isolated
  variant is the dormant extension 2.b. No runtime dependency on the
  isolated-context skill exists in this section.

---

# Emergent Contract Coding — Structure Pass

The structure pass is the pass that ends every work item after the flow is
written. It gives every relevant call site an explicit outcome, runs the
interface-change and merge tests, makes exactly one structure decision per
candidate, and shapes and prunes the resulting interfaces. The write loop
hands off here.

The activation guard above applies to this section too: without the
`AGENTS.md` opt-in statement, none of the steps below apply.

## Main scenario

Execute these steps for the work item's change, after the write loop's step 7
hand-off.

1. **Regenerate and check the registry.** Run `contracts generate` and
   `contracts check`. The registry is never hand-edited.
2. **List the blast radius.** Run `contracts affected --diff HEAD` — every
   affected interface, all its call sites, and interfaces whose call sites
   were removed (flagged for step 8).
3. **Give every relevant call site an explicit outcome:** updated, left
   unchanged with a recorded reason, or paused with an `unresolved` entry.
   Uncertainty is never resolved by silence. Propagate caller updates until
   stable, within ownership: rigid interfaces and systems owned by others are
   outside the boundary; input interfaces owned by this project stay inside.
   Pause if a propagated change would alter externally visible behavior. Do
   not re-examine any interface created, changed, or merged during this same
   pass.
4. **Run the interface-change check** for each existing interface the change
   must alter — a disagreement test, not a likeness test:
   - **Rigid** → never changed; route through the write loop's
     rigid-interface wish handling (its step 5.c).
   - **Lax, all call sites want the same change** → change it in place and
     update every caller in this work item.
   - **Lax, call sites want different things** → create a new interface for
     the new need, leave the old one serving its callers, record a
     `divergence` entry.
5. **Run the merge test on observed co-change.** Merge only when all three
   hold: (a) the same change was needed in two or more places in this work
   item; (b) the changed region is the same rule and could be written once;
   (c) the diff matches none of the excluded causes below. One qualifying
   event is enough; similar inputs, overlapping code, or a shared output
   interface are never sufficient on their own. Check exclusions by comparing
   the diff against the list, not by inferring intent. Never merge
   automatically.

   Excluded causes — co-change from these is not merge evidence:

   - **Rigid-interface ripple:** callers changed because a rigid interface
     changed (for example a library upgrade).
   - **Shared-interface or shared-state ripple:** callers changed because a
     shared interface or shared state they all use changed. This includes
     caller updates made by this structure pass itself (steps 3 and 4), and
     changes to a state schema.
   - **Batch edit:** one request, refactor or codemod edited both places with
     no shared logic in the changed region. Exception: it qualifies when the
     changed region is literally the same transformation.
   - **Asymmetric adaptation:** one requirement touched both places, but each
     needed its own adaptation. The symmetric case — one rule applied
     identically — may merge.
   - **Drive-by edits:** convenience changes made "while here".
6. **Make exactly one structure decision per considered candidate — merge,
   divorce, or leave — and record it with its reason via `contracts log
   append`.** Record `leave` only when a candidate was actually considered
   and preserved, not for every pair that fails the merge test. Metrics may
   inform review but never trigger a decision. New qualifying evidence about
   a previously considered pair may reopen it in this pass — prior `leave`
   entries do not forbid that.
7. **Shape the outcome.** A merged interface reaches only as far as the
   regions that actually co-changed, and its contract is stated without
   referring to its callers. "No interface; keep it inline" is a valid
   outcome. A boundary chosen only because it coincides with a change site is
   forbidden. When serving divergent call sites would require a flag or mode
   parameter — or recorded `divergence` entries show its callers no longer
   want the same thing — split or dissolve the interface instead. Never add
   the flag.
8. **Run the liveness check** for each interface flagged in step 2 whose call
   sites were removed: using the registry, check each contract clause for a
   remaining live reader and remove the clauses none uses. The check runs at
   this change, never as a sweep, and it runs whether or not a merge
   happened.
9. **Commit.** The trial repo's gate runs `contracts check` and `contracts
   log check`, and the full test suite runs green; all exit 0 and the work
   item ends. These checks are shared with the write loop's step 7 — this
   pass runs them; it does not own them alone.

## Substrate scripts

The contracts CLI lives at `<skill-directory>/scripts/contracts/` (a Python
package) with a launcher at `<skill-directory>/scripts/contracts-cli.py`.
Run it as `python3 <skill-directory>/scripts/contracts-cli.py <command>`
from anywhere, or `python3 -m contracts <command>` from the `scripts/`
directory. Its tests run with `python3 -m unittest discover contracts/tests`
from that same directory.

Language support: Python sources (`.py`) are always extracted (stdlib `ast`);
TypeScript sources (`.ts`/`.tsx`) are extracted when tree-sitter is installed
(`pip install -r <skill-directory>/scripts/requirements.txt`); other file
extensions in the `[source] tree` are skipped. A single `contracts.toml` may
mix Python and TypeScript directories; interfaces from both extractors are
merged in one registry.

Extensions to step 2:

- **2.a.** IF the `affected` output marks unresolved calls that affect the
  change; THEN pause for the operator.

Extensions to step 3:

- **3.a.** IF a call site's relevance, impact, or update cannot be
  determined; THEN pause and record `unresolved` — never silence.
- **3.b.** IF a propagated change would alter externally visible behavior;
  THEN pause for the operator.

Extensions to step 5:

- **5.a.** IF a co-change matches an excluded cause (rigid-interface ripple,
  shared-interface/state ripple, batch edit without identical transformation,
  asymmetric adaptation, drive-by edit); THEN it is not merge evidence; the
  merge test fails. Record `leave` only if the pair was genuinely considered
  as a candidate.
- **5.b.** IF the co-change's cause matches no exclusion but cannot be
  determined; THEN pause and record `unresolved`.

Extensions to step 6:

- **6.a.** IF new qualifying evidence about a previously considered pair
  exists; THEN the pair may be considered again in this pass — prior `leave`
  entries do not forbid it.

Extensions to step 9:

- **9.a.** IF the registry or log check fails at commit; THEN the commit is
  blocked; resolve within the work item.

## Constraints and boundaries

- **Activation stays guarded.** This section never becomes active by
  conversation, issue text, or code reference — only the `AGENTS.md` opt-in
  statement activates the skill (see the Activation guard above).
- **Substrate scripts are referenced by name only.** This section names
  `contracts generate` / `check` / `affected` / `log append` / `log check`
  and the registry's never-edit rule; it does not embed or depend on their
  implementation. Authoring is independent of the substrate scripts.
- **Entry kinds are not invented here.** The entries used (`merge`,
  `divorce`, `leave`, `divergence`, `unresolved`) are defined by the
  requirements and validated by the append tool; this section introduces no
  new kinds.
- **No recursion, no sweeps.** The pass does not re-examine interfaces it
  created or merged in the same pass (step 3), and the liveness check runs
  only at a change that removed callers, never as a sweep (step 8).
- **Metrics never decide.** Coupling and cohesion metrics may validate a
  proposed boundary but never propose one or trigger a decision.
- **Scope exclusions.** No recursive restructuring, no single-caller merges,
  and none of the other merge-test exclusions; the write loop and
  verification authoring are owned by the write-loop section above.
