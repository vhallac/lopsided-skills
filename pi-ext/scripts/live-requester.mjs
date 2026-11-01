// Live requester harness for unit-009 (issue#42 live acceptance, two herdr
// panes). Runs in the requester pane A with AGENT_PANE (or HERDR_PANE_ID) and
// MAILBOX_DIR set. Drives the six #40 acceptance checks against the worker
// pane B (identified via LIVE_WORKER_PANE) using the REAL extension code:
// createTools executes (the same executes pi registers), the real mailbox CLI
// subprocess, and the real delivery probe (probeDeliveries) with a captured
// sendMessage standing in for pi.sendMessage.
//
// Claim blocks (unit-009, ACC scenario outline of .todo/specs/issue-42.feature):
//   claim id: mailbox-ext-ACC/reply-before-wait
//   claim: A reply persisted before A waits is returned immediately by agent_wait
//   scenario: Given a dispatched request whose reply B persisted first
//     When pane A calls agent_wait
//     Then the outcome is returned immediately
//
//   claim id: mailbox-ext-ACC/reply-during-tool-rounds
//   claim: A reply arriving during A's tool rounds is queued, not steered, and
//     delivered as exactly one attributed follow-up at the next boundary
//   scenario: Given a dispatched request whose reply arrives while A is busy
//     When A's turn boundary probe runs
//     Then exactly one follow-up attributed to B is delivered, none mid-run
//
//   claim id: mailbox-ext-ACC/blocked-wait-released
//   claim: A blocked agent_wait is released by the worker's reply
//   scenario: Given a blocking agent_wait with no outcome yet
//     When B replies
//     Then the wait returns the outcome
//
//   claim id: mailbox-ext-ACC/duplicate-notification
//   claim: A already-delivered reply never produces a second notification
//   scenario: Given a reply already delivered once
//     When the delivery probe runs again
//     Then no further follow-up is sent
//
//   claim id: mailbox-ext-ACC/worker-stops-without-replying
//   claim: A worker settling without agent_reply resolves the wait explicitly
//     as stopped-without-a-result, never DONE
//   scenario: Given a dispatched request the worker never replied to
//     When the worker session settles
//     Then the wait resolves FAILED with "stopped without a result"
//
//   claim id: mailbox-ext-ACC/session-restart-replacement
//   claim: A replacement session never receives the old session's pending
//     replies until an explicit rebind delivers them (EXT-4d / RC-4)
//   scenario: Given a pending reply addressed to the replaced session
//     When the pane's session is replaced and agent_rebind runs
//     Then no delivery before the rebind and exactly one after
import { randomUUID } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";

import { bindPane, resolvePane } from "../agent-mailbox/identity.mjs";
import { recordReplacement } from "../agent-mailbox/rebind.mjs";
import { probeDeliveries } from "../agent-mailbox/delivery.mjs";
import { createTools } from "../agent-mailbox/index.mjs";
import { STOPPED_REPORT } from "../agent-mailbox/settle.mjs";

const mailboxDir = process.env.MAILBOX_DIR;
const paneName = process.env.AGENT_PANE ?? process.env.HERDR_PANE_ID ?? null;
const workerPane = process.env.LIVE_WORKER_PANE ?? null;
if (!mailboxDir || !paneName || !workerPane) {
  console.error("LIVE-REQUESTER-FATAL: MAILBOX_DIR, AGENT_PANE/HERDR_PANE_ID, LIVE_WORKER_PANE required");
  process.exit(2);
}
const syncDir = join(mailboxDir, "ext", "acc-sync");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function awaitSync(name, timeoutMs = 30000) {
  const path = join(syncDir, name);
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    try {
      return await readFile(path, "utf8");
    } catch {
      if (Date.now() >= deadline) throw new Error(`sync file ${name} never appeared`);
      await sleep(100);
    }
  }
}

// --- harness setup: bind pane A like the extension's session_start does ---
const sessionId = `requester-${randomUUID()}`;
await bindPane({ mailboxDir, paneName, sessionId });

// Wait until the worker pane's session_start binding is visible — the worker
// process is started in parallel in its own herdr pane.
{
  const deadline = Date.now() + 30000;
  for (;;) {
    const binding = await resolvePane({ mailboxDir, paneName: workerPane });
    if (binding?.sessionId) break;
    if (Date.now() >= deadline) throw new Error(`worker pane ${workerPane} never bound a session identity`);
    await sleep(100);
  }
}

const tools = Object.fromEntries(createTools({ mailboxDir, paneName }).map((t) => [t.name, t]));
async function callTool(name, params) {
  const result = await tools[name].execute("live-call", params);
  if (result.details?.error) throw new Error(`${name} failed: ${result.details.reason}`);
  return result.details ?? {};
}

// Captured sendMessage stand-in for pi.sendMessage — records every follow-up
// the delivery layer would start.
const messages = [];
const sendMessage = (message, opts) => messages.push({ message, opts, at: Date.now() });

const seen = new Set();
let requesterIdentity = sessionId;
const probe = () =>
  probeDeliveries({ mailboxDir, requesterIdentity, seen, sendMessage });

let failures = 0;
function check(name, ok, detail = "") {
  if (ok) {
    console.log(`ACC-PASS ${name}${detail ? ` :: ${detail}` : ""}`);
  } else {
    failures += 1;
    console.log(`ACC-FAIL ${name}${detail ? ` :: ${detail}` : ""}`);
  }
}

async function request(instruction) {
  const details = await callTool("agent_request", { worker: workerPane, instruction });
  return details.requestId;
}

/** Dispatch and wait until B's reply is persisted; returns { requestId, replyAt }. */
async function requestAndAwaitReply(instruction) {
  const requestId = await request(instruction);
  const replyAt = Date.now();
  await awaitSync(`replied-${requestId}`);
  return { requestId, replyAt };
}

// --- ACC check 1: reply before wait -----------------------------------------
{
  const { requestId } = await requestAndAwaitReply("LIVE-CHECK-1 reply before wait");
  const t0 = Date.now();
  const details = await callTool("agent_wait", { requestId, timeoutMs: 15000 });
  check(
    "reply-before-wait",
    details.status === "outcome" && details.reply?.status === "DONE",
    `status=${details.status} reply=${details.reply?.status} waited=${Date.now() - t0}ms`,
  );
}

// --- ACC check 2: reply during tool rounds ----------------------------------
{
  const requestId = await request("LIVE-CHECK-2 reply during tool rounds");
  // Busy "tool rounds": the extension never probes mid-run, so no delivery
  // may be sent while this window is open. B's reply lands inside it.
  await sleep(500); // B's poll interval is 150ms — the reply persists mid-busy
  const replyAt = await awaitSync(`replied-${requestId}`).then(() => Date.now());
  await sleep(300);
  const busyEnd = Date.now();
  check("reply-during-tool-rounds/no-mid-run-steering", messages.length === 0,
    `reply persisted at ${replyAt}, busy until ${busyEnd}, messages=${messages.length}`);
  const { delivered } = await probe();
  const ok =
    delivered.length === 1 &&
    delivered[0].requestId === requestId &&
    messages.length === 1 &&
    messages[0].opts?.triggerTurn === true &&
    messages[0].message.details?.worker !== undefined &&
    messages[0].at >= busyEnd;
  check("reply-during-tool-rounds", ok,
    `delivered=${delivered.map((d) => d.requestId)} messages=${messages.length}`);
}

// --- ACC check 3: blocked wait released by reply ----------------------------
{
  const requestId = await request("LIVE-CHECK-3 blocked wait released");
  const t0 = Date.now();
  const details = await callTool("agent_wait", { requestId, timeoutMs: 20000 });
  check(
    "blocked-wait-released",
    details.status === "outcome" && details.reply?.status === "DONE",
    `status=${details.status} waited=${Date.now() - t0}ms`,
  );
}

// --- ACC check 4: duplicate notification suppressed -------------------------
{
  const before = messages.length;
  const { delivered } = await probe();
  check(
    "duplicate-notification",
    delivered.length === 0 && messages.length === before,
    `delivered=${delivered.length} messages=${before}->${messages.length}`,
  );
}

// --- ACC check 5: worker stops without replying -----------------------------
{
  const requestId = await request("LIVE-CHECK-5 LIVE-SETTLE worker stops without replying");
  await awaitSync(`settled-${requestId}`);
  const details = await callTool("agent_wait", { requestId, timeoutMs: 15000 });
  check(
    "worker-stops-without-replying",
    details.status === "outcome" &&
      details.reply?.status === "FAILED" &&
      (details.reply?.report ?? "").startsWith("stopped without a result"),
    `status=${details.status} reply=${details.reply?.status} report=${details.reply?.report}`,
  );
}

// --- ACC check 6: session restart / replacement -----------------------------
{
  const requestId = await request("LIVE-CHECK-6 session restart/replacement");
  await awaitSync(`replied-${requestId}`);
  const workerBinding = await resolvePane({ mailboxDir, paneName: workerPane });

  // The pane's session is replaced: a new session rebinds the pane name at
  // session_start and records the replacement (extension session_start path).
  const replacementId = `requester-${randomUUID()}`;
  await recordReplacement({
    mailboxDir,
    paneName,
    fromSessionId: sessionId,
    toSessionId: replacementId,
  });
  await bindPane({ mailboxDir, paneName, sessionId: replacementId });
  requesterIdentity = replacementId;

  // EXT-4d: before an explicit rebind the replacement must NOT receive the
  // old session's pending reply.
  const before = messages.length;
  const p1 = await probe();
  check(
    "session-restart-replacement/no-delivery-before-rebind",
    p1.delivered.length === 0 && messages.length === before,
    `delivered=${p1.delivered.length} messages=${before}->${messages.length}`,
  );

  // RC-4: explicit rebind delivers the pending reply to the replacement.
  await callTool("agent_rebind", {});
  const p2 = await probe();
  const ok =
    p2.delivered.length === 1 &&
    p2.delivered[0].requestId === requestId &&
    messages.length === before + 1 &&
    messages[before].message.details?.worker === workerBinding?.sessionId;
  check(
    "session-restart-replacement",
    ok,
    `delivered=${p2.delivered.map((d) => d.requestId)} worker=${workerBinding?.sessionId}`,
  );
}

await mkdir(syncDir, { recursive: true });
if (failures === 0) {
  await writeFile(join(syncDir, "requester-done"), "ALL-PASS");
  console.log("LIVE-ALL-PASS");
} else {
  await writeFile(join(syncDir, "requester-done"), `${failures} FAILURES`);
  console.log(`LIVE-ALL-FAIL failures=${failures}`);
  process.exit(1);
}
