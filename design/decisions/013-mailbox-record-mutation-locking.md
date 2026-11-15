# 013 — Mailbox record mutation is serialized by a per-request exclusive lock

**Status:** accepted (amended 2026-11-13)

## Context

MR !44 review round 2 (work item #41) found a Blocker: every mailbox command
performed an unlocked read-modify-write of the whole record, and concurrent
CLI invocations — the normal case, since #41's acceptance model has a second
client submitting replies and pause/cancel/rebind "settable by any client" —
silently overwrote each other's writes. Executed probes lost an acknowledged
reply in 12/30 trials and double-delivered in 15/30. Sequential tests never
saw it.

## Decision

Each command that mutates a request record runs its read-modify-write inside
a **per-request exclusive lock**:

- Lock acquisition: `open("<id>.lock", "wx")` (exclusive create), retried
  with backoff; a lock older than a staleness bound (10s — operations are
  ms-scale; a longer-lived holder means a crashed process) is stolen; a
  wait timeout fails with a rejected-class "busy" error (exit 3).
- The lock is released in `finally` — including when the body exits via a
  thrown command failure (an exit never skips release).
- Record state is re-read **under** the lock: guards (live-expectation,
  cancelled, identity) always see the committed state, never a stale copy.
- Enumeration and read-only commands (`list`, `show`) take no lock.
- `consume` with no settled reply performs **no write**: persistence of
  no-op attempts was itself the overwrite hazard.
- Concurrency claims are verified only by tests that spawn real concurrent
  processes; sequential invocations cannot exercise the interleavings.

Rejected: compare-and-swap on a record version field — same guarantee, but
every command body must then retry on conflict; the lock centralizes the
serialization once.

## Consequences

- No acknowledged write can be erased by a concurrent command; concurrent
  registrations yield exactly one winner; the "last writer wins" reply-loss
  failure class (#40's motivation) is closed.
- The delivered mark is still set *after* the requester acknowledgment (see
  decision 012's ordering discussion and R2.F3): on a crash in that window
  delivery is at-least-once (re-delivery), never lost.
- A crashed process can hold the lock for up to the staleness bound before
  another contender steals it; contention beyond the wait timeout is
  reported as a busy rejection rather than a silent overwrite.
- Applicability beyond the mailbox: any same-host file-store backing a
  multi-client CLI should treat per-key serialization + state-recheck-under-
  lock as the default, and verify it with real concurrent processes.
- Standing requirement (amendment from issue #50): any future store-level or
  locking change extends the real-concurrent-process coverage rather than
  regressing to sequential-only tests. Paths not yet covered under real
  concurrency — notably the lock wait-timeout ("busy") and stale-lock steal
  paths — must be brought under concurrent-process tests by the change that
  touches them; sequential tests never exercise the interleavings these
  guards exist for.
