// agent_reply (unit-003): the worker pane submits a structured outcome
// (status + report) for a dispatched requestId. The worker identity passed
// to the mailbox must be the worker pane's *session* identity (issue#41
// EXT-3b: the mailbox rejects a reply whose submitting identity does not
// match record.worker). The CLI exit vocabulary (2 usage / 3 rejected /
// 4 not found) is the contract; a rejected or missing request surfaces the
// mailbox rejection to the agent.
import { dispatchRequest, runMailbox, MAILBOX_CLI } from "./request.mjs";
import { resolvePane } from "./identity.mjs";

const defaultRunMailbox = runMailbox;

export { dispatchRequest, runMailbox, MAILBOX_CLI };

/** Extension-side reply failure with a human-readable reason. */
export class ReplyError extends Error {
  constructor(message, { kind = "rejected" } = {}) {
    super(message);
    this.kind = kind; // "rejected" | "not-found" | "error"
  }
}

function exitToKind(code) {
  if (code === 3) return "rejected";
  if (code === 4) return "not-found";
  return "error";
}

/**
 * Submit an outcome for a dispatched request.
 * - `workerPane` names the replying pane; its bound session identity is used
 *   as the submitting worker identity (issue#41 EXT-3b). A caller-supplied
 *   `workerIdentity` overrides it (tests / already-known identity).
 * - Invalid status vocabulary, identity mismatch, cancelled request, or
 *   unknown requestId all surface as ReplyError with the mailbox's reason
 *   (exit 3/4 mapped to kind "rejected"/"not-found").
 * Returns { requestId, status } on success.
 */
export async function replyOutcome({
  mailboxDir,
  requestId,
  status,
  report,
  workerPane,
  workerIdentity,
  runMailbox: runMailboxImpl = defaultRunMailbox,
  resolvePane: resolvePaneImpl = resolvePane,
}) {
  if (!mailboxDir) throw new ReplyError("mailboxDir required");
  if (!requestId || typeof requestId !== "string") {
    throw new ReplyError("requestId is required");
  }

  let identity = workerIdentity;
  if (!identity) {
    if (!workerPane || typeof workerPane !== "string") {
      throw new ReplyError('worker identity required: pass workerPane (a pane with a bound session identity) or workerIdentity');
    }
    const binding = await resolvePaneImpl({ mailboxDir, paneName: workerPane });
    if (!binding || !binding.sessionId) {
      throw new ReplyError(
        `unknown worker pane "${workerPane}": no session identity is bound for this pane; the agent must run in a pane that has started (AGENT_PANE set) before it can reply`,
        { kind: "rejected" },
      );
    }
    identity = binding.sessionId;
  }

  const args = ["reply", "--id", requestId, "--worker", identity, "--status", status];
  if (report !== undefined && report !== null) args.push("--report", String(report));

  const result = await runMailboxImpl({ mailboxDir, args });
  if (result.code !== 0) {
    const detail = (result.stderr || result.stdout).trim();
    throw new ReplyError(`mailbox reply rejected: ${detail}`, { kind: exitToKind(result.code) });
  }
  return { requestId, status, workerIdentity: identity };
}
