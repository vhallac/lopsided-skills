---
name: publish-review
description: Publish a review-change report to its channel — PR/MR comment, forge issue comment, or beads work-item notes — with the operator's decision (fix / accept / defer, file / decline) on every finding and unrelated problem, and the round markers later reviews read. Use when asked to publish, post, or record a review, or to record a changed decision on an already-published review. Never reviews code itself.
---

# Publish Review

Publish a review with operator decisions, given as `[F1=fix F2=accept:"reason" F3=defer[:#n] U1=file[:#n] U2=decline:"reason" rest=<decision>] [--to <channel>]`.

This skill publishes a review produced by the review-change skill. It does not review code and does not modify code, work items, or git state. Its only write is the approved publication.

## Files in this skill

| File | Read when |
| --- | --- |
| `channels/forge-comment.md` | publishing to a GitHub PR/issue or a GitLab MR/issue |
| `channels/beads-notes.md` | publishing to a beads work item |
| `rendering.md` | composing the publication (all channels) |

Markers are rendered by the review-change skill's `scripts/rounds.py` (`marker round`, `marker decisions`). Never write them by hand: the next review parses them.

## Source

The report file written by review-change (`<temp dir>/review-<label>-r<round>.md`, schema in review-change's `report-schema.md`). It is the only source. If it is missing, report an error and stop — never reconstruct findings from chat or memory; a rebuilt review drifts silently from what was found.

Check before anything else:

- frontmatter `schema: review-report/1`;
- every `F<n>`/`U<n>` block in the body appears in the frontmatter with the same ID, severity, likelihood and summary, and vice versa;
- every finding block has all seven fields.

If any check fails, report what is wrong and stop.

## Channel

From `--to`, else from the report's `target`:

| Target | Channel |
| --- | --- |
| `pr:<n>` / `mr:<n>` | that PR/MR — `channels/forge-comment.md` |
| `issue:<n>` | that forge issue — `channels/forge-comment.md` |
| `bd:<id>` | that work item's notes — `channels/beads-notes.md` |

If the channel cannot be determined, report an error and stop.

## Decisions

The reviewer's findings are published **verbatim**. The operator's view goes in **Operator decisions**, never into the finding text: no rewording, re-grading or merging findings.

Every finding needs exactly one decision:

| Decision | Meaning |
| --- | --- |
| `fix` | The author addresses it in this change. |
| `accept:"<reason>"` | Not changed; the reason is recorded. |
| `defer[:#n]` | Not in this change; tracked in `#n`, or "to be filed". |

Every unrelated problem needs one:

| Decision | Meaning |
| --- | --- |
| `file[:#n]` | Approved for a new work item (`#n` once filed). |
| `decline:"<reason>"` | Not filed; the reason is recorded. |

`rest=<decision>` applies to every finding not named explicitly (`F1=fix rest=accept:"minor, not worth churn"`). It never covers unrelated problems; name those.

If any ID is left without a decision, list the undecided IDs and ask. Never infer a decision from severity.

**Corrections to a finding** (a factual error in its evidence, say) are amendment notes under that finding's decision, never edits to the finding.

**Issues are not created here.** `defer` and `file` without a number publish as "to be filed"; creating the work item is a separate, separately approved step. Once it exists, record the number with a decision update (below).

## Flow

1. Validate the report (*Source*). Determine the channel.
2. Collect decisions; ask about any missing.
3. Write the decisions (with reasons and amendment notes) into the report's frontmatter `decisions` and under each finding block.
4. Compose the publication per `rendering.md` and the channel file, with both markers from `rounds.py`.
5. Show the draft and **wait for the operator's approval** — the operator curates the permanent record.
6. Publish via the channel file.
7. Confirm it landed: re-read the channel and run `rounds.py fetch` on it; this round's markers must come back with the decisions just posted.
8. On confirmed success, delete the report file. On any failure, leave it untouched, report the error with the draft, and do not retry blindly.
9. Report where it was published (URL or work-item ID) and the report file's fate.

## Decision updates

A decision changed after publishing — reversed after discussion, or an issue number assigned — is recorded as a **new, short publication** on the same channel, never by editing the original:

- one line per changed ID: `R2.F1: accept → fix — <reason>` or `R2.U1: file → file:#146`;
- a `review-decisions` marker for that round carrying only the changed IDs (`rounds.py marker decisions --round 2 F1=fix`).

The same approval step applies. No report file is needed.
