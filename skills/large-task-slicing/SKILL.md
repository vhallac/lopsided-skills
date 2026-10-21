---
name: large-task-slicing
description: Break large or long-horizon tasks into externally tracked, bite-sized work units with verification gates. Use when a task spans many files/items, has more than four meaningful steps, may exceed context, or the user asks to work one-by-one, maintain a TODO, avoid free-reign execution, or amend a live plan.
---

# Large Task Slicing

Use this skill when a task is too large to trust to conversational memory alone.
The goal is to turn a long-horizon task into a small, externally tracked loop:
define state, do one unit, verify, update state, stop or continue only under
the agreed bounds.

All plan state lives in `.todo/` at the project root. Three plan files, one
plan, no exceptions, plus a non-hidden guard file. `task_plan.md` is strictly
owned by a script (`plan.py`); `findings.md` and `progress.md` are free-form
notes.

## Working root

Everything is root-relative (`plan.py init <root>`). The root is the plan's
workspace from birth: under plan-work's step 1.5 this is a worktree created
via the worktree-management skill, and all paths, gates, and archives resolve
inside it. In a linked worktree, `.git` is a file pointing at the common
gitdir — `plan.py` handles this (excludes are written to the common gitdir).

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

## Plan Files

### `task_plan.md` — The Plan (script-owned, strict)

The plan is the only strict file. It is written and mutated **only through
`plan.py`** — never by hand. It holds a guard frontmatter block followed by
three fixed sections:

```markdown
---
guard: |
  STOP — READ BEFORE TOUCHING ANYTHING
  This plan is managed by the **large-task-slicing** skill. ...
---
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
- [ ] unit-001 — short label
  - input: <named files/notes the unit starts from>
  - scope: <the change; the scope lock's must-not-change applies>
  - output: <what exists after>
  - verify: <one command>
```

Goal memory and Bounds are set once at plan creation and do not change. Each
work unit is a **contract** — `input` / `scope` / `output` / `verify` — so a
fresh session can execute it without re-deriving context. A unit bound to a
plan-work **flow** (see plan-work's "Extra information") reads that flow as
part of its inputs; the plan's **assumptions** are held as
entitlement-without-re-verification — if execution contradicts one, record a
finding and amend through the normal amendment path, never a silent workaround.
The `verify` field is
the unit's verification command.

Unit state lives in the checkbox, derived from the unit's **event trail** —
appended `added` / `done` / `blocked` / `cancelled` sub-lines carrying a
timestamp and, for `done`, the verbatim evidence. A unit's text is never
rewritten once written; changing intent is only ever `cancel` + `add-unit`
(see Plan Amendments). This is the provenance trail: it records what was
intended, what happened, and why it changed.

Checkbox states:

| Marker | State | Meaning |
|--------|-------|---------|
| `[ ]` | open | pending |
| `[x]` | done | verified with evidence |
| `[!]` | blocked | a failure is classified and logged |
| `[-]` | cancelled | abandoned with a reason, text preserved |

### `findings.md` — Research & Decisions (free-form)

Every non-obvious discovery, design decision, dead end, or error goes here.
This is the institutional memory of the task — what you learned and why you
chose each path. Append only; do not rewrite history. Hand-edit freely.

```markdown
# Findings: [Task name]

## YYYY-MM-DD
- **Tried:** ... → **Result:** ...
- **Decision:** ... because ...
- **Error:** ... (do not retry without a different approach)
```

Log every error or dead end with enough detail that a future attempt won't
repeat it. After every 2 operations that produce new information, save findings.

### `progress.md` — Session Log (free-form)

A per-turn log of what was done. One entry per execution loop iteration.
Hand-edit freely. Include the verification command output verbatim here — this
is where the full multi-line output lives when the plan's `done` event carries
only the anchor evidence.

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

Update after every unit — do not batch multiple units into one entry.

### `READ-ME-FIRST-use-skill-large-task-slicing.md` — Guard (script-owned)

A non-hidden tripwire file, mirroring the zettelkasten store's guard. Its
imperative name appears in every `.todo/` listing and its body instructs a
reader to load this skill and never hand-edit `task_plan.md`. `plan.py init`
creates it, every mutating `plan.py` command recreates it if it is deleted or
altered, and the same note also rides at the top of `task_plan.md` as YAML
frontmatter (`guard: |`) so an agent that reads only the plan still sees it.
Treat it as immutable — never edit or delete it yourself.

---

## The `plan.py` Tool

The LLM decides a unit's label, contract, and when to verify it. `plan.py` owns
every mechanical mutation: unit IDs, placement, checkbox state, the event trail,
and validation. There is deliberately **no edit/rewrite/reorder command** — so
"no modify" is not a rule you must remember, it is a property of the tool
surface.

**Using `plan.py` is non-negotiable.** Do not hand-edit `task_plan.md`. If
`plan.py` cannot be found or run, HALT the plan work and report the problem to
the user instead of hand-editing. `findings.md` and `progress.md` are the
exceptions — they stay free-form and hand-edited.

Every mutating command verifies the plan against a tamper ticket
(`.todo/.plan-state`) before writing, then refreshes the ticket. Hand edits to
`task_plan.md` are therefore detected and refused. The script lives at
`<skill-directory>/scripts/plan.py` — never guess a fixed absolute path.

Commands:

| Command | Semantics |
|---|---|
| `init <root> --name <t> --goal\|--goal-file <g> --bounds\|--bounds-file <b>` | Create `.todo/`, the plan skeleton (guard frontmatter / Goal memory / Bounds / empty Work units), the guard file, `findings.md`, `progress.md`, and the ticket. Refuses if a plan already exists. Any `--*-file` flag accepts `-` to read its text from stdin; the inline form treats `-` as literal text. |
| `add-unit <root> --label --input --scope --output --verify [--after <id\|frontier>]` | Add a contract unit. New ID (`unit-NNN`, never reused/renumbered), placed at the tail by default, or after `<id>`, or after `frontier` (first open unit). |
| `complete <root> <unit> --evidence "<verbatim output>"` | Mark done **and** record the evidence. Refuses without evidence and refuses terminal units. |
| `block <root> <unit> --kind <code\|test\|mechanical\|requirement> --reason <why>` | Mark blocked with a failure classification. |
| `cancel <root> <unit> --reason <why>` | Abandon an unfinished unit. Text preserved; reason appended. Refuses a done unit. |
| `status <root>` | The projection to read each loop: current unit + contract, and open/done/blocked/cancelled buckets. |
| `history <root>` | The provenance trail — every event with its timestamp. |
| `archive <root>` | Archive and remove `.todo/`. Refuses unless every unit is done or cancelled. |
| `validate <root>` | Check plan structure and report the ticket state. |
| `re-ticket <root>` | Repair: re-bless the current plan as the ticketed state. |

### Operation: Repair a refused command

If a command fails with "the plan file was modified outside plan.py", the plan
was hand-edited. Do not recreate `.plan-state` yourself:

1. Run `python3 <skill-directory>/scripts/plan.py validate <project-root>`.
2. If the hand edit should be discarded, undo it so the plan matches the last
   `plan.py` state (the event trail in `history` shows what the plan should
   read), then redo the intended change through `add-unit` / `complete` /
   `block` / `cancel`.
3. If the hand edit is correct and `validate` passes, run
   `plan.py re-ticket <project-root>` to re-bless it. **STOP and confirm with
   the user before re-ticketing** — re-ticket blesses whatever is there, so
   never use it to paper over a mess. `validate` refuses a plan whose guard
   frontmatter was stripped, so re-ticket cannot bless that removal.
4. Never delete or rewrite `.todo/.plan-state` by hand; the only writer is `plan.py`.

---

## Single Plan Enforcement

At most one plan exists at any time. The three plan files in `.todo/` are the
plan (the guard file rides alongside them).

When this skill activates:

1. Check if `.todo/task_plan.md` exists.
2. **Exists → resume.** Run `plan.py status <root>` and read `findings.md`.
   Report: "Resuming plan — N units remaining." Do not create a new plan.
3. **Does not exist → new plan.** Proceed to Required First Move.
4. **User wants to abandon the current plan →** archive it first (see Plan
   Cleanup), then create a new one.

> **Gate:** Do not create a second plan alongside an existing one. `plan.py init`
> refuses if `.todo/task_plan.md` already exists. Resume it or get explicit user
> consent to replace it (archive first).

---

## Key Rules

1. **Never repeat a failure.** If a unit fails, log the error in `findings.md` and mark the unit blocked (`plan.py block --kind ... --reason ...`). Do not retry the same approach. Change the approach or skip the unit with a reason.

2. **Diagnose before fixing.** Classify each failure as `code`, `test`, `mechanical`, or `requirement` (the `block --kind` taxonomy), then fix that source. Never weaken a test merely to pass; a changed expectation needs an anchor.

3. **Log all errors.** Every unexpected result, failed verification, or tool error goes into `findings.md` immediately — before moving on.

4. **Save findings after every 2 operations.** "Operations" means tool calls that produce new information (reads, searches, test runs, builds). Prevents losing research context if the session ends unexpectedly.

5. **Verification is external, and evidence is mandatory.** A unit is not done until a shell command confirms it and the output is recorded (`plan.py complete --evidence`). `complete` refuses without evidence. When verification is inspection-only, still pass `--evidence`, labelled honestly as a weak check — never dress up inspection as command evidence.

6. **The tracker is the source of truth.** `plan.py status` reports what is done and what is current — regardless of what chat memory claims. If a unit is unchecked, it is not done.

7. **Never hand-edit `task_plan.md`.** All plan changes go through `plan.py`. This is what makes "no modify" and provenance mechanical rather than a discipline rule.

---

## Required First Move (New Plan)

Before creating a plan for a newly activated task:

1. Restate the original goal in 2-4 bullets (→ Goal memory).
2. Define the smallest useful work unit and its contract (input / scope / output / verify).
3. Define verification for one unit.
4. State the stop rule (→ Bounds).
5. If the user has not already consented to this decomposition, ask for approval before creating the plan.

Output:

```markdown
## Large-task slicing plan

Goal memory:
- ...

Work unit:
- ... (input / scope / output / verify)

Verification per unit:
- ...

Stop rule:
- ...

The plan will be created with `plan.py` (3 files: task_plan.md, findings.md, progress.md).
```

> **Gate:** Do not run `plan.py init` until the work unit, verification, and
> stop rule are explicit AND the user has consented (or already consented to
> the decomposition).

After consent, build the plan through the script — never by hand:

```sh
python3 <skill-directory>/scripts/plan.py init <project-root> \
  --name "<task>" --goal-file <goal.md> --bounds-file <bounds.md>

Any `--*-file` flag (goal and bounds) accepts `-` to
read its text from stdin (e.g. piped text); the inline form treats `-` as
literal text.

python3 <skill-directory>/scripts/plan.py add-unit <project-root> \
  --label "<label>" --input "<input>" --scope "<scope>" \
  --output "<output>" --verify "<verify>"
```

Repeat `add-unit` for each planned unit (they append at the tail in order).

---

## Work Unit Selection

Pick the smallest unit that produces meaningful, verifiable progress.

- **Corpus review:** one document section, one record, one report error group, or one category instance.
- **Code repair:** one failing test, one diagnostic, one compiler error cluster, or one file-local bug.
- **Documentation:** one heading, one use case, one endpoint, one diagram, or one page section.
- **Git cleanup:** one logical changeset, not the whole repository.

If a candidate unit cannot be verified independently, split it smaller or
define a better verification command before proceeding. Each unit's `verify`
must be a single command.

---

## Execution Loop

For every unit:

1. **Read the plan.** Run `plan.py status <root>` and confirm the current unit and its contract. Skim `findings.md` for relevant past attempts or decisions.
2. **Gather context.** Read only the source context needed for that unit.
3. **Apply the change.** Smallest change that completes the unit.
4. **Verify and record.** Run the unit's `verify` command.
   - Pass → `plan.py complete <root> <unit> --evidence "<verbatim output>"` (marks done and records evidence).
   - Fail → log the error in `findings.md`, `plan.py block <root> <unit> --kind <code|test|mechanical|requirement> --reason "<why>"`, and stop (error mode).
5. **Log progress.** Append to `progress.md` with action, verification output, and new state.
6. **Save findings.** If 2+ operations produced new information, append to `findings.md`.
7. **Amend if needed.** If new knowledge invalidates upcoming work, amend the plan (see Plan Amendments) at this unit boundary.
8. **Stop or continue.** Stop if the stop rule is reached; otherwise continue only if the agreed loop permits.

> **Gate:** Update the plan through `plan.py` after each completed, skipped, or
> blocked unit. Do not rely on chat memory. The plan file is the only source of
> truth for progress.

### Verification Commands

Prefer objective, repeatable commands (they become the unit's `verify`):

- File exists: `test -f path && wc -l path`
- Content exists: `grep -n "anchor-or-label" path`
- Count remaining items: `plan.py status <root> | grep "Remaining open"`
- Git state: `git status --short`
- Gates: if the project has a `gates.yaml` manifest (written by the
  commit-gate-wiring skill), take unit, commit, extra gates, and the
  diff-coverage floor (when present) from it verbatim — do not re-derive or
  guess project-specific checks
- Anchor checks: invariant script, golden diff, canary run (project-specific
  when no manifest declares them)
- Tests/build: project-specific test command

---

## Plan Amendments

Plans rarely survive intact. When new knowledge gathered mid-run invalidates
upcoming work, amend the plan — do **not** rewrite it. There is no `modify`
command on purpose: provenance is preserved by only ever appending.

An amendment is **one `cancel` + one `add-unit`**:

1. **Cancel** the now-wrong unit:
   `plan.py cancel <root> <unit> --reason "<why it died>"` — the original text
   stays visible forever with the reason appended.
2. **Add** the replacement right after the current step:
   `plan.py add-unit <root> --label ... --after frontier` — a fresh ID placed
   at the frontier, never renumbering existing units.

The trail then reads: here is what was intended, here is why it died, here is
what replaced it. Position and identity are independent — a new unit gets a new
ID but takes the execution slot you choose with `--after`.

**Amend autonomously, report at the boundary.** Make the amendment at a unit
boundary and continue; surface it in the next report ("Amended: cancelled
unit-005 because ..., added unit-009 after unit-004") so the user can accept or
further revise. Under the cautious stop rule (or the error stop rule), the
amendment ends the round with a report instead of continuing.

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

The final step of every plan is `plan.py archive <root>`. It refuses unless
every unit is done or cancelled — so completion is enforced mechanically, not
by remembering to clean up.

```sh
python3 <skill-directory>/scripts/plan.py archive <project-root>
```

It writes `.todo-<timestamp>.tar.gz` to the project root and removes `.todo/`.
The archive stays as a local record — it is not committed. If the user
explicitly asks to keep `.todo/` for reference, skip `archive` and note it as a
deviation in the final report. If aborting a plan (with user consent), archive
first — do not silently delete findings.

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

Amended: (since the last report)
- cancelled unit-NNN — ... → added unit-MMM after unit-PPP — ...
  or "none"

Plan:
- Remaining open: N

Next unit:
- ... (unit id, label, verify)

Blocked / uncertain:
- ... or "none"
```

### Completion Criteria

Do not claim the overall task is complete until:

- [ ] Every unit in the plan is done or cancelled (no open or blocked units)
- [ ] `plan.py archive <root>` has run (`.todo/` is gone)
- [ ] The archive file exists in the project root
- [ ] Any estimate-vs-actual deviation is noted in `findings.md`

---

## Cross-Round Continuity

This skill cannot automatically re-inject the plan into every new round — that
requires platform-level hooks. Instead:

- **Within a session:** The execution loop (step 1: `plan.py status`) ensures the
  plan state is re-read every iteration.
- **Across rounds:** Use `mini_mem__add` to store a reference to the active
  `.todo/` plan. The next round's context will include the working memory slot.
- **Manual resume:** If the LLM has no context of the plan, the user can say
  "continue the plan in .todo/" and the skill's single-plan enforcement will
  pick it up via `plan.py status`.

The `.todo/` directory on disk is the durable source of truth. Any round can
resume it with `plan.py status <root>` plus reading `findings.md`.
