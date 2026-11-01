// Settle detection (unit-006, EXT-3a): when a worker pane's session settles
// (session_shutdown) without having called agent_reply on a dispatched
// request, the outcome must resolve explicitly as "stopped without a
// result" — never DONE — and the request must stay inspectable. The worker's
// own extension is the only party that reliably observes its shutdown, so on
// session_shutdown it sweeps the mailbox for dispatched requests where it is
// the worker and no reply is persisted, and persists a FAILED outcome whose
// report says "stopped without a result". Because the outcome is persisted
// in the mailbox (decision 011 boundary), pending agent_wait poll loops
// resolve on their next probe and queued follow-up deliveries pick the
// outcome up at the next delivery probe — no extra signaling needed.
import { runMailbox as defaultRunMailbox } from "./request.mjs";
import { replyOutcome } from "./reply.mjs";
import { resolvePane } from "./identity.mjs";

export const STOPPED_REPORT =
  "stopped without a result: the worker session settled (session ended) without calling agent_reply";

/**
 * Sweep dispatched requests owned by this worker session and settle the ones
 * left without a reply:
 * - `mailbox list` enumerates request ids (read-only).
 * - `mailbox show --id` reads each record (read-only).
 * - A record settles only when record.worker === this worker's session
 *   identity AND no reply is persisted. The outcome is submitted through the
 *   ordinary `mailbox reply` path with status FAILED (vocabulary per
 *   agent_reply; never DONE), so all mailbox semantics apply unchanged.
 * - Requests already replied, cancelled, or owned by another worker are
 *   untouched; a second sweep is a no-op (reply now persisted).
 * `workerIdentity` overrides the binding lookup (tests / known identity).
 * Returns { settled: [requestId, ...] }.
 */
export async function settlePendingOnShutdown({
  mailboxDir,
  workerPane,
  workerIdentity,
  status = "FAILED",
  report = STOPPED_REPORT,
  runMailbox: runMailboxImpl = defaultRunMailbox,
  resolvePane: resolvePaneImpl = resolvePane,
}) {
  if (!mailboxDir) return { settled: [] };

  let identity = workerIdentity;
  if (!identity && workerPane) {
    const binding = await resolvePaneImpl({ mailboxDir, paneName: workerPane });
    identity = binding?.sessionId ?? null;
  }
  if (!identity) return { settled: [] };

  const listed = await runMailboxImpl({ mailboxDir, args: ["list"] });
  if (listed.code !== 0) return { settled: [] };
  const ids = listed.stdout
    .split("\n")
    .map((line) => line.split("\t")[0].trim())
    .filter(Boolean);

  const settled = [];
  for (const requestId of ids) {
    const shown = await runMailboxImpl({ mailboxDir, args: ["show", "--id", requestId] });
    if (shown.code !== 0) continue;
    let record;
    try {
      record = JSON.parse(shown.stdout);
    } catch {
      continue;
    }
    if (record.worker !== identity) continue;
    if (record.reply) continue;
    // Ordinary reply path: mailbox validates the vocabulary and the worker
    // identity (EXT-3b) and persists the outcome; the request stays fully
    // inspectable (show) and deliverable (consume) afterwards.
    await replyOutcome({
      mailboxDir,
      requestId,
      status,
      report,
      workerIdentity: identity,
      runMailbox: runMailboxImpl,
    });
    settled.push(requestId);
  }
  return { settled };
}
