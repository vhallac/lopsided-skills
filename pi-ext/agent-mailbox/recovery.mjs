// Recovery controls (unit-008, RC-1..RC-3). The operator or agent can
// inspect pending requests and undelivered replies (RC-1), pause automatic
// delivery so replies become inspectable state (RC-2), and cancel a blocked
// agent_wait without losing the request (RC-3).
//
// Decision 011: the mailbox CLI is the only integration boundary —
// inspection, pause, and resume go through `mailbox list/show/pause/resume`.
// Cancelling a WAIT is in-process only: it aborts the extension's poll loop;
// it NEVER calls `mailbox cancel`, which would cancel the request itself and
// destroy the reply obligation (a cancelled record binds no outcome). After
// a wait cancel the request stays pending and a later agent_wait still
// receives the outcome (EXT-4c unchanged).
import { runMailbox as defaultRunMailbox } from "./request.mjs";

/** In-process registry of active agent_wait poll loops, keyed by requestId. */
const activeWaits = new Map();

/**
 * Register an active wait's AbortController for requestId so a later
 * agent_cancel can abort the blocked poll loop. Multiple concurrent waits on
 * the same requestId overwrite the previous entry (last wait wins).
 */
export function registerActiveWait(requestId, controller) {
  if (!requestId || typeof requestId !== "string") throw new TypeError("requestId required");
  if (!controller || typeof controller.abort !== "function") {
    throw new TypeError("AbortController required");
  }
  activeWaits.set(requestId, controller);
}

/** Unregister a wait (called when the wait finishes for any reason). */
export function unregisterActiveWait(requestId, controller) {
  if (activeWaits.get(requestId) === controller) activeWaits.delete(requestId);
}

/**
 * Cancel a BLOCKED WAIT for requestId (RC-3): aborts the in-process poll
 * loop so the wait returns without a result, without consuming the reply
 * and without touching the request itself. Returns
 * { cancelled: true, hadActiveWait: true } when a wait was aborted, or
 * { cancelled: false, hadActiveWait: false } when nothing was blocked —
 * the request itself stays pending either way.
 */
export function cancelWait(requestId) {
  const controller = activeWaits.get(requestId);
  if (!controller) return { cancelled: false, hadActiveWait: false };
  controller.abort();
  activeWaits.delete(requestId);
  return { cancelled: true, hadActiveWait: true };
}

/**
 * Inspect recovery state (RC-1): list requests with their pending/delivery
 * state. `pendingOnly` restricts to records that are not yet delivered and
 * not cancelled. Returns [{ requestId, state, hasReply, delivered, paused,
 * requester, worker }].
 */
export async function listRecoverable({
  mailboxDir,
  pendingOnly = false,
  runMailbox: runMailboxImpl = defaultRunMailbox,
} = {}) {
  if (!mailboxDir) throw new TypeError("mailboxDir required");
  const listed = await runMailboxImpl({
    mailboxDir,
    args: pendingOnly ? ["list", "--pending"] : ["list"],
  });
  if (listed.code !== 0) {
    throw new TypeError(`mailbox list failed (exit ${listed.code}): ${(listed.stderr || listed.stdout).trim()}`);
  }
  const ids = listed.stdout
    .split("\n")
    .map((line) => line.split("\t")[0].trim())
    .filter(Boolean);
  const records = [];
  for (const requestId of ids) {
    const shown = await runMailboxImpl({ mailboxDir, args: ["show", "--id", requestId] });
    if (shown.code !== 0) continue;
    let record;
    try {
      record = JSON.parse(shown.stdout);
    } catch {
      continue;
    }
    if (pendingOnly && (record.state === "cancelled" || record.delivered)) continue;
    records.push({
      requestId,
      state: record.state,
      hasReply: Boolean(record.reply),
      delivered: record.delivered === true,
      paused: record.paused === true,
      requester: record.requester,
      worker: record.worker,
      replyStatus: record.reply?.status ?? null,
    });
  }
  return records;
}

/**
 * Pause automatic delivery for requestId (RC-2): while paused, a reply stays
 * persisted (inspectable via mailbox show / agent_list) and delivery holds —
 * `mailbox consume` answers "held-paused", which the delivery layer treats
 * as a non-winning consume (no follow-up round). Idempotent: pausing an
 * already-paused request is a mailbox-side no-op. Returns { message }.
 */
export async function pauseDelivery({
  mailboxDir,
  requestId,
  runMailbox: runMailboxImpl = defaultRunMailbox,
} = {}) {
  if (!mailboxDir) throw new TypeError("mailboxDir required");
  if (!requestId || typeof requestId !== "string") throw new TypeError("requestId required");
  const result = await runMailboxImpl({ mailboxDir, args: ["pause", "--id", requestId] });
  const message = (result.stdout || result.stderr).trim();
  if (result.code !== 0) {
    throw new TypeError(`mailbox pause failed (exit ${result.code}): ${message}`);
  }
  return { message };
}

/**
 * Resume delivery for requestId (RC-2): after resume, a held reply is
 * delivered on the next wait or delivery probe. Idempotent like pause.
 * Returns { message }.
 */
export async function resumeDelivery({
  mailboxDir,
  requestId,
  runMailbox: runMailboxImpl = defaultRunMailbox,
} = {}) {
  if (!mailboxDir) throw new TypeError("mailboxDir required");
  if (!requestId || typeof requestId !== "string") throw new TypeError("requestId required");
  const result = await runMailboxImpl({ mailboxDir, args: ["resume", "--id", requestId] });
  const message = (result.stdout || result.stderr).trim();
  if (result.code !== 0) {
    throw new TypeError(`mailbox resume failed (exit ${result.code}): ${message}`);
  }
  return { message };
}
