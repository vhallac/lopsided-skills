# Design note — card status values

Status: implemented (PR #2, issue #1). Standing decisions extracted to
`design/decisions/` (001–005). Covers roadmap items #4 (obsolete state),
#6 (note states), and #7 (superseding).

## Problem

Cards currently have no per-card maturity signal. Supersession is purely via
typed links, deletion is delete-or-promote, and readers have no way to tell how
much to trust a card. A status vocabulary must be designed once, with the
obsolescence and supersession semantics in view, to avoid a later migration.

## Proposed vocabulary

Five values, defaulting to `draft`:

| Status | Meaning | Discovery | Mutation gates |
|---|---|---|---|
| `draft` | Captured but not verified. Default for every new card. | Normal | None |
| `verified` | Claims checked against sources/evidence. | Normal | None |
| `settled` | Stable and relied upon; content is considered decided. | Normal | Re-parent/supersede require explicit operator action |
| `obsolete` | No longer to be built upon; children and inbound links stay in place. | Excluded from discovery, resolvable by ID/link | None |
| `superseded` | Replaced by a successor card; readers should follow the redirect. | Excluded from discovery; resolving surfaces the successor | None |

`draft → verified → settled` is a trust ladder (roadmap #6). `obsolete`
implements roadmap #4: the card stays addressable so links don't dangle, but
drops out of normal discovery. `superseded` builds on `obsolete` (roadmap #7):
the old card is kept addressable, and inbound references are re-pointed (or
redirected at resolution time) to the successor. A true delete becomes rare
and manual.

## Integration points

- **Card immutability vs. status changes.** A status change mutates a card, so
  it must ride the same validate/commit machinery as every other store change
  (`scripts/store.py`). Decide whether status is a card-line field or tolerated
  card metadata.
- **Discovery.** Title index and link-search must skip `obsolete`/`superseded`
  cards by default, while ID-based resolution still works. `superseded`
  resolution should surface the successor card.
- **Index coherence.** The complete title index stays in context; excluding
  statuses must be deterministic so incremental edits don't drift.
- **Migration.** None: absence of status means `draft`.

## Open questions — Resolved

1. `settled` is advisory-only in v1 (D5): the operator is asked for explicit
   confirmation before a settled mutation; `store.py` never refuses.
2. Status lives inline as an index-line annotation
   (`[draft|verified|settled|obsolete]` or `[superseded → <id>]`); absence
   means `draft`. Card bodies stay untouched.
3. `superseded` redirects at resolution time: inbound links are never
   rewritten (D2); the `[superseded → <id>]` annotation resolves to the
   successor when the old card is addressed.
4. Transitions record a rationale (via `set-status --rationale`), which is
   carried into the local store commit message (D3).
