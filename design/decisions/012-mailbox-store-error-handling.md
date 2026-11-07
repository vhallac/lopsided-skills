# 012 — Mailbox CLI store error handling: fail-open discovery, rejected-class corruption

**Status:** accepted

## Context

MR !44 review round 1 (work item #41) surfaced two durable handling rules for
the mailbox CLI's on-disk store (one JSON file per request under
`$MAILBOX_DIR`): a single damaged file wedged `list` — the pending-discovery
mechanism #41 relies on — with an unhandled crash outside the documented exit
vocabulary; and error exits did not distinguish input errors from store-state
refusals.

## Decision

- **Enumeration fails open:** `list` skips unparseable store files with a
  stderr warning; the exit code stays within the documented 0/2/3/4
  vocabulary. Discovery over the store must degrade, never wedge or crash.
- **Addressed corruption is rejected-class:** `show`/`load` of a specifically
  addressed corrupt record is a clean rejection (exit 3), not a usage error
  (exit 2) — the caller addressed a real record; the store state is what
  failed. `StoreError` carries its exit code; usage errors (invalid id,
  missing flag value) remain exit 2.

## Consequences

- Pending discovery survives a damaged file; the operator is warned and can
  repair the file without the CLI blocking.
- Exit-code consumers (the #42 pi extension) can distinguish "my input was
  wrong" (2) from "the store refused/cannot serve" (3) from "no such record"
  (4).
- A corrupt record is deliberately *not* silently deleted; repair remains an
  operator action.
