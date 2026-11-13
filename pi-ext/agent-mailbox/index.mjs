// agent-mailbox pi extension (issue#42).
// agent_request performs real dispatch (unit-002); agent_reply submits
// outcomes (unit-003); agent_wait blocks on the outcome without consuming
// LLM rounds (unit-004). The mailbox CLI (decision 011: one package, bin
// shared) is invoked as a subprocess.
import { resolvePaneName, bindPane, resolvePane, loadBindings } from "./identity.mjs";
import { recordReplacement, rebindPaneRequests } from "./rebind.mjs";
import { dispatchRequest, RequestError } from "./request.mjs";
import { replyOutcome } from "./reply.mjs";
import { waitForOutcome, resolveRequesterIdentity, WaitError } from "./wait.mjs";
import { createDeliveryHooks } from "./delivery.mjs";
import { settlePendingOnShutdown } from "./settle.mjs";
import {
  registerActiveWait,
  unregisterActiveWait,
  cancelWait,
  listRecoverable,
  pauseDelivery,
  resumeDelivery,
} from "./recovery.mjs";

export const TOOL_NAMES = [
  "agent_request",
  "agent_wait",
  "agent_reply",
  "agent_rebind",
  "agent_list",
  "agent_pause",
  "agent_resume",
  "agent_cancel",
];

function requestErrorResult(message) {
  return {
    content: [{ type: "text", text: `agent_request failed: ${message}` }],
    details: { tool: "agent_request", error: true, reason: message },
  };
}

function replyErrorResult(message) {
  return {
    content: [{ type: "text", text: `agent_reply failed: ${message}` }],
    details: { tool: "agent_reply", error: true, reason: message },
  };
}

export { waitForOutcome, WaitError };

/**
 * Real agent_request execute (unit-002). Resolves the requester's own
 * session identity from the bindings (pane bound at session_start) and
 * dispatches via the mailbox. Fail-fast (decision 015): an unbound pane
 * rejects the request instead of proceeding as an anonymous requester.
 */
function requestExecute(options) {
  return async (_toolCallId, params) => {
    const mailboxDir = options.mailboxDir ?? process.env.MAILBOX_DIR;
    try {
      let requesterIdentity = options.requesterIdentity;
      if (!requesterIdentity && mailboxDir) {
        const paneName = options.paneName ?? resolvePaneName(options);
        if (!paneName) {
          throw new RequestError(
            "requester identity required: no pane name (AGENT_PANE/HERDR_PANE_ID) is set for this pane; the agent must run in a pane that has started before it can request",
          );
        }
        const own = await resolvePane({ mailboxDir, paneName });
        if (!own || !own.sessionId) {
          throw new RequestError(
            `requester identity required: pane "${paneName}" has no bound session identity; the agent must run in a pane that has started (AGENT_PANE/HERDR_PANE_ID set) before it can request`,
          );
        }
        requesterIdentity = own.sessionId;
      }
      const { requestId, worker } = await dispatchRequest({
        mailboxDir,
        worker: params.worker,
        instruction: params.instruction,
        requesterIdentity,
      });
      return {
        content: [
          {
            type: "text",
            text: `Request dispatched to worker pane ${params.worker} (session ${worker}). requestId: ${requestId}. Use agent_wait to block on the outcome.`,
          },
        ],
        details: { tool: "agent_request", requestId, worker },
      };
    } catch (err) {
      return requestErrorResult(err?.message ?? String(err));
    }
  };
}

/**
 * Real agent_reply execute (unit-003). Resolves the replying pane's session
 * identity from the bindings (pane bound at session_start) and submits the
 * outcome via the mailbox. Mailbox rejections (invalid status, identity
 * mismatch, cancelled/unknown request) surface the mailbox's own reason.
 */
function replyExecute(options) {
  return async (_toolCallId, params) => {
    const mailboxDir = options.mailboxDir ?? process.env.MAILBOX_DIR;
    try {
      const { workerIdentity } = await replyOutcome({
        mailboxDir,
        requestId: params.requestId,
        status: params.status,
        report: params.report,
        workerPane: options.paneName ?? resolvePaneName(options),
      });
      return {
        content: [
          {
            type: "text",
            text: `Reply persisted for request ${params.requestId} (status: ${params.status}, worker session ${workerIdentity}). The requesting pane will receive this outcome on its next wait or delivery.`,
          },
        ],
        details: { tool: "agent_reply", requestId: params.requestId, status: params.status },
      };
    } catch (err) {
      return replyErrorResult(err?.message ?? String(err));
    }
  };
}

/**
 * Real agent_wait execute (unit-004). Blocks in-extension (bounded poll loop
 * over mailbox state — never an LLM round) until the outcome is available,
 * consumes it exactly once, or returns "no outcome yet" on timeout without
 * consuming (EXT-4c: the request stays pending).
 */
function waitExecute(options) {
  return async (_toolCallId, params) => {
    const mailboxDir = options.mailboxDir ?? process.env.MAILBOX_DIR;
    try {
      const paneName = options.paneName ?? resolvePaneName(options);
      const requesterIdentity =
        options.requesterIdentity ??
        (await resolveRequesterIdentity({ mailboxDir, paneName }));
      // RC-3: the wait is cancellable in-process. The AbortController is
      // registered so agent_cancel can abort the blocked poll loop; the
      // request itself is never touched.
      const controller = new AbortController();
      registerActiveWait(params.requestId, controller);
      let result;
      try {
        result = await waitForOutcome({
          mailboxDir,
          requestId: params.requestId,
          requesterIdentity,
          timeoutMs: params.timeoutMs,
          signal: controller.signal,
        });
      } finally {
        unregisterActiveWait(params.requestId, controller);
      }
      if (result.status === "cancelled") {
        return {
          content: [
            {
              type: "text",
              text: `wait cancelled for request ${params.requestId}: the wait returned without a result and nothing was consumed; the request stays pending and can be waited on later.`,
            },
          ],
          details: { tool: "agent_wait", requestId: params.requestId, status: "cancelled" },
        };
      }
      if (result.status === "timeout") {
        return {
          content: [
            {
              type: "text",
              text: `no outcome yet for request ${params.requestId}: the wait timed out without consuming the reply; the request stays pending — call agent_wait again later.`,
            },
          ],
          details: { tool: "agent_wait", requestId: params.requestId, status: "timeout" },
        };
      }
      const { reply } = result;
      return {
        content: [
          {
            type: "text",
            text: `Outcome for request ${params.requestId} (status: ${reply.status}):\n${reply.report ?? "(no report)"}`,
          },
        ],
        details: {
          tool: "agent_wait",
          requestId: params.requestId,
          status: "outcome",
          reply,
        },
      };
    } catch (err) {
      return waitErrorResult(err?.message ?? String(err));
    }
  };
}

function waitErrorResult(message) {
  return {
    content: [{ type: "text", text: `agent_wait failed: ${message}` }],
    details: { tool: "agent_wait", error: true, reason: message },
  };
}

/**
 * agent_rebind execute (unit-007, RC-4). Explicit rebind after a pane's
 * session was replaced: rebinds the old session's undelivered requests to
 * the replacement session so pending replies deliver to the replacement.
 * Without this explicit call the replacement NEVER receives the old
 * session's replies (EXT-4d).
 */
function rebindExecute(options) {
  return async (_toolCallId, params) => {
    const mailboxDir = options.mailboxDir ?? process.env.MAILBOX_DIR;
    try {
      const paneName = params.pane ?? options.paneName ?? resolvePaneName(options);
      if (!paneName) throw new Error("pane name required (param `pane`, AGENT_PANE, or HERDR_PANE_ID)");
      const result = await rebindPaneRequests({ mailboxDir, paneName, toIdentity: params.toIdentity });
      if (!result) {
        return {
          content: [
            {
              type: "text",
              text: `agent_rebind: no session replacement recorded for pane ${paneName}; nothing to rebind.`,
            },
          ],
          details: { tool: "agent_rebind", pane: paneName, rebound: [] },
        };
      }
      const { rebound, replacement } = result;
      return {
        content: [
          {
            type: "text",
            text:
              `Rebound ${rebound.length} pending request(s) from session ${replacement.from} ` +
              `to ${replacement.to} for pane ${paneName}${rebound.length ? `: ${rebound.join(", ")}` : ""}. ` +
              "Pending replies will now deliver to the replacement session.",
          },
        ],
        details: { tool: "agent_rebind", pane: paneName, rebound, replacement },
      };
    } catch (err) {
      return {
        content: [{ type: "text", text: `agent_rebind failed: ${err?.message ?? String(err)}` }],
        details: { tool: "agent_rebind", error: true, reason: err?.message ?? String(err) },
      };
    }
  };
}

/**
 * Recovery controls (unit-008, RC-1..RC-3). Shared execute factory for the
 * inspect/pause/resume/cancel tools: mailbox subprocess for list/pause/
 * resume, in-process abort for cancelling a blocked wait (never `mailbox
 * cancel` — that would destroy the request's reply obligation).
 */
function recoveryExecute(options, { tool, run }) {
  return async (_toolCallId, params) => {
    const mailboxDir = options.mailboxDir ?? process.env.MAILBOX_DIR;
    try {
      return await run({ mailboxDir, params });
    } catch (err) {
      const message = err?.message ?? String(err);
      return {
        content: [{ type: "text", text: `${tool} failed: ${message}` }],
        details: { tool, error: true, reason: message },
      };
    }
  };
}

function listExecute(options) {
  return recoveryExecute(options, {
    tool: "agent_list",
    run: async ({ mailboxDir, params }) => {
      const records = await listRecoverable({ mailboxDir, pendingOnly: params.pendingOnly === true });
      const lines = records.map(
        (r) =>
          `${r.requestId}\t${r.state}\t${r.hasReply ? `reply:${r.replyStatus}` : "no-reply"}` +
          `\t${r.delivered ? "delivered" : "undelivered"}\t${r.paused ? "paused" : "active"}`,
      );
      return {
        content: [
          {
            type: "text",
            text: lines.length
              ? `requestId\tstate\treply\tdelivery\tpause\n${lines.join("\n")}`
              : "no requests in the mailbox",
          },
        ],
        details: { tool: "agent_list", records },
      };
    },
  });
}

function pauseExecute(options) {
  return recoveryExecute(options, {
    tool: "agent_pause",
    run: async ({ mailboxDir, params }) => {
      const { message } = await pauseDelivery({ mailboxDir, requestId: params.requestId });
      return {
        content: [
          {
            type: "text",
            text: `${message}. Replies for this request are now held as inspectable state and will not be delivered until resumed.`,
          },
        ],
        details: { tool: "agent_pause", requestId: params.requestId, paused: true },
      };
    },
  });
}

function resumeExecute(options) {
  return recoveryExecute(options, {
    tool: "agent_resume",
    run: async ({ mailboxDir, params }) => {
      const { message } = await resumeDelivery({ mailboxDir, requestId: params.requestId });
      return {
        content: [
          {
            type: "text",
            text: `${message}. Any held reply delivers on the next wait or delivery probe.`,
          },
        ],
        details: { tool: "agent_resume", requestId: params.requestId, paused: false },
      };
    },
  });
}

function cancelExecute(options) {
  return recoveryExecute(options, {
    tool: "agent_cancel",
    run: async ({ params }) => {
      const { cancelled, hadActiveWait } = cancelWait(params.requestId);
      if (!hadActiveWait) {
        return {
          content: [
            {
              type: "text",
              text: `no blocked agent_wait for request ${params.requestId} in this session; nothing to cancel. The request itself is untouched and stays pending.`,
            },
          ],
          details: { tool: "agent_cancel", requestId: params.requestId, cancelled: false },
        };
      }
      return {
        content: [
          {
            type: "text",
            text: `cancelled the blocked wait for request ${params.requestId}: it returns without a result. The request stays pending and can be waited on later.`,
          },
        ],
        details: { tool: "agent_cancel", requestId: params.requestId, cancelled: true },
      };
    },
  });
}

/**
 * Build the tool definitions. Exported so unit tests can assert
 * registration without running inside pi.
 */
export function createTools(options = {}) {
  return [
    {
      name: "agent_request",
      label: "Agent Request",
      description:
        "Dispatch a request to another agent pane via the mailbox: registers, dispatches, and returns a requestId with a reply obligation.",
      parameters: {
        type: "object",
        properties: {
          worker: { type: "string", description: "Target worker pane name" },
          instruction: { type: "string", description: "What the worker should do" },
        },
        required: ["worker", "instruction"],
      },
      execute: requestExecute(options),
    },
    {
      name: "agent_wait",
      label: "Agent Wait",
      description:
        "Block (without consuming LLM rounds) until the reply for a requestId is available, or return 'no outcome yet' on timeout.",
      parameters: {
        type: "object",
        properties: {
          requestId: { type: "string", description: "Request id to wait on" },
          timeoutMs: { type: "number", description: "Maximum time to block, milliseconds" },
        },
        required: ["requestId"],
      },
      execute: waitExecute(options),
    },
    {
      name: "agent_reply",
      label: "Agent Reply",
      description:
        "Submit a worker reply (status + report) for a dispatched requestId. Status vocabulary: DONE, NEEDS_INPUT, BLOCKED, FAILED.",
      parameters: {
        type: "object",
        properties: {
          requestId: { type: "string", description: "Request id being answered" },
          status: { type: "string", description: "One of DONE, NEEDS_INPUT, BLOCKED, FAILED" },
          report: { type: "string", description: "Outcome report text" },
        },
        required: ["requestId", "status"],
      },
      execute: replyExecute(options),
    },
    {
      name: "agent_rebind",
      label: "Agent Rebind",
      description:
        "Explicitly rebind a pane's pending requests from its previous session identity to the replacement session (RC-4). Required after a pane restart: without it, the new session never receives the old session's replies (EXT-4d).",
      parameters: {
        type: "object",
        properties: {
          pane: { type: "string", description: "Pane whose session was replaced (defaults to this pane)" },
          toIdentity: {
            type: "string",
            description: "Target session identity (defaults to the replacement session recorded at session_start)",
          },
        },
        required: [],
      },
      execute: rebindExecute(options),
    },
  {
    name: "agent_list",
    label: "Agent List",
    description:
      "Inspect recovery state (RC-1): list mailbox requests with pending/delivery state, including pending requests and undelivered replies.",
    parameters: {
      type: "object",
      properties: {
        pendingOnly: {
          type: "boolean",
          description: "Restrict to undelivered, non-cancelled requests (default: list everything)",
        },
      },
      required: [],
    },
    execute: listExecute(options),
  },
  {
    name: "agent_pause",
    label: "Agent Pause",
    description:
      "Pause automatic delivery for a requestId (RC-2): replies become inspectable state and are not delivered until resumed.",
    parameters: {
      type: "object",
      properties: {
        requestId: { type: "string", description: "Request id whose delivery to pause" },
      },
      required: ["requestId"],
    },
    execute: pauseExecute(options),
  },
  {
    name: "agent_resume",
    label: "Agent Resume",
    description:
      "Resume automatic delivery for a requestId (RC-2): held replies deliver on the next wait or delivery probe.",
    parameters: {
      type: "object",
      properties: {
        requestId: { type: "string", description: "Request id whose delivery to resume" },
      },
      required: ["requestId"],
    },
    execute: resumeExecute(options),
  },
  {
    name: "agent_cancel",
    label: "Agent Cancel",
    description:
      "Cancel a blocked agent_wait for a requestId (RC-3): the wait returns without a result; the request itself stays pending and can be waited on later. This does NOT cancel the request.",
    parameters: {
      type: "object",
      properties: {
        requestId: { type: "string", description: "Request id whose blocked wait to cancel" },
      },
      required: ["requestId"],
    },
    execute: cancelExecute(options),
  },
];
}

/**
 * Extension factory. Exported default; pi calls it with ExtensionAPI.
 * On session_start, binds this pane's name to the session identity so
 * later units can resolve requester/worker identities per pane.
 */
export default function agentMailboxExtension(pi, options = {}) {
  const mailboxDir = options.mailboxDir ?? process.env.MAILBOX_DIR;
  for (const tool of createTools(options)) {
    pi.registerTool(tool);
  }
  // Delivery layer (unit-005): probes at session boundaries + idle timer
  // deliver settled-but-undelivered replies as custom follow-up rounds.
  const delivery = createDeliveryHooks(pi, options);
  pi.on("session_start", async (_event, ctx) => {
    const paneName = options.paneName ?? resolvePaneName(options);
    if (!paneName || !mailboxDir) return; // anonymous pane: no binding
    // Session replacement bookkeeping (unit-007, EXT-4d): when a NEW session
    // reuses this pane name, record the replacement — but do NOT rebind the
    // old session's requests. Old replies stay undeliverable to the
    // replacement until an explicit agent_rebind (RC-4).
    const previous = (await loadBindings(mailboxDir))[paneName];
    // R1.F5: no silent pane-name fallback. Without a real session id the
    // binding would be wrong for every identity lookup that follows, so
    // refuse loudly instead of binding to the pane name.
    const sessionId = options.sessionId ?? ctx?.sessionManager?.getSessionId?.();
    if (!sessionId) {
      throw new Error(
        `agent-mailbox: cannot bind pane "${paneName}": no session id available ` +
        "(options.sessionId and ctx.sessionManager.getSessionId both missing); " +
        "refusing to fall back to the pane name",
      );
    }
    if (previous && previous.sessionId && previous.sessionId !== sessionId) {
      await recordReplacement({
        mailboxDir,
        paneName,
        fromSessionId: previous.sessionId,
        toSessionId: sessionId,
      });
    }
    await bindPane({ mailboxDir, paneName, sessionId });
    delivery.onSessionStart(paneName);
  });
  pi.on("turn_end", () => {
    delivery.onTurnEnd(options.paneName ?? resolvePaneName(options));
  });
  pi.on("session_shutdown", () => {
    // Settle detection (unit-006, EXT-3a): on shutdown, settle dispatched
    // requests this pane owns without a reply — "stopped without a result",
    // never DONE. Pending waits resolve on their next poll; queued follow-up
    // deliveries pick the outcome up at the next delivery probe.
    const paneName = options.paneName ?? resolvePaneName(options);
    settlePendingOnShutdown({ mailboxDir, workerPane: paneName }).catch(() => {
      // Best-effort: if the sweep fails, the request stays pending and
      // remains inspectable (agent_wait timeout path still applies).
    });
    delivery.onSessionShutdown();
  });
}

/** Convenience: resolve another pane's session identity (used by later units). */
export function paneIdentity(mailboxDir, paneName) {
  return resolvePane({ mailboxDir, paneName });
}
