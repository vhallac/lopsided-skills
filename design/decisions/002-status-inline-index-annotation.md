# 002 — Status lives inline as an index annotation

**Status:** accepted

## Context

A status change mutates a card, so it must ride the same validate/commit
machinery as every other store change. The design choice was between an
inline card-line field and tolerated card metadata.

## Decision

Status lives inline on the index line as an annotation —
`[draft|verified|settled|obsolete]` or `[superseded → <id>]`; absence means
`draft`. Card bodies stay untouched.

## Consequences

Index parsing carries status (and successor id) per entry; the annotated
form is matched first, and lines that do not end in a recognized annotation
fall back to the pre-status `ID — Title` format with the full remainder as
title. Consequence: a title that genuinely ends with a valid annotation
form (e.g. `Costs [settled]`) is inherently ambiguous and is parsed as an
annotation — titles ending that way must be avoided. Any other bracketed
title text (e.g. `Costs [USD]`) stays valid, preserving the no-migration
constraint. No separate metadata store to keep coherent.

## Enforced by

invariant (`scripts/store.py` `INDEX_RE` + `parse_index` + `scripts/test_store.py`)
