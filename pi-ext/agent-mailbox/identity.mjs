// Stable session identity bindings: pane name -> session identity.
// Persisted under the mailbox directory namespace so every extension
// instance (any pane on the same host/user) sees the same table.
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";

import { withStateLock } from "./extlock.mjs";

/**
 * Path of the identity bindings file inside the mailbox dir namespace.
 * Lives alongside (not inside) the mailbox store's request files so the
 * CLI never mistakes it for request state.
 */
export function bindingsPath(mailboxDir) {
  return join(mailboxDir, "ext", "session-identities.json");
}

/** Load the pane -> session-identity table. Missing file means empty table. */
export async function loadBindings(mailboxDir) {
  try {
    const raw = await readFile(bindingsPath(mailboxDir), "utf8");
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

/**
 * Bind a pane name to a session identity (stable string, e.g. pi session id).
 * Records the binding with a timestamp. Returns the stored binding.
 */
export async function bindPane({ mailboxDir, paneName, sessionId, now = new Date().toISOString() }) {
  if (!paneName || typeof paneName !== "string") throw new TypeError("paneName required");
  if (!sessionId || typeof sessionId !== "string") throw new TypeError("sessionId required");
  const file = bindingsPath(mailboxDir);
  // Read-modify-write is serialized under the ext-state lock (R1.F4):
  // state is re-read UNDER the lock, never from a stale pre-lock copy.
  return withStateLock(file, async () => {
    const bindings = await loadBindings(mailboxDir);
    bindings[paneName] = { sessionId, boundAt: now };
    await mkdir(dirname(file), { recursive: true });
    await writeFile(file, JSON.stringify(bindings, null, 2) + "\n");
    return bindings[paneName];
  });
}

/** Resolve a pane name to its session identity, or null when unbound. */
export async function resolvePane({ mailboxDir, paneName }) {
  const bindings = await loadBindings(mailboxDir);
  return bindings[paneName] ?? null;
}

/**
 * Best-effort pane name for this extension instance. Overridable for tests.
 * herdr sets AGENT_PANE per pane; absent that, the pane is anonymous and
 * identity binding is skipped (requester tools fail fast on unbound panes).
 */
export function resolvePaneName({ env = process.env } = {}) {
  return env.AGENT_PANE || null;
}
