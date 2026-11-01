# Rendering a review

Markdown, the same on every channel. The channel files say only how it is posted.

## Layout

```markdown
**Review round 2** — !144 (work item #111) — change review — `d53a4d4..4437b56` (since round 1: `8effa87..4437b56`)
Reviewer verdict: **approve with follow-ups**

### Findings

| ID | Severity | Summary | Decision |
| --- | --- | --- | --- |
| R2.F1 | Minor | Render-time Kahn fallback drops providers silently | fix |
| R2.F2 | Minor | `required` docstring overstates null semantics | accept |

### Operator decisions

- **To fix in this change:** R2.F1
- **Accepted:** R2.F2 — null-render semantics are intended; docstring tightened separately in #150
- **Deferred:** none
- Amendment notes: none

### Prior rounds

- R1.F1 (fix) — resolved
- R1.F2 (fix) — resolved

### Details

#### F1 — Minor: Render-time Kahn fallback drops providers silently
…all eight fields, verbatim from the report…

<details><summary>F2 — Minor: …</summary>

…verbatim…

</details>

### Unrelated problems

| ID | Anchor | Problem | Decision |
| --- | --- | --- | --- |
| R2.U1 | `lib/provider-contract.ts` `ProviderRegistry.providers` | publicly mutable Map | file: to be filed |

<!-- review-round: round=2 target=pr:144 work=gh:111 base=d53a4d4 head=4437b56 verdict=approve-with-follow-ups -->
<!-- review-decisions: round=2 F1=fix F2=accept U1=file -->

🤖 Content created by LLM
```

## Rules

- **Result line** — round, target (and work item), mode, range, and the delta since the last round when there is one. Then the reviewer's verdict on its own line, labelled as the reviewer's.
- **Findings table** — every finding, ID order, IDs qualified with the round (`R2.F1`).
- **Operator decisions** — what the author must do, grouped by decision. If no finding is `fix`, write exactly: "No changes required in this change." This section, not the verdict, defines what the author changes.
- **Prior rounds** — from the report's Prior findings; omit in round 1.
- **Details** — the reviewer's blocks verbatim. Blocking and Important in full; Minor and Observation inside `<details>`. Inside a block, finding IDs stay unqualified (`F1`) as the reviewer wrote them.
- **Unrelated problems** — omit the section if there are none.
- **Markers** — `rounds.py marker round` and `rounds.py marker decisions`, pasted unmodified, after all visible content and before the footer.
- **Never** use the heading "Changes required", and never label findings "required".
- Last line: `🤖 Content created by LLM`.
