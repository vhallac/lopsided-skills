# 014 — Cancel is terminal for a mailbox request expectation

**Status:** accepted

## Context

MR !44 review round 3 (work item #41) found that `dispatch` on a cancelled
record flipped its state back to `dispatched` (an idempotent-retry shaped
command resurrecting a cancelled expectation), letting a reply bind and a
delivery occur past the operator's explicit cancel. A related finding showed
the supersede-on-re-registration path silently destroyed the cancelled
record's rejection history.

## Decision

- **Cancel is terminal.** No command may move a cancelled request record out
  of the cancelled state. `dispatch` on a cancelled record is an explicit
  no-op (clear message, exit 0) per the operator decision — not a rejection
  and never a state flip. Replies to cancelled records stay rejected
  (rejected-class exit 3, attempt inspectable) and delivery stays refused.
- **Supersede preserves history.** The only way a cancelled record leaves
  the live namespace is re-registration, and that path **archives** the
  record as `<id>.cancelled.<timestamp>.json` in the store dir rather than
  deleting it — its rejection history stays inspectable. Discovery
  (`list`) recognizes only exact `<id>.json` record names, so archives are
  never live expectations.

## Consequences

- A cancelled expectation can never deliver, bind an outcome, or be revived;
  the only path back to live is an explicit fresh `register`, which the
  operator's re-registration action signals deliberately.
- Audit trail of refused replies survives supersede; diagnostics for "a
  reply arrived after cancel" remain answerable after re-registration.
- Store directory accumulates one archived file per supersede cycle; these
  are inert (ignored by discovery, not addressable by `show`), and pruning
  them is an operator action, not automatic — deliberate, since automatic
  pruning would recreate the history-loss defect.
- Applicability beyond the mailbox: terminal states set by an explicit
  operator command should be non-transitions in every other command's state
  machine, and superseding a terminal record should archive, not delete.
