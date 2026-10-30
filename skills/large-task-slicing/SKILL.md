---
name: large-task-slicing
description: Break large or long-horizon tasks into externally tracked, bite-sized work units with verification gates. Use when a task spans many files/items, has more than four meaningful steps, may exceed context, or the user asks to work one-by-one, maintain a TODO, or avoid free-reign execution.
---

# Large Task Slicing

Use this skill when a task is too large to trust to conversational memory alone.
The goal is to turn a long-horizon task into a small, externally tracked loop:
define state, do one unit, verify, update state, stop or continue only under
the agreed bounds.

All plan state lives in `.todo/` at the project root. Three files, one plan,
no exceptions.

## When to Use

Activate this skill when ANY of these are true:

- The task has more than 4 meaningful steps.
- The task spans many files, services, reports, records, errors, stories, endpoints, or commits.
- The task involves classification, extraction, conversion, repair, or review over a corpus.
- The task may exceed the current context window.
- The user says: "one by one", "bite sized", "TODO", "remaining", "work through this", "long horizon", "continue where we left off", "do not have free reign", or similar.

Skip this skill for a single-file edit, a direct factual answer, or a task
with an obvious one-command solution — unless the user explicitly asks for
tracked incremental progress.

---

## Bootstrap: `.todo/` Directory

On first activation for a task, create the `.todo/` directory at the project
root (the directory containing `.git/`). If not in a git repository, skip the
exclude step — the skill still works.

```bash
mkdir -p .todo

# Exclude from git (per-clone, never committed)
if ! grep -qxF '.todo' .git/info/exclude 2>/dev/null; then
  echo '.todo' >> .git/info/exclude
fi
```

Verify:

```bash
test -d .todo && grep -qxF '.todo' .git/info/exclude && echo "✓ .todo ready"
```

`.todo/` must not be committed. It is local tracker state.

---

## Single Plan Enforcement

At most one plan exists at any time. The three files in `.todo/` are the plan.

When this skill activates:

1. Check if `.todo/task_plan.md` exists.
2. **Exists → resume.** Read all three files. Report: "Resuming plan from `.todo/task_plan.md` — N units remaining." Do not create a new plan.
3. **Does not exist → new plan.** Proceed to Required First Move.
4. **User wants to abandon the current plan →** archive `.todo/` first (see Plan Cleanup), then create a new one.

> **Gate:** Do not create a second `task_plan.md` alongside an existing one. If a plan already exists, resume it or get explicit user consent to replace it.

---

## The Three Files

### `task_plan.md` — The Plan

Written once when the plan is approved. The structure is fixed; checkboxes
move, but the plan text does not.

```markdown
# [Task name]

## Goal memory
- Final artefacts: ...
- Source inputs: ...
- Quality expectations: ...
- Must not lose: ...

## Bounds
- Work unit: ...
- Stop rule: ...
- Verification per unit: ...

## Work units
1. [ ] Bootstrap outputs / state
2. [ ] Process units
   - [ ] unit-001 — short label
   - [ ] unit-002 — short label
3. [ ] Final verification
4. [ ] Archive and clean up .todo/
```

Ordered items (1, 2, 3, 4) are sequential phases. Unordered children under a
parent are independent — they may be processed in any order, but still require
verification and state updates. Step 4 (archive and clean up) is mandatory in
every plan.

### `findings.md` — Research & Decisions

Every non-obvious discovery, design decision, dead end, or error goes here.
This is the institutional memory of the task — what you learned and why you
chose each path. Append only; do not rewrite history.

```markdown
# Findings: [Task name]

## YYYY-MM-DD
- **Tried:** ... → **Result:** ...
- **Decision:** ... because ...
- **Error:** ... (do not retry without a different approach)
```

Log every error or dead end with enough detail that a future attempt won't
repeat it. After every 2 operations that produce new information, save findings.

### `progress.md` — Session Log

A per-turn log of what was done. One entry per execution loop iteration.

```markdown
# Progress: [Task name]

## YYYY-MM-DD

### Unit: unit-001 — short label
- **Action:** ...
- **Verification:**
  ```text
  [command]
  [output]
  ```
- **State after:** unit-001 checked, N remaining
```

Include the verification command output verbatim. Update after every unit —
do not batch multiple units into one entry.

---

## Key Rules

1. **Never repeat a failure.** If a unit fails, log the error in `findings.md` and mark the unit as blocked. Do not retry the same approach. Change the approach or skip the unit with a reason.

2. **Log all errors.** Every unexpected result, failed verification, or tool error goes into `findings.md` immediately — before moving on.

3. **Save findings after every 2 operations.** "Operations" means tool calls that produce new information (reads, searches, test runs, builds). Prevents losing research context if the session ends unexpectedly.

4. **Verification is external.** A unit is not done until a shell command confirms it. Self-reported completion is not accepted.

5. **The tracker is the source of truth.** If the tracker says a unit is unchecked, it is not done — regardless of what chat memory claims.

---

## Required First Move (New Plan)

Before writing `task_plan.md` for a newly activated task:

1. Restate the original goal in 2-4 bullets.
2. Define the smallest useful work unit.
3. Define verification for one unit.
4. State the stop rule.
5. If the user has not already consented to this decomposition, ask for approval before writing.

Output:

```markdown
## Large-task slicing plan

Goal memory:
- ...

Work unit:
- ...

Verification per unit:
- ...

Stop rule:
- ...

Plan will live in `.todo/` (3 files: task_plan.md, findings.md, progress.md).
```

> **Gate:** Do not write `task_plan.md` until the work unit, verification, and
> stop rule are explicit AND the user has consented (or already consented to
> the decomposition).

---

## Work Unit Selection

Pick the smallest unit that produces meaningful, verifiable progress.

- **Corpus review:** one document section, one record, one report error group, or one category instance.
- **Code repair:** one failing test, one diagnostic, one compiler error cluster, or one file-local bug.
- **Documentation:** one heading, one use case, one endpoint, one diagram, or one page section.
- **Git cleanup:** one logical changeset, not the whole repository.

If a candidate unit cannot be verified independently, split it smaller or
define a better verification command before proceeding.

---

## Execution Loop

For every unit:

1. **Read the plan.** Open `.todo/task_plan.md` and confirm the current unit.
2. **Read findings.** Skim `.todo/findings.md` for relevant past attempts or decisions.
3. **Gather context.** Read only the source context needed for that unit.
4. **Apply the change.** Smallest change that completes the unit.
5. **Verify.** Run the unit verification command. If it fails, log the error in `findings.md`, mark the unit blocked in `task_plan.md`, and stop (error mode).
6. **Log progress.** Append to `.todo/progress.md` with action, verification output, and new state.
7. **Update the plan.** Mark the unit `[x]` in `task_plan.md`.
8. **Save findings.** If 2+ operations produced new information, append to `findings.md`.
9. **Stop or continue.** Stop if the stop rule is reached; otherwise continue only if the agreed loop permits.

> **Gate:** Update `.todo/task_plan.md` after each completed, skipped, or
> blocked unit. Do not rely on chat memory. The external file is the only
> source of truth for progress.

### Cross-slice verification

When the plan identifies a contract spanning units, check that it assigns an
integration check. Run the check at its assigned boundary after its contributors
are joined, and record the actual output. Contributor units may pass their own
checks, but the cross-slice contract is not verified until its integration check
passes. If the check is missing, cannot run, or fails, stop and report the
contract as unverified. Block its unfinished unit; if no such unit exists, seek
a plan amendment rather than altering a completed unit. Do not substitute
individual unit checks. An explicit deferral remains unverified, not passed.
Work without such a contract needs no extra integration step.

### Verification Commands

Prefer objective, repeatable commands:

- File exists: `test -f path && wc -l path`
- Content exists: `grep -n "anchor-or-label" path`
- Count remaining items: `grep -c "^- \[ \]" .todo/task_plan.md`
- Git state: `git status --short`
- Tests/build: project-specific test command

---

## Stop Rules

Choose one stop rule before execution starts:

- **Default cautious mode:** process exactly 1 unit, verify, update tracker, then stop.
- **Batch mode:** process at most N units, then stop and report.
- **Time-box mode:** work until the time limit, but finish the current unit before stopping if safe.
- **Error mode:** stop immediately when a unit is blocked, ambiguous, or verification fails. Do not skip to the next unit — the plan may need revision.

If the user says "one by one" or "you do not have free reign", use default
cautious mode unless they explicitly authorize a batch size. If context is
running low, stop after updating the tracker with the next unit and current
state.

---

## Plan Cleanup

Every plan's final work unit (step 4 in the template) is to archive and remove
`.todo/`. A plan is not complete until `.todo/` is gone.

When all work units (except step 4) are checked:

1. Verify: all units `[x]`, no blocked units without documented reasons.
2. Archive (preferred):
   ```bash
   tar czf ".todo-$(date +%Y%m%d-%H%M%S).tar.gz" .todo/ && rm -rf .todo/
   ```
3. Or delete (if the user prefers no archive):
   ```bash
   rm -rf .todo/
   ```
4. Verify cleanup:
   ```bash
   test ! -d .todo && echo "✓ Plan complete — .todo/ cleaned up"
   ```

The archive stays in the project root as a local record — it is not committed.
If the user explicitly asks to keep `.todo/` for reference, skip cleanup but
note it as a deviation in the final report. If aborting a plan (with user
consent), archive first — do not silently delete findings.

---

## Reporting Format

After each bounded run:

```markdown
## Progress update

Completed:
- ...

Verification:
```text
[command]
[relevant output]
```

Plan:
- `.todo/task_plan.md`
- Remaining unchecked units: N

Next unit:
- ...

Blocked / uncertain:
- ... or "none"
```

### Completion Criteria

Do not claim the overall task is complete until:

- [ ] All work units in `task_plan.md` are checked (including step 4 — archive)
- [ ] Final verification has been run
- [ ] `.todo/` directory no longer exists (or the user explicitly opted to keep it)
- [ ] The archive file exists in the project root (if archiving was chosen)

---

## Cross-Round Continuity

This skill cannot automatically re-inject the plan into every new round — that
requires platform-level hooks. Instead:

- **Within a session:** The execution loop (step 1: read the plan) ensures the
  plan is re-read every iteration.
- **Across rounds:** Use `mini_mem__add` to store a reference to the active
  `.todo/` plan. The next round's context will include the working memory slot.
- **Manual resume:** If the LLM has no context of the plan, the user can say
  "continue the plan in .todo/" and the skill's single-plan enforcement will
  pick it up.

The `.todo/` directory on disk is the durable source of truth. Any round can
resume it by reading the three files.
