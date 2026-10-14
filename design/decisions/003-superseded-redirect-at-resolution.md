# 003 — Superseded cards redirect at resolution; inbound links never rewritten

**Status:** accepted

## Context

Superseding a card leaves inbound references pointing at the old card. The
alternatives were rewriting inbound links during the supersede operation, or
redirecting at resolution time.

## Decision

Redirect happens at resolution time: the `[superseded → <id>]` annotation
resolves to the successor when the old card is addressed. Inbound links are
never rewritten. Redirect-on-resolution is behavioral — index annotation plus
a SKILL.md reading rule — not a `store.py resolve/get` subcommand (that would
be scope creep for a sole-writer store). Double-supersede is rejected.

## Consequences

Readers must follow redirects via the SKILL.md rule; no inbound-link churn on
supersede. Supersede is one atomic commit (successor capture + annotation).

## Enforced by

invariant (`scripts/store.py` `supersede` + `scripts/test_store.py`)
