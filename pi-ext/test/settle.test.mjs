// Behavioral tests for pi-extension unit-006 (settle-without-reply-detection),
// mapped to .todo/specs/issue-42.feature. The mailbox CLI is exercised as a
// real subprocess against a temp store (decision 011 integration boundary).
// Settle semantics: a worker session that settles without agent_reply resolves
// pending waits and queued follow-ups with an explicit "stopped without a
// result" outcome — never DONE — and the request stays inspectable (EXT-3a).

import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { bindPane } from "../agent-mailbox/identity.mjs";
import { dispatchRequest, runMailbox } from "../agent-mailbox/request.mjs";
import { replyOutcome } from "../agent-mailbox/reply.mjs";
import { settlePendingOnShutdown, STOPPED_REPORT } from "../agent-mailbox/settle.mjs";
import { waitForOutcome } from "../agent-mailbox/wait.mjs";
import { probeDeliveries } from "../agent-mailbox/delivery.mjs";

async function setup() {
  const mailboxDir = await mkdtemp(join(tmpdir(), "agent-mailbox-settle-"));
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
 * Claim block (unit-006):
 *   claim id: mailbox-ext-EXT-3/EXT-3a
 *   claim: worker settles without replying — never a false DONE (EXT-3a)
 *   scenario: Given a dispatched request whose worker session settles without
 *     calling agent_reply
 *     When A waits for the outcome
 *     Then the wait resolves with an explicit "stopped without a result"
 *     And the outcome status is not DONE
 */
test("EXT-3/EXT-3a: worker settle without reply resolves the pending wait with 'stopped without a result', never DONE", async () => {
  const { mailboxDir, requestId } = await setup();

  // The worker pane's session ends without agent_reply; its extension sweeps
  // the mailbox on session_shutdown.
  const { settled } = await settlePendingOnShutdown({
    mailboxDir,
    workerPane: "worker-b",
  });
  assert.deepEqual(settled, [requestId]);

  // A waits afterwards: the outcome is persisted, explicit, and not DONE.
  const result = await waitForOutcome({
    mailboxDir,
    requestId,
    requesterIdentity: "sess-requester-a",
    timeoutMs: 5_000,
    pollMs: 20,
  });
  assert.equal(result.status, "outcome");
  assert.equal(result.reply.status, "FAILED");
  assert.notEqual(result.reply.status, "DONE");
  assert.match(result.reply.report, /stopped without a result/);
});

test("EXT-3/EXT-3a: a wait already blocked when the worker settles resolves on the settle sweep", async () => {
  const { mailboxDir, requestId } = await setup();

  // A is blocked in its poll loop when B's session shuts down mid-wait.
  let polls = 0;
  const waitPromise = waitForOutcome({
    mailboxDir,
    requestId,
    requesterIdentity: "sess-requester-a",
    timeoutMs: 5_000,
    pollMs: 20,
    sleepImpl: async () => {
      polls += 1;
      if (polls === 2) {
        await settlePendingOnShutdown({ mailboxDir, workerPane: "worker-b" });
      }
    },
  });
  const result = await waitPromise;
  assert.equal(result.status, "outcome");
  assert.equal(result.reply.status, "FAILED");
  assert.match(result.reply.report, /stopped without a result/);
  assert.ok(polls >= 2);
});

test("EXT-3/EXT-3a: a queued follow-up delivery surfaces the stopped-without-result outcome", async () => {
  const { mailboxDir, requestId } = await setup();
  await settlePendingOnShutdown({ mailboxDir, workerPane: "worker-b" });

  const sent = [];
  const { delivered } = await probeDeliveries({
    mailboxDir,
    requesterIdentity: "sess-requester-a",
    sendMessage: (message) => sent.push(message),
  });
  assert.equal(delivered.length, 1);
  assert.equal(delivered[0].requestId, requestId);
  assert.equal(sent.length, 1);
  assert.equal(sent[0].customType, "agent-mailbox-delivery");
  assert.match(sent[0].content, /stopped without a result/);
  assert.match(sent[0].content, /FAILED/);
});

test("settle sweep touches only this worker's unreplied requests and is idempotent", async () => {
  const { mailboxDir, requestId } = await setup();

  // A second request, already replied DONE by the same worker.
  const { requestId: repliedId } = await dispatchRequest({
    mailboxDir,
    worker: "worker-b",
    instruction: "already handled",
    requesterIdentity: "sess-requester-a",
  });
  await replyOutcome({
    mailboxDir,
    requestId: repliedId,
    status: "DONE",
    report: "done earlier",
    workerIdentity: "sess-worker-b",
  });

  // A third request owned by a different worker session.
  await bindPane({ mailboxDir, paneName: "worker-c", sessionId: "sess-worker-c" });
  const { requestId: otherId } = await dispatchRequest({
    mailboxDir,
    worker: "worker-c",
    instruction: "not mine",
    requesterIdentity: "sess-requester-a",
  });

  const { settled } = await settlePendingOnShutdown({
    mailboxDir,
    workerPane: "worker-b",
  });
  assert.deepEqual(settled, [requestId]);

  // Replied request keeps its DONE outcome; other worker's request untouched.
  const shownReplied = JSON.parse(
    (await runMailbox({ mailboxDir, args: ["show", "--id", repliedId] })).stdout,
  );
  assert.equal(shownReplied.reply.status, "DONE");
  const shownOther = JSON.parse(
    (await runMailbox({ mailboxDir, args: ["show", "--id", otherId] })).stdout,
  );
  assert.equal(shownOther.reply, null);

  // Idempotent: a second sweep settles nothing new; the first outcome stands.
  const second = await settlePendingOnShutdown({ mailboxDir, workerPane: "worker-b" });
  assert.deepEqual(second.settled, []);
  const shown = JSON.parse(
    (await runMailbox({ mailboxDir, args: ["show", "--id", requestId] })).stdout,
  );
  assert.equal(shown.reply.report, STOPPED_REPORT);
});

test("settle sweep with no bound identity or empty mailbox settles nothing", async () => {
  const mailboxDir = await mkdtemp(join(tmpdir(), "agent-mailbox-settle-empty-"));
  const none = await settlePendingOnShutdown({ mailboxDir, workerPane: "nobody" });
  assert.deepEqual(none.settled, []);
  const noDir = await settlePendingOnShutdown({ mailboxDir: "", workerPane: "worker-b" });
  assert.deepEqual(noDir.settled, []);
});
