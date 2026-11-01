# 016 — The agent-mailbox pi extension shells out to the mailbox CLI and keeps its own state namespaced away from the store

**Status:** proposed

## Context

Issue #42 turned the mailbox CLI (#41) into pi tools. Two structural choices
had to be made during execution: how the extension reaches the CLI, and where
extension-only state (the pane → session identity bindings) lives.

## Decision

- **Subprocess, not reimplementation.** Every tool (`agent_request`,
  `agent_wait`, `agent_reply`, `agent_rebind`, `agent_list`, `agent_pause`,
  `agent_resume`, `agent_cancel`) shells out to `mailbox` (decision 011's
  bin) and maps its exit vocabulary (0/2/3/4) onto tool errors. The mailbox
  CLI surface is consumed, not changed — one implementation of the store
  semantics, no drift.
- **Identity bindings live at `<MAILBOX_DIR>/ext/session-identities.json`.**
  The namespace subdirectory keeps extension state out of the store root, so
  the CLI never sees it as request state. Pane name source is `AGENT_PANE`;
  a pane without it is anonymous and cannot dispatch or reply (fail-fast).
- **Blocking waits are extension-internal.** `agent_wait` is a bounded
  subprocess poll loop on `mailbox show` (read-only) — never an LLM round —
  and consumes via `mailbox consume`, inheriting exactly-once (decision 012
  error handling, 013 locking unchanged).
- **Failed dispatch self-cancels.** A dispatch failure after a successful
  register triggers `mailbox cancel` (decision 014: cancel is terminal) so no
  half-dispatched register survives.

## Consequences

- Decisions 011–014 hold unchanged; the extension adds no mailbox semantics
  of its own.
- Delivery timing (follow-up rounds attributed to the worker via custom
  messages, no mid-run steering) is extension behavior layered on top; the
  mailbox stays pull-only per decision 011.
- A future mailbox implementation in-process must keep the exit vocabulary
  and store layout, or this decision must be revisited.
