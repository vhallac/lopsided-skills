// Session replacement + explicit rebind (unit-007, EXT-4d / RC-4).
//
// When a pane's session ends and a NEW session reuses the same pane name,
// the pane binding is overwritten with the new session identity (base
// binding semantics). The old session's pending replies must NEVER reach
// the new session: delivery matches on the requester identity, which no
// longer resolves for the replacement (EXT-4d). The only path back is an
// explicit rebind (RC-4): the operator (or the replacement session itself)
// calls agent_rebind, which records the replacement at session_start and
// rebinds the pending requests' requester identity to the replacement
// session via `mailbox rebind` (decision 011: the CLI is the only
// integration boundary).
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";

import { runMailbox as defaultRunMailbox } from "./request.mjs";
import { withStateLock } from "./extlock.mjs";

/** Path of the session-replacement journal inside the mailbox dir namespace. */
export function replacementsPath(mailboxDir) {
  return join(mailboxDir, "ext", "session-replacements.json");
}

/** Load the replacement journal. Missing file means empty journal. */
export async function loadReplacements(mailboxDir) {
  try {
    const raw = await readFile(replacementsPath(mailboxDir), "utf8");
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

/**
 * Record that paneName's session was replaced: fromSessionId ended and
 * toSessionId now owns the pane name. Appends to the journal (latest last).
 * Recording is bookkeeping only — it does NOT rebind anything and does NOT
 * enable delivery of the old session's replies (EXT-4d: explicit rebind
 * required).
 */
export async function recordReplacement({
  mailboxDir,
  paneName,
  fromSessionId,
  toSessionId,
  now = new Date().toISOString(),
}) {
  if (!paneName || typeof paneName !== "string") throw new TypeError("paneName required");
  if (!fromSessionId || typeof fromSessionId !== "string") throw new TypeError("fromSessionId required");
  if (!toSessionId || typeof toSessionId !== "string") throw new TypeError("toSessionId required");
  const file = replacementsPath(mailboxDir);
  // Read-modify-write is serialized under the ext-state lock (R1.F4):
  // the journal is re-read UNDER the lock, never from a stale pre-lock copy.
  return withStateLock(file, async () => {
    const entries = await loadReplacements(mailboxDir);
    entries.push({ paneName, from: fromSessionId, to: toSessionId, at: now });
    await mkdir(dirname(file), { recursive: true });
    await writeFile(file, JSON.stringify(entries, null, 2) + "\n");
    return entries[entries.length - 1];
  });
}

/** Latest replacement recorded for a pane, or null when none was recorded. */
export async function latestReplacement(mailboxDir, paneName) {
  const entries = await loadReplacements(mailboxDir);
  for (let i = entries.length - 1; i >= 0; i--) {
    if (entries[i].paneName === paneName) return entries[i];
  }
  return null;
}

/**
 * Explicitly rebind every undelivered request whose registered requester is
 * fromIdentity to toIdentity, via `mailbox rebind` (RC-4). Only undelivered
 * records are touched — a reply already delivered stays delivered (exactly
 * once is mailbox-backed). Returns { rebound: [requestIds] }.
 */
export async function rebindRequester({
  mailboxDir,
  fromIdentity,
  toIdentity,
  runMailbox: runMailboxImpl = defaultRunMailbox,
}) {
  if (!mailboxDir) throw new TypeError("mailboxDir required");
  if (!fromIdentity || typeof fromIdentity !== "string") throw new TypeError("fromIdentity required");
  if (!toIdentity || typeof toIdentity !== "string") throw new TypeError("toIdentity required");
  const listed = await runMailboxImpl({ mailboxDir, args: ["list"] });
  if (listed.code !== 0) {
    throw new TypeError(`mailbox list failed (exit ${listed.code}): ${(listed.stderr || listed.stdout).trim()}`);
  }
  const ids = listed.stdout
    .split("\n")
    .map((line) => line.split("\t")[0].trim())
    .filter(Boolean);
  const rebound = [];
  for (const requestId of ids) {
    const shown = await runMailboxImpl({ mailboxDir, args: ["show", "--id", requestId] });
    if (shown.code !== 0) continue;
    let record;
    try {
      record = JSON.parse(shown.stdout);
    } catch {
      continue;
    }
    if (record.requester !== fromIdentity) continue;
    if (record.delivered) continue; // already delivered exactly once — leave it
    const result = await runMailboxImpl({
      mailboxDir,
      args: ["rebind", "--id", requestId, "--requester", toIdentity],
    });
    // Exit 0 ("rebound ...") or the explicit already-bound no-op both mean
    // the request is now bound to toIdentity; anything else is a failure.
    if (
      result.code === 0 &&
      (result.stdout.startsWith("rebound ") || result.stdout.includes("already bound"))
    ) {
      rebound.push(requestId);
    }
  }
  return { rebound };
}

/**
 * Rebind a replacement pane's pending requests: resolves the latest recorded
 * replacement for paneName and rebinds the old session's undelivered requests
 * to toIdentity (default: the replacement session the replacement recorded).
 * Returns { rebound, replacement } or null when no replacement was recorded
 * for the pane (nothing to rebind — also the safe answer for a pane that was
 * never rebound).
 */
export async function rebindPaneRequests({
  mailboxDir,
  paneName,
  toIdentity,
  runMailbox: runMailboxImpl = defaultRunMailbox,
}) {
  const replacement = await latestReplacement(mailboxDir, paneName);
  if (!replacement) return null;
  const target = toIdentity ?? replacement.to;
  const { rebound } = await rebindRequester({
    mailboxDir,
    fromIdentity: replacement.from,
    toIdentity: target,
    runMailbox: runMailboxImpl,
  });
  return { rebound, replacement: { ...replacement, to: target } };
}
