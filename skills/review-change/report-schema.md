# Report file

The report file is the canonical record of a review and the only input `publish-review` accepts. It always holds the full report, whatever the chat profile.

## Location and lifecycle

- Path: `<system temp dir>/review-<label>-r<round>.md`, where `<label>` is the target slug used for the worktree (`pr144`, `mr37`, `bd-12`, `gh111`). Overwrite an earlier report for the same target and round.
- `publish-review` writes the operator's decisions into it, posts it, and deletes it after a successful post.
- A report file that survives means a review was never published. At the start of every review, list any `review-*.md` in the temp dir and report them; never delete them silently.

## Frontmatter

```yaml
---
schema: review-report/1
label: pr144
round: 2
target: pr:144              # pr:<n> | mr:<n> | issue:<n> | bd:<id>
work: gh:111                # optional: gh:<n> | gl:<n> | bd:<id> | <tracker>:<id>
forge: github               # github | gitlab | none
repo: vhallac/semblr        # owner/repo or GitLab project path; omit when forge is none
mode: change                # implementation | change | reconciliation
base: d53a4d4               # merge-base (full or abbreviated SHA)
head: 4437b56               # reviewed commit
last_head: 8effa87          # previous round's head; omit in round 1
verdict: approve-with-follow-ups
findings:
  - {id: F1, severity: Minor, likelihood: probable, summary: "render-time Kahn fallback drops providers silently"}
  - {id: F2, severity: Minor, likelihood: unlikely, summary: "required docstring overstates null semantics"}
unrelated:
  - {id: U1, summary: "providers Map is publicly mutable"}
prior:
  - {id: R1.F1, decision: fix, status: resolved}
  - {id: R1.F2, decision: fix, status: resolved}
waivers: []                  # operator waivers for unmapped claims (first review only)
decisions: {}               # filled in by publish-review
---
```

Verdict values are hyphenated (`approve-with-follow-ups`, `partially-satisfied`) so they can go straight into the round marker.

## Body

In this order, each a `##` heading:

1. **Header** — target(s), selected mode and why, commit range and merge-base, delta since last round, evidence inspected, material claims extracted for falsification, any ignored markers.
2. **Prior findings** — one line per earlier finding with its decision and current status (`rounds.md`). Omit in round 1.
3. **Findings** — `#### F<n> — <Severity>: <summary>` blocks with all eight fields (`method.md`, *Severity*), including the likelihood grade (`method.md`, *Likelihood*).
4. **Unrelated problems** — `#### U<n>: <summary>` blocks: anchor, concrete problem, evidence, likely consequence, suggested follow-up work item. Say so if none.
5. **Requirement traceability** — table: requirement or claim | evidence | status | gap/note. Statuses: supported, contradicted, partially supported, unverified, not applicable.
6. **Design-decision matrix** — table: decision | why relevant | result (complies / possible tension / violates / not applicable) | evidence.
7. **Verification assessment** — evidence per conclusion, checks run or inspected, counterexamples attempted, paths examined, claims still unverified, limitations of the review.
8. **Verdict** — the verdict and the finding IDs that determined it (`method.md`, *Verdict*).

Frontmatter and body must agree: every finding in the body appears in `findings` with the same ID, severity, likelihood and summary, and vice versa. `publish-review` refuses a report where they disagree.

## Claim coverage and waivers

First review only (`method.md`, *Claim-test presence check*):

- Every unmapped claim is a finding of the finding class **insufficient testing**: a normal `#### F<n>` block whose summary lists the unmapped `claim-id[/enumeration-id]`, mirrored in the frontmatter `findings` list.
- Operator waivers for unmapped claims are recorded in the frontmatter `waivers` list:

  ```yaml
  waivers:
    - {claim: C3/E2, by: operator, source: chat}
  ```

  and echoed in the **Verdict** body section together with the finding IDs they unblocked. The waiver lives in the review output only; updating the claim record to `coverage: review-only` is a separate, operator-directed step (see `method.md`, *Waiver procedure*).
- In the **Requirement traceability** table, a waived claim's status is `unverified`, with `waived; coverage: review-only` in the gap/note column.

## Chat profiles

The profile changes only what is shown in chat. Default **compact**:

1. Header — target, mode, range, round, verdict.
2. Findings table — `ID | Severity | Likelihood | Anchor | Problem | Recommended correction`.
3. Full blocks for every Blocking and Important finding.
4. Prior findings — only those not resolved.
5. Unrelated problems — one line each: ID, anchor, problem, suggested work item.
6. What was checked — brief falsification summary; name unverified claims.

Traceability, decision matrix and full verification assessment are skipped in compact unless a claim is contradicted or unverified; then include those rows.

**full** shows the whole report.

End the chat report with `Full detail: <path>`.
