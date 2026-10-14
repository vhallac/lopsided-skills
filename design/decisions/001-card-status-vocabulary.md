# 001 — Card status vocabulary

**Status:** accepted

## Context

Cards had no per-card maturity signal: supersession was purely via typed
links, deletion was delete-or-promote, and readers could not tell how much to
trust a card. A vocabulary had to be designed once, with obsolescence and
supersession semantics in view, to avoid a later migration.

## Decision

Five status values, defaulting to `draft`:

| Status | Meaning | Discovery |
|---|---|---|
| `draft` | Captured but not verified. Default. | Normal |
| `verified` | Claims checked against sources/evidence. | Normal |
| `settled` | Stable and relied upon; content decided. | Normal |
| `obsolete` | No longer to be built upon; stays addressable. | Excluded from discovery; resolvable by ID/link |
| `superseded` | Replaced by a successor; readers follow the redirect. | Excluded from discovery; resolution surfaces successor |

`draft → verified → settled` is the trust ladder. `obsolete` keeps links
non-dangling while dropping the card from normal discovery. A true delete
becomes rare and manual. Migration is none: absence of status means `draft`.

## Consequences

Discovery (title index, link-search) must deterministically skip
`obsolete`/`superseded`; ID-based resolution still works. Future card
features must account for five default states rather than a boolean
delete/promote.

## Enforced by

invariant (`scripts/store.py` index parsing + `scripts/test_store.py`)
