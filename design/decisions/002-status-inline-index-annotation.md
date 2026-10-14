# 002 — Status lives inline as an index annotation

**Status:** accepted

## Context

A status change mutates a card, so it must ride the same validate/commit
machinery as every other store change. The design choice was between an
inline card-line field and tolerated card metadata.

## Decision

Status lives inline on the index line as an annotation —
`[draft|verified|settled|obsolete]` or `[superseded -> <id>]`; absence means
`draft`. Card bodies stay untouched.

## Consequences

Index parsing carries status (and successor id) per entry; title regex
forbids a trailing `]` so malformed annotations fail as parse errors. No
separate metadata store to keep coherent.

## Enforced by

invariant (`scripts/store.py` `INDEX_RE` + `parse_index` + `scripts/test_store.py`)
