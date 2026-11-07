# 011 — The mailbox service CLI is a Node.js CLI shipped via package.json bin in this repository

**Status:** accepted

## Context

Issue #41 (mailbox service, child of #40) needed a home for a CLI that
persists and correlates request-reply pairs between agent sessions on the
same host, same OS user. At plan time the runtime and packaging were
assumption A-1: Node.js, shipped via the existing `package.json` `bin` field,
since the repository is already a pi (Node) package and the future pi
extension (#42) will share it. The assumption proved load-bearing and was
confirmed by execution — units 001–004 of the #41 plan built the CLI on it
with no contradiction.

## Decision

The mailbox service is a **Node.js CLI** shipped through this repository's
`package.json` (`bin: mailbox` → `mailbox/mailbox.mjs`), one package together
with the future pi extension (#42). Rejected: a separate repository — only
warranted if the service were consumer-agnostic; #41's boundaries say it is
not (same host, same OS user, single-requester correlation).

## Consequences

- One versioning unit for CLI and future extension; wire expectations cannot
  drift between them.
- State lives on disk (`$MAILBOX_DIR` or `~/.local/share/mailbox`, one JSON
  file per request, atomic tmp+rename writes); no daemon, no network.
- Delivery is pull-based (`mailbox consume`); push notification is deferred
  to the #42 pi integration.
- If a non-Node runtime is ever required, this decision must be revisited
  (the store format is plain JSON files, so a port is mechanical).
