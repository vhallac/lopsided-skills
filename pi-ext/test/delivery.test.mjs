// Behavioral tests for pi-extension unit-005 (delivery timing), mapped to
// .todo/specs/issue-42.feature. The mailbox CLI is exercised as a real
// subprocess against a temp store (decision 011 integration boundary).
// Delivery semantics: a settled reply that arrives outside agent_wait starts
// exactly one follow-up round attributed to the worker as a custom message
// (MS-4), queued at turn boundaries with no mid-run steering (EXT-4a), and
// duplicate notifications never produce a duplicate continuation (EXT-4b).

import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { bindPane } from "../agent-mailbox/identity.mjs";
import { dispatchRequest, runMailbox } from "../agent-mailbox/request.mjs";
import { replyOutcome } from "../agent-mailbox/reply.mjs";
import {
  probeDeliveries,
  deliveryMessage,
  createDeliveryHooks,
} from "../agent-mailbox/delivery.mjs";

async function setup({ status = "DONE", report = "checks pass, 17/17" } = {}) {
  const mailboxDir = await mkdtemp(join(tmpdir(), "agent-mailbox-delivery-"));
  await bindPane({ mailboxDir, paneName: "worker-b", sessionId: "sess-worker-b" });
  const { requestId } = await dispatchRequest({
    mailboxDir,
    worker: "worker-b",
    instruction: "run the acceptance checks",
    requesterIdentity: "sess-requester-a",
  });
  // B settles while A is idle: the reply is persisted but not delivered —
  // agent_wait never ran, so nothing consumed it yet.
  await replyOutcome({
    mailboxDir,
    requestId,
    status,
    report,
    workerIdentity: "sess-worker-b",
  });
  return { mailboxDir, requestId };
}

/**
 * Claim block (unit-005):
 *   claim id: mailbox-ext-SC-4/4
 *   claim: Reply arrives while requester is idle — follow-up round attributed to B (MS-4)
 *   scenario: Given a request whose reply arrives when A is not blocked in agent_wait
 *     Then the outcome starts exactly one follow-up round in A attributed to B (custom message, never operator-typed text)
 */
test("SC-4/4: idle requester gets exactly one follow-up round attributed to the worker", async () => {
  const { mailboxDir, requestId } = await setup();

  const sent = [];
  const { delivered } = await probeDeliveries({
    mailboxDir,
    requesterIdentity: "sess-requester-a",
    sendMessage: (message, opts) => sent.push({ message, opts }),
  });

  // Exactly one follow-up, attributed to worker B, as a custom message —
  // never a user/operator-typed message.
  assert.equal(delivered.length, 1);
  assert.equal(sent.length, 1);
  const { message, opts } = sent[0];
  assert.equal(message.customType, "agent-mailbox-delivery");
  assert.match(message.content, /Outcome from worker sess-worker-b/);
  assert.match(message.content, new RegExp(`request ${requestId}`));
  assert.match(message.content, /status: DONE/);
  assert.equal(message.details.worker, "sess-worker-b");
  assert.equal(message.details.requestId, requestId);
  assert.equal(message.details.source, "agent-mailbox-delivery");
  assert.deepEqual(opts, { triggerTurn: true });

  // The mailbox marked the reply delivered for our identity.
  const show = await runMailbox({ mailboxDir, args: ["show", "--id", requestId] });
  const record = JSON.parse(show.stdout);
  assert.equal(record.delivered, true);
  assert.equal(record.requester, "sess-requester-a");
});

/**
 * Claim block (unit-005):
 *   claim id: mailbox-ext-EXT-4/EXT-4a
 *   claim: Reply during tool rounds — queued follow-up, no mid-run steering (EXT-4a)
 *   scenario: Given A is executing tool rounds when the reply arrives
 *     Then the reply is queued as a follow-up and starts no mid-run steering
 *     And exactly one delivery occurs
 */
test("EXT-4/EXT-4a: reply during tool rounds queues one follow-up, no mid-run steering", async () => {
  const { mailboxDir, requestId } = await setup();

  // Probes run only at turn boundaries; the reply persisted "during" the run
  // is picked up by the next boundary probe and queued via sendMessage —
  // the message is enqueued for the next turn (triggerTurn), never injected
  // into the running one.
  const sent = [];
  const first = await probeDeliveries({
    mailboxDir,
    requesterIdentity: "sess-requester-a",
    sendMessage: (message, opts) => sent.push({ message, opts }),
  });
  assert.equal(first.delivered.length, 1);
  assert.equal(sent.length, 1);
  assert.deepEqual(sent[0].opts, { triggerTurn: true });

  // Exactly one delivery: a second boundary probe (same seen-set, as one
  // extension instance keeps) delivers nothing further.
  const second = await probeDeliveries({
    mailboxDir,
    requesterIdentity: "sess-requester-a",
    sendMessage: (message) => sent.push({ message }),
    seen: new Set([requestId]),
  });
  assert.equal(second.delivered.length, 0);
  assert.equal(sent.length, 1);

  // And even without a seen-set, the mailbox delivered flag suppresses it.
  const third = await probeDeliveries({
    mailboxDir,
    requesterIdentity: "sess-requester-a",
    sendMessage: (message) => sent.push({ message }),
  });
  assert.equal(third.delivered.length, 0);
  assert.equal(sent.length, 1);
});

/**
 * Claim block (unit-005):
 *   claim id: mailbox-ext-EXT-4/EXT-4b
 *   claim: Duplicate reply notification — no duplicate continuation (EXT-4b)
 *   scenario: Given a reply for a request was already delivered or queued
 *     When a duplicate reply notification arrives
 *     Then A sees no duplicate continuation
 */
test("EXT-4/EXT-4b: duplicate notification and lost-race consume produce no duplicate continuation", async () => {
  const { mailboxDir, requestId } = await setup();

  const sent = [];
  const seen = new Set();

  // First probe delivers and records the request in the seen-set.
  await probeDeliveries({
    mailboxDir,
    requesterIdentity: "sess-requester-a",
    sendMessage: (message) => sent.push(message),
    seen,
  });
  assert.equal(sent.length, 1);

  // Duplicate notification with the same seen-set: no continuation.
  const dup = await probeDeliveries({
    mailboxDir,
    requesterIdentity: "sess-requester-a",
    sendMessage: (message) => sent.push(message),
    seen,
  });
  assert.equal(dup.delivered.length, 0);

  // Lost race: a second extension instance (fresh seen-set) probes, but the
  // mailbox's exactly-once consume means only the winning consume sends a
  // follow-up — the loser's consume output is not a delivery.
  const racer = await probeDeliveries({
    mailboxDir,
    requesterIdentity: "sess-requester-a",
    sendMessage: (message) => sent.push(message),
  });
  assert.equal(racer.delivered.length, 0);
  assert.equal(sent.length, 1);
});

test("delivery probes skip other requesters' replies and unparsable records", async () => {
  // A reply addressed to a different requester is never delivered here.
  const mailboxDir = await mkdtemp(join(tmpdir(), "agent-mailbox-delivery-"));
  await bindPane({ mailboxDir, paneName: "worker-b", sessionId: "sess-worker-b" });
  const { requestId } = await dispatchRequest({
    mailboxDir,
    worker: "worker-b",
    instruction: "other request",
    requesterIdentity: "sess-someone-else",
  });
  await replyOutcome({
    mailboxDir,
    requestId,
    status: "DONE",
    report: "not yours",
    workerIdentity: "sess-worker-b",
  });
  const sent = [];
  const { delivered } = await probeDeliveries({
    mailboxDir,
    requesterIdentity: "sess-requester-a",
    sendMessage: (message) => sent.push(message),
  });
  assert.equal(delivered.length, 0);
  assert.equal(sent.length, 0);
});

test("deliveryMessage shapes the attributed custom message", () => {
  const message = deliveryMessage({
    requestId: "req-1",
    worker: "worker-b",
    reply: { status: "NEEDS_INPUT", report: "need the spec" },
  });
  assert.equal(message.customType, "agent-mailbox-delivery");
  assert.match(message.content, /worker worker-b/);
  assert.match(message.content, /status: NEEDS_INPUT/);
  assert.match(message.content, /need the spec/);
  assert.equal(message.display, true);
  assert.equal(message.details.reply.status, "NEEDS_INPUT");
});

test("createDeliveryHooks wires session lifecycle probes with an idle timer", async () => {
  const { mailboxDir, requestId } = await setup();

  const sent = [];
  const pi = {
    sendMessage: (message, opts) => sent.push({ message, opts }),
  };
  const hooks = createDeliveryHooks(pi, {
    mailboxDir,
    paneName: null,
    requesterIdentity: "sess-requester-a",
    probeMs: 10,
  });

  // Session start probe delivers the pre-persisted reply (idle case) and
  // starts the idle poll timer.
  hooks.onSessionStart(null);
  await new Promise((resolve) => setTimeout(resolve, 300));
  assert.equal(sent.length, 1);
  assert.deepEqual(sent[0].opts, { triggerTurn: true });
  assert.match(sent[0].message.content, new RegExp(requestId));

  // Idle timer probes keep firing but deliver nothing new; shutdown clears.
  hooks.onSessionShutdown();
  const before = sent.length;
  await new Promise((resolve) => setTimeout(resolve, 40));
  assert.equal(sent.length, before);
});

test("createDeliveryHooks guards concurrent probes with a single seen-set", async () => {
  const { mailboxDir } = await setup();

  const sent = [];
  const pi = { sendMessage: (message) => sent.push(message) };
  const hooks = createDeliveryHooks(pi, {
    mailboxDir,
    requesterIdentity: "sess-requester-a",
    probeMs: 0, // no timer; explicit probes only
  });

  // Two overlapping turn_end probes: exactly one continuation total.
  hooks.onTurnEnd(null);
  hooks.onTurnEnd(null);
  await new Promise((resolve) => setTimeout(resolve, 400));
  assert.equal(sent.length, 1);
  hooks.onSessionShutdown();
});
