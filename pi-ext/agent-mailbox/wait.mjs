// agent_wait (unit-004): the requesting pane blocks on a dispatched request
// without consuming LLM rounds — the blocking is an in-extension bounded
// subprocess poll loop on mailbox state (decision 011: the CLI is the only
// integration boundary), never an LLM round. When the outcome is already
// persisted the wait returns immediately (EXT-2a); on timeout it returns
// "no outcome yet" WITHOUT consuming the reply, so the request stays pending
// and a later wait still receives the outcome (EXT-4c). Delivery itself is
// exactly-once via `mailbox consume` (decision 012 exit vocabulary).
import { runMailbox as defaultRunMailbox } from "./request.mjs";
import { resolvePane } from "./identity.mjs";

export class WaitError extends Error {
  constructor(message, { kind = "error" } = {}) {
    super(message);
    this.kind = kind; // "not-found" | "error"
  }
}

function exitToKind(code) {
  if (code === 4) return "not-found";
  return "error";
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Block until the reply for requestId is available, or time out.
 * - Polls `mailbox show --id` (read-only probe: never consumes) on a fixed
 *   interval until `record.reply` is non-null or the deadline passes.
 * - On outcome: consumes via `mailbox consume --id --requester` (exactly
 *   once; a second consume is a mailbox-side no-op) and returns the reply.
 * - On timeout: returns { status: "timeout" } without any consume — the
 *   request stays pending (EXT-4c).
 * - Unknown requestId surfaces as WaitError kind "not-found" (exit 4).
 * Returns { status: "outcome", requestId, reply, delivered } on success.
 */
export async function waitForOutcome({
  mailboxDir,
  requestId,
  requesterIdentity,
  timeoutMs = 30_000,
  pollMs = 250,
  signal, // optional AbortSignal: aborting the wait cancels the WAIT (RC-3), never the request
  runMailbox: runMailboxImpl = defaultRunMailbox,
  sleepImpl = sleep,
  nowImpl = () => Date.now(),
}) {
  if (!mailboxDir) throw new WaitError("mailboxDir required");
  if (!requestId || typeof requestId !== "string") {
    throw new WaitError("requestId is required");
  }
  if (!requesterIdentity) {
    throw new WaitError(
      "requesterIdentity required (requester session identity or explicit fallback)",
    );
  }
  if (!Number.isFinite(timeoutMs) || timeoutMs < 0) throw new WaitError("timeoutMs must be a non-negative number");

  const deadline = nowImpl() + timeoutMs;
  for (;;) {
    // RC-3: a cancelled wait returns without a result and without consuming —
    // the request stays pending and a later wait still receives the outcome.
    if (signal?.aborted) return { status: "cancelled", requestId };
    const shown = await runMailboxImpl({ mailboxDir, args: ["show", "--id", requestId] });
    if (shown.code !== 0) {
      // Exit 4 = unknown request (decision 012). Anything else is unexpected.
      const detail = (shown.stderr || shown.stdout).trim();
      throw new WaitError(`mailbox show failed (exit ${shown.code}): ${detail}`, {
        kind: exitToKind(shown.code),
      });
    }
    let record;
    try {
      record = JSON.parse(shown.stdout);
    } catch {
      throw new WaitError(`mailbox show returned unparsable output for ${requestId}`);
    }
    if (record.reply) {
      // Outcome persisted (EXT-2a: may predate the wait). Consume delivers
      // it exactly once; a repeated consume is a mailbox-side no-op.
      const consumed = await runMailboxImpl({
        mailboxDir,
        args: ["consume", "--id", requestId, "--requester", requesterIdentity],
      });
      if (consumed.code !== 0) {
        const detail = (consumed.stderr || consumed.stdout).trim();
        throw new WaitError(`mailbox consume failed (exit ${consumed.code}): ${detail}`);
      }
      return {
        status: "outcome",
        requestId,
        reply: record.reply,
        delivered: record.delivered === true,
      };
    }
    if (nowImpl() >= deadline) {
      // EXT-4c: "no outcome yet" WITHOUT consuming — the request stays
      // pending and a later wait still receives the outcome.
      return { status: "timeout", requestId };
    }
    await sleepImpl(Math.min(pollMs, deadline - nowImpl()));
  }
}

/**
 * Resolve the waiting pane's own requester identity the same way
 * agent_request does: bound session identity, else explicit "anonymous".
 */
export async function resolveRequesterIdentity({ mailboxDir, paneName }) {
  if (!mailboxDir) throw new WaitError("mailboxDir required");
  if (!paneName) return "anonymous";
  const own = await resolvePane({ mailboxDir, paneName });
  return own?.sessionId ?? "anonymous";
}
