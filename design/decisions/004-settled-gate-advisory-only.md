# 004 — `settled` mutation gate is advisory-only in v1

**Status:** accepted

## Context

The design question: does `settled` actually gate mutations (re-parenting,
superseding), or is it advisory-only in v1?

## Decision

Advisory-only: the operator is asked for explicit confirmation before a
settled mutation; `store.py` never refuses. Tests assert the mutation is
allowed on settled cards.

## Consequences

Store code stays simpler; enforcement (if ever wanted) can be added later
without a schema change. Trust in `settled` cards depends on operator
discipline, not the tool.

## Enforced by

invariant (`scripts/test_store.py` — settled mutations succeed)
