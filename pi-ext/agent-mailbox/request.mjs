// agent_request dispatch (unit-002): validate the target worker pane against
// the session-identity table, then register + dispatch via the mailbox CLI
// subprocess (decision 011) with the reply obligation attached. Returns the
// requestId immediately. Unknown/unreachable worker fails with the reason and
// leaves nothing behind (EXT-1a); if dispatch fails after a successful
// register, the request is cancelled so no half-dispatched register survives.
import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { resolvePane } from "./identity.mjs";

const here = dirname(fileURLToPath(import.meta.url));
export const MAILBOX_CLI = join(here, "..", "..", "mailbox", "mailbox.mjs");

/** Extension-side dispatch failure with a human-readable reason. */
export class RequestError extends Error {}

/**
 * Run one mailbox CLI command as a subprocess. Resolves { code, stdout, stderr }
 * — never rejects for non-zero exits (the exit-code vocabulary is the contract).
 * Overridable via `runMailbox` injection in dispatchRequest for unit tests.
 */
export function runMailbox({ mailboxDir, args, nodePath = process.execPath, cliPath = MAILBOX_CLI }) {
  return new Promise((resolve, reject) => {
    const child = spawn(nodePath, [cliPath, ...args], {
      env: { ...process.env, MAILBOX_DIR: mailboxDir },
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (d) => (stdout += d));
    child.stderr.on("data", (d) => (stderr += d));
    child.on("error", reject);
    child.on("close", (code) => resolve({ code, stdout, stderr }));
  });
}

function requireOk(step, result) {
  if (result.code !== 0) {
    const detail = (result.stderr || result.stdout).trim();
    throw new RequestError(`mailbox ${step} failed (exit ${result.code}): ${detail}`);
  }
}

/**
 * Dispatch a request to a worker pane.
 * - `worker` is a pane name; it must have a session identity binding, else
 *   the dispatch fails immediately (EXT-1a) without registering anything.
 * - The mailbox worker identity is the worker's *session* identity (issue#41
 *   EXT-3b: agent_reply must later match it exactly).
 * - `requesterIdentity` is the requesting pane's session identity, or a
 *   caller-supplied fallback (e.g. "anonymous").
 * Returns { requestId, worker } where `worker` is the session identity bound
 * into the mailbox record.
 */
export async function dispatchRequest({
  mailboxDir,
  worker,
  instruction,
  requesterIdentity,
  runMailbox: runMailboxImpl = runMailbox,
  idFactory = () => `req-${randomUUID()}`,
}) {
  if (!mailboxDir) throw new RequestError("mailboxDir required");
  if (!worker || typeof worker !== "string") throw new RequestError("worker (pane name) is required");
  if (!instruction || typeof instruction !== "string") throw new RequestError("instruction is required");
  if (!requesterIdentity) {
    throw new RequestError("requesterIdentity required (requester session identity or explicit fallback)");
  }

  const binding = await resolvePane({ mailboxDir, paneName: worker });
  if (!binding || !binding.sessionId) {
    // EXT-1a: unknown/unreachable worker — fail before any store mutation.
    throw new RequestError(`unknown worker pane "${worker}": no session identity is bound for this pane; the agent must run in a pane that has started (AGENT_PANE set) before it can be addressed`);
  }
  const run = (args) => runMailboxImpl({ mailboxDir, args });
  const requestId = idFactory();

  const registered = await run([
    "register", "--id", requestId,
    "--requester", requesterIdentity,
    "--worker", binding.sessionId,
    "--instruction", instruction,
  ]);
  requireOk("register", registered);

  try {
    const dispatched = await run(["dispatch", "--id", requestId]);
    requireOk("dispatch", dispatched);
  } catch (err) {
    // No half-dispatch: the register must not survive a failed dispatch.
    // Cancel is terminal (decision 014), so the orphan expectation is closed.
    await run(["cancel", "--id", requestId]);
    throw err;
  }

  return { requestId, worker: binding.sessionId };
}
