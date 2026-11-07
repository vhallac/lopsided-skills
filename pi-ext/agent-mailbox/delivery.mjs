// Delivery layer (unit-005): a reply arriving while the requester is idle or
// executing tool rounds starts exactly one follow-up round attributed to the
// worker as a CUSTOM message (pi.sendMessage with triggerTurn — never
// operator-typed text), with no mid-run steering. Exactly-once is backed by
// the mailbox: a follow-up is sent only when this process's `mailbox consume`
// is the winning delivery (stdout starts with "delivered reply for"); a
// duplicate consume is a mailbox-side no-op and produces no continuation
// (EXT-4b). Probes run only at turn boundaries (session_start, turn_end) and
// on an idle poll timer — never mid-run — so a reply that arrives during tool
// rounds is queued until the next boundary (EXT-4a).
import { runMailbox as defaultRunMailbox } from "./request.mjs";

const CONSUMED_PREFIX = "delivered reply for ";

/**
 * Build the attributed follow-up message for a delivered reply.
 * Custom message shape per docs/extensions.md (message-renderer example):
 * { customType, content, display, details }. Attribution to worker B lives
 * in the content header and details (A-2, verified in unit-005: custom
 * messages carry customType + details; before_agent_start sees
 * messageType "custom").
 */
export function deliveryMessage({ requestId, worker, reply }) {
  const workerLabel = worker ?? "unknown-worker";
  return {
    customType: "agent-mailbox-delivery",
    content:
      `Outcome from worker ${workerLabel} for request ${requestId} ` +
      `(status: ${reply.status}):\n${reply.report ?? "(no report)"}`,
    display: true,
    details: {
      requestId,
      worker: workerLabel,
      reply,
      source: "agent-mailbox-delivery",
    },
  };
}

/**
 * Probe the mailbox for settled-but-undelivered replies addressed to this
 * requester and deliver each exactly once:
 * - `mailbox list` enumerates request ids (read-only).
 * - `mailbox show --id` filters to records where this identity is the
 *   requester, a reply is persisted, and delivery has not happened.
 * - `mailbox consume --id --requester` performs the exactly-once delivery;
 *   only a winning consume (stdout prefix) produces a follow-up message via
 *   `sendMessage(message, { triggerTurn: true })`.
 * `seen` is the caller's dedup set (in-process continuation guard on top of
 * the mailbox's delivered flag). Returns { delivered: [...] }.
 */
export async function probeDeliveries({
  mailboxDir,
  requesterIdentity,
  sendMessage,
  seen = new Set(),
  runMailbox: runMailboxImpl = defaultRunMailbox,
}) {
  if (!mailboxDir || !requesterIdentity) return { delivered: [] };
  const listed = await runMailboxImpl({ mailboxDir, args: ["list"] });
  if (listed.code !== 0) return { delivered: [] };
  const ids = listed.stdout
    .split("\n")
    .map((line) => line.split("\t")[0].trim())
    .filter(Boolean);
  const delivered = [];
  for (const requestId of ids) {
    if (seen.has(requestId)) continue;
    const shown = await runMailboxImpl({ mailboxDir, args: ["show", "--id", requestId] });
    if (shown.code !== 0) continue;
    let record;
    try {
      record = JSON.parse(shown.stdout);
    } catch {
      continue;
    }
    if (!record.reply || record.delivered) continue;
    if (record.requester !== requesterIdentity) continue;
    const consumed = await runMailboxImpl({
      mailboxDir,
      args: ["consume", "--id", requestId, "--requester", requesterIdentity],
    });
    if (consumed.code !== 0 || !consumed.stdout.startsWith(CONSUMED_PREFIX)) {
      // Lost race (another consumer delivered first), held-paused, or a
      // refusal — in every case this process must not send a continuation
      // (EXT-4b: no duplicate continuation).
      continue;
    }
    seen.add(requestId);
    const delivery = { requestId, reply: record.reply, worker: record.worker };
    delivered.push(delivery);
    if (sendMessage) {
      sendMessage(deliveryMessage(delivery), { triggerTurn: true });
    }
  }
  return { delivered };
}

/**
 * Wire delivery probes into the extension lifecycle: session_start (catches
 * replies persisted before the session began), turn_end (queues replies that
 * arrived during the run without steering it), and an idle poll timer so a
 * reply arriving while fully idle still starts its follow-up round. The
 * timer is cleared on session_shutdown. All probes share one in-flight guard
 * and one seen-set, so a reply can never produce two continuations.
 */
export function createDeliveryHooks(pi, options = {}) {
  const mailboxDir = options.mailboxDir ?? process.env.MAILBOX_DIR;
  const seen = new Set();
  let inFlight = false;
  let timer = null;

  const resolveIdentity = async (paneName) => {
    if (options.requesterIdentity) return options.requesterIdentity;
    if (!paneName) return null;
    const { resolvePane } = await import("./identity.mjs");
    const own = await resolvePane({ mailboxDir, paneName });
    return own?.sessionId ?? null;
  };

  const probe = async (paneName) => {
    if (!mailboxDir || inFlight) return;
    inFlight = true;
    try {
      const requesterIdentity = await resolveIdentity(paneName);
      await probeDeliveries({
        mailboxDir,
        requesterIdentity,
        seen,
        sendMessage: (message, opts) => pi.sendMessage(message, opts),
      });
    } catch {
      // Delivery is best-effort: the mailbox persists the reply and a later
      // probe (or agent_wait) still delivers it.
    } finally {
      inFlight = false;
    }
  };

  return {
    onSessionStart(paneName) {
      if (!mailboxDir) return;
      probe(paneName);
      if (!timer && (options.probeMs ?? 2000) > 0) {
        timer = setInterval(() => probe(paneName), options.probeMs ?? 2000);
        timer.unref?.();
      }
    },
    onTurnEnd(paneName) {
      probe(paneName);
    },
    onSessionShutdown() {
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
    },
  };
}
