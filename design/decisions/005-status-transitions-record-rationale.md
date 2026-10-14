# 005 — Status transitions record a rationale

**Status:** accepted

## Context

`verified`/`settled` transitions could be a bare flip, but then the store
loses why the trust level changed.

## Decision

Transitions record a rationale via `set-status --rationale`, carried into the
local store commit message.

## Consequences

Rationale is only as durable as the local store history; supersede carries
its own justification in the same way.

## Enforced by

invariant (`scripts/store.py` `set-status` + `scripts/test_store.py`)
