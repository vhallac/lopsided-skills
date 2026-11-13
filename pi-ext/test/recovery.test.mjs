// Behavioral tests for pi-extension unit-008 (recovery controls), mapped to
// .todo/specs/issue-42.feature. The mailbox CLI is exercised as a real
// subprocess against a temp store (decision 011 integration boundary).
// RC-1: inspect pending requests and undelivered replies; RC-2: pause holds
// delivery (replies become inspectable state), resume delivers; RC-3:
// cancelling a blocked wait returns without a result and the request stays
// pending — the request itself is never cancelled.

import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import agentMailboxExtension, { createTools } from "../agent-mailbox/index.mjs";
import { bindPane } from "../agent-mailbox/identity.mjs";
import { dispatchRequest } from "../agent-mailbox/request.mjs";
import { replyOutcome } from "../agent-mailbox/reply.mjs";
import { runMailbox } from "../agent-mailbox/request.mjs";
import {
  listRecoverable,
  pauseDelivery,
  resumeDelivery,
  cancelWait,
  registerActiveWait,
} from "../agent-mailbox/recovery.mjs";

function fakePi() {
  const registered = [];
  return {
    registered,
    registerTool(tool) {
      registered.push(tool);
    },
    handlers: {},
    on(name, fn) {
      this.handlers[name] = fn;
    },
    sendMessage() {},
  };
}

function toolByName(registered, name) {
  const tool = registered.find((t) => t.name === name);
  assert.ok(tool, `tool ${name} registered`);
  return tool;
}

async function setup() {
  const mailboxDir = await mkdtemp(join(tmpdir(), "agent-mailbox-recovery-"));
  await bindPane({ mailboxDir, paneName: "worker-b", sessionId: "sess-worker-b" });
  const { requestId } = await dispatchRequest({
    mailboxDir,
    worker: "worker-b",
    instruction: "run the acceptance checks",
    requesterIdentity: "sess-requester-a",
  });
  return { mailboxDir, requestId };
}

/**
 * Claim block (unit-008):
 *   claim id: mailbox-ext-RC-1/1
 *   claim: the operator can inspect pending requests and undelivered replies (RC-1)
 *   scenario: Given dispatched requests, some with undelivered replies
 *     When the operator inspects recovery state
 *     Then pending requests and undelivered replies are listed
 */
test("RC-1/1: inspect lists pending requests and undelivered replies", async () => {
  const { mailboxDir, requestId } = await setup();
  // No reply yet: pending, no-reply.
  let records = await listRecoverable({ mailboxDir });
  assert.equal(records.length, 1);
  assert.equal(records[0].requestId, requestId);
  assert.equal(records[0].state, "dispatched");
  assert.equal(records[0].hasReply, false);
  assert.equal(records[0].delivered, false);

  // B replies; the reply is persisted but undelivered — inspectable state.
  await replyOutcome({
    mailboxDir,
    requestId,
    status: "DONE",
    report: "checks pass",
    workerIdentity: "sess-worker-b",
  });
  records = await listRecoverable({ mailboxDir });
  assert.equal(records[0].hasReply, true);
  assert.equal(records[0].replyStatus, "DONE");
  assert.equal(records[0].delivered, false, "reply is persisted but undelivered");

  // After delivery the request leaves the pending-only view.
  await runMailbox({
    mailboxDir,
    args: ["consume", "--id", requestId, "--requester", "sess-requester-a"],
  });
  records = await listRecoverable({ mailboxDir, pendingOnly: true });
  assert.equal(records.length, 0, "delivered request is no longer pending");
});

/**
 * Claim block (unit-008):
 *   claim id: mailbox-ext-RC-2/2
 *   claim: paused delivery holds replies as inspectable state; resume delivers (RC-2)
 *   scenario: Given delivery is paused
 *     When a reply arrives
 *     Then it becomes inspectable state and is not delivered
 *     And after resume, pending replies deliver
 */
test("RC-2/2: pause holds delivery as inspectable state; resume delivers", async () => {
  const { mailboxDir, requestId } = await setup();
  const deliveries = [];
  const sendMessage = (message) => deliveries.push(message);

  // Pause BEFORE the reply arrives.
  const pauseResult = await pauseDelivery({ mailboxDir, requestId });
  assert.match(pauseResult.message, /^paused /);

  // Reply arrives while paused; a delivery probe must NOT deliver it.
  await replyOutcome({
    mailboxDir,
    requestId,
    status: "DONE",
    report: "held checks pass",
    workerIdentity: "sess-worker-b",
  });
  const { probeDeliveries } = await import("../agent-mailbox/delivery.mjs");
  await probeDeliveries({ mailboxDir, requesterIdentity: "sess-requester-a", sendMessage });
  assert.equal(deliveries.length, 0, "no follow-up delivered while paused");

  // The reply is inspectable state (show returns it; nothing consumed).
  const shown = await runMailbox({ mailboxDir, args: ["show", "--id", requestId] });
  const held = JSON.parse(shown.stdout);
  assert.equal(held.reply?.report, "held checks pass");
  assert.equal(held.delivered, false, "reply stays persisted, undelivered");

  // Resume: the pending reply delivers on the next probe.
  const resumeResult = await resumeDelivery({ mailboxDir, requestId });
  assert.match(resumeResult.message, /^resumed /);
  const { delivered } = await probeDeliveries({
    mailboxDir,
    requesterIdentity: "sess-requester-a",
    sendMessage,
  });
  assert.equal(delivered.length, 1);
  assert.equal(deliveries.length, 1, "exactly one follow-up after resume");
});

/**
 * Claim block (unit-008):
 *   claim id: mailbox-ext-RC-3/3
 *   claim: cancelling a blocked wait loses neither the reply nor the request (RC-3)
 *   scenario: Given A is blocked in agent_wait
 *     When A cancels the blocked wait
 *     Then the wait returns without a result
 *     And the request stays pending and can still be waited on later
 */
test("RC-3/3: cancel aborts the blocked wait; the request stays pending", async () => {
  const { mailboxDir, requestId } = await setup();

  // Cancel a registered active wait (as agent_cancel does against the
  // in-process registry): the poll loop observes the abort and returns
  // without a result.
  const controller = new AbortController();
  registerActiveWait(requestId, controller);
  const waitPromise = (await import("../agent-mailbox/wait.mjs")).waitForOutcome({
    mailboxDir,
    requestId,
    requesterIdentity: "sess-requester-a",
    timeoutMs: 5_000,
    pollMs: 20,
    signal: controller.signal,
  });
  const cancelled = cancelWait(requestId);
  assert.equal(cancelled.cancelled, true, "an active wait was aborted");
  const result = await waitPromise;
  assert.equal(result.status, "cancelled");
  assert.equal(result.reply, undefined, "no result returned");

  // The request itself is untouched: not cancelled, still pending, and a
  // later wait still receives the outcome (EXT-4c unchanged).
  const shown = await runMailbox({ mailboxDir, args: ["show", "--id", requestId] });
  const record = JSON.parse(shown.stdout);
  assert.equal(record.state, "dispatched", "request NOT cancelled by the wait cancel");
  assert.equal(record.reply, null, "nothing was consumed");

  await replyOutcome({
    mailboxDir,
    requestId,
    status: "DONE",
    report: "delivered after cancel",
    workerIdentity: "sess-worker-b",
  });
  const later = await (await import("../agent-mailbox/wait.mjs")).waitForOutcome({
    mailboxDir,
    requestId,
    requesterIdentity: "sess-requester-a",
    timeoutMs: 5_000,
    pollMs: 20,
  });
  assert.equal(later.status, "outcome");
  assert.equal(later.reply.report, "delivered after cancel");
});

test("cancel with no active wait is a clean no-op; the request stays pending", async () => {
  const { mailboxDir, requestId } = await setup();
  const result = cancelWait(requestId);
  assert.deepEqual(result, { cancelled: false, hadActiveWait: false });
  // The record still exists and is not cancelled.
  const shown = await runMailbox({ mailboxDir, args: ["show", "--id", requestId] });
  assert.equal(JSON.parse(shown.stdout).state, "dispatched");
});

test("cancel does NOT use mailbox cancel (the request must survive)", async () => {
  const { mailboxDir, requestId } = await setup();
  const controller = new AbortController();
  registerActiveWait(requestId, controller);
  controller.abort();
  cancelWait(requestId);
  // `mailbox show` must still find the request (a mailbox-side cancel would
  // have renamed it to <id>.cancelled.<ts>.json).
  const shown = await runMailbox({ mailboxDir, args: ["show", "--id", requestId] });
  assert.equal(shown.code, 0);
});

// Tool-level wiring: the four recovery tools are registered and behave.
test("recovery tools registered: agent_list, agent_pause, agent_resume, agent_cancel", () => {
  const pi = fakePi();
  agentMailboxExtension(pi, { mailboxDir: "/unused" });
  for (const name of ["agent_list", "agent_pause", "agent_resume", "agent_cancel"]) {
    assert.ok(pi.registered.find((t) => t.name === name), `${name} registered`);
  }
});

test("agent_list tool lists pending requests (RC-1 at tool level)", async () => {
  const { mailboxDir, requestId } = await setup();
  const pi = fakePi();
  agentMailboxExtension(pi, { mailboxDir });
  const tool = toolByName(pi.registered, "agent_list");
  const result = await tool.execute("call-1", { pendingOnly: true });
  assert.match(result.content[0].text, new RegExp(requestId));
  assert.match(result.content[0].text, /no-reply/);
});

test("agent_pause/agent_resume tool round-trip holds then releases a reply (RC-2)", async () => {
  const { mailboxDir, requestId } = await setup();
  const pi = fakePi();
  agentMailboxExtension(pi, { mailboxDir });
  const pause = toolByName(pi.registered, "agent_pause");
  const resume = toolByName(pi.registered, "agent_resume");

  const paused = await pause.execute("call-1", { requestId });
  assert.match(paused.content[0].text, /held as inspectable state/);

  await replyOutcome({
    mailboxDir,
    requestId,
    status: "DONE",
    report: "tool-level hold",
    workerIdentity: "sess-worker-b",
  });
  const shown1 = JSON.parse((await runMailbox({ mailboxDir, args: ["show", "--id", requestId] })).stdout);
  assert.equal(shown1.delivered, false, "held while paused");

  const resumed = await resume.execute("call-2", { requestId });
  assert.match(resumed.content[0].text, /delivers on the next wait or delivery probe/);

  // After resume a wait delivers the outcome.
  const { waitForOutcome } = await import("../agent-mailbox/wait.mjs");
  const outcome = await waitForOutcome({
    mailboxDir,
    requestId,
    requesterIdentity: "sess-requester-a",
    timeoutMs: 5_000,
    pollMs: 20,
  });
  assert.equal(outcome.status, "outcome");
  assert.equal(outcome.reply.report, "tool-level hold");
});

test("agent_cancel tool aborts a blocked agent_wait; the request survives (RC-3)", async () => {
  const { mailboxDir, requestId } = await setup();
  const pi = fakePi();
  agentMailboxExtension(pi, { mailboxDir, requesterIdentity: "sess-requester-a" });
  const wait = toolByName(pi.registered, "agent_wait");
  const cancel = toolByName(pi.registered, "agent_cancel");

  const waitPromise = wait.execute("call-1", { requestId, timeoutMs: 10_000 });
  // The wait registers its AbortController synchronously before its first
  // poll; give the event loop a tick, then cancel.
  await new Promise((resolve) => setImmediate(resolve));
  const cancelResult = await cancel.execute("call-2", { requestId });
  assert.match(cancelResult.content[0].text, /stays pending and can be waited on later/);

  const waitResult = await waitPromise;
  assert.equal(waitResult.details.status, "cancelled", "wait returned without a result");

  // The request stays pending: still showable, not renamed to .cancelled.
  const shown = await runMailbox({ mailboxDir, args: ["show", "--id", requestId] });
  assert.equal(shown.code, 0);
  assert.equal(JSON.parse(shown.stdout).state, "dispatched");

  // A later wait still receives the outcome.
  await replyOutcome({
    mailboxDir,
    requestId,
    status: "DONE",
    report: "post-cancel outcome",
    workerIdentity: "sess-worker-b",
  });
  const later = await toolByName(pi.registered, "agent_wait").execute("call-3", {
    requestId,
    timeoutMs: 5_000,
  });
  assert.equal(later.details.status, "outcome");
  assert.match(later.content[0].text, /post-cancel outcome/);
});

test("agent_cancel with no blocked wait is a clean no-op", async () => {
  const { requestId } = await setup();
  const tool = toolByName(createTools({}), "agent_cancel");
  const result = await tool.execute("call-1", { requestId });
  assert.match(result.content[0].text, /nothing to cancel/);
  assert.equal(result.details.cancelled, false);
});

test("agent_list surfaces mailbox failures as tool errors", async () => {
  // The extension now defaults to the CLI store, so force a store failure
  // with a path whose parent is a regular file (ENOTDIR).
  const root = await mkdtemp(join(tmpdir(), "agent-mailbox-bad-store-"));
  const file = join(root, "not-a-dir");
  await writeFile(file, "");
  const tool = toolByName(createTools({ mailboxDir: join(file, "store") }), "agent_list");
  const result = await tool.execute("call-1", {});
  assert.equal(result.details.error, true);
});
