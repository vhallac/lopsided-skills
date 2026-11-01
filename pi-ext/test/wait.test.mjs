// Behavioral tests for pi-extension unit-004 (agent_wait), mapped to
// .todo/specs/issue-42.feature. The mailbox CLI is exercised as a real
// subprocess against a temp store (decision 011 integration boundary).
// Wait semantics: block without LLM rounds (MS-2), immediate return on an
// already-persisted outcome (EXT-2a), timeout without consuming (EXT-4c).

import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { bindPane } from "../agent-mailbox/identity.mjs";
import { dispatchRequest, runMailbox } from "../agent-mailbox/request.mjs";
import { replyOutcome } from "../agent-mailbox/reply.mjs";
import { waitForOutcome, WaitError, resolveRequesterIdentity } from "../agent-mailbox/wait.mjs";

async function setup() {
  const mailboxDir = await mkdtemp(join(tmpdir(), "agent-mailbox-wait-"));
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
 * Claim block (unit-004):
 *   claim id: mailbox-ext-SC-2/2
 *   claim: agent_wait blocks without polling the LLM (MS-2)
 *   scenario: Given a dispatched request with no outcome yet
 *     When pane A calls agent_wait(requestId, timeout)
 *     Then the call blocks without consuming LLM rounds
 *     And when B replies, the wait returns the outcome
 */
/**
 * Claim block (R1.F3):
 *   claim id: mailbox-ext-SC-5/5
 *   claim: A observes the structured outcome (DONE | NEEDS_INPUT | BLOCKED | FAILED)
 *     and proceeds
 *   scenario: Given a dispatched request whose worker persisted a reply with a
 *     structured status
 *     When A calls agent_wait and the outcome is observed
 *     Then the wait returns the outcome carrying exactly that status and report
 */
test("SC-2/2: wait blocks via in-extension poll loop and returns the outcome when B replies", async () => {
  const { mailboxDir, requestId } = await setup();

  // In-extension blocking primitive: bounded subprocess poll loop (sleeps),
  // never an LLM round. B replies mid-wait; the wait observes it.
  let polls = 0;
  const result = await waitForOutcome({
    mailboxDir,
    requestId,
    requesterIdentity: "sess-requester-a",
    timeoutMs: 5_000,
    pollMs: 20,
    sleepImpl: async () => {
      polls += 1;
      if (polls === 2) {
        await replyOutcome({
          mailboxDir,
          requestId,
          status: "DONE",
          report: "checks pass, 17/17",
          workerIdentity: "sess-worker-b",
        });
      }
    },
  });

  assert.equal(result.status, "outcome");
  assert.equal(result.reply.status, "DONE");
  assert.equal(result.reply.report, "checks pass, 17/17");

  // Exactly-once delivery via consume: the record is marked delivered.
  const show = await runMailbox({ mailboxDir, args: ["show", "--id", requestId] });
  const record = JSON.parse(show.stdout);
  assert.equal(record.delivered, true);
  assert.equal(record.deliveryAttempts.at(-1).requester, "sess-requester-a");
});

/**
 * Claim block (unit-004):
 *   claim id: mailbox-ext-EXT-2/EXT-2a
 *   claim: Reply before wait returns immediately (EXT-2a)
 *   scenario: Given B replied before A called agent_wait
 *     When A calls agent_wait(requestId, timeout)
 *     Then the wait returns immediately with the already-persisted outcome
 */
test("EXT-2/EXT-2a: outcome persisted before the wait returns immediately, first probe", async () => {
  const { mailboxDir, requestId } = await setup();
  await replyOutcome({
    mailboxDir,
    requestId,
    status: "NEEDS_INPUT",
    report: "need the OAS file path",
    workerIdentity: "sess-worker-b",
  });

  let probes = 0;
  const result = await waitForOutcome({
    mailboxDir,
    requestId,
    requesterIdentity: "sess-requester-a",
    timeoutMs: 5_000,
    pollMs: 20,
    sleepImpl: async () => {
      probes += 1;
      assert.fail("EXT-2a: no sleep must occur when the outcome is already persisted");
    },
    nowImpl: (() => {
      let t = 0;
      return () => (probes === 0 ? t : t);
    })(),
  });

  assert.equal(result.status, "outcome");
  assert.equal(result.reply.status, "NEEDS_INPUT");
  assert.equal(result.delivered, false); // not yet delivered when first seen
});

/**
 * Claim block (unit-004):
 *   claim id: mailbox-ext-EXT-4/EXT-4c
 *   claim: Wait timeout leaves the request pending (EXT-4c)
 *   scenario: When agent_wait(requestId, timeout) times out with no reply
 *     persisted
 *     Then the call returns "no outcome yet" without consuming the reply
 *     And the request stays pending and a later wait still receives the
 *     outcome
 */
test("EXT-4/EXT-4c: timeout returns no-outcome without consuming; a later wait still gets the outcome", async () => {
  const { mailboxDir, requestId } = await setup();

  const timedOut = await waitForOutcome({
    mailboxDir,
    requestId,
    requesterIdentity: "sess-requester-a",
    timeoutMs: 60,
    pollMs: 20,
  });
  assert.equal(timedOut.status, "timeout");

  // No consume happened: the record is still undelivered and reply-less.
  let show = await runMailbox({ mailboxDir, args: ["show", "--id", requestId] });
  let record = JSON.parse(show.stdout);
  assert.equal(record.reply, null);
  assert.equal(record.delivered, false);
  assert.deepEqual(record.deliveryAttempts, []);

  // Later, B replies; the subsequent wait still receives the outcome.
  await replyOutcome({
    mailboxDir,
    requestId,
    status: "DONE",
    report: "late but delivered",
    workerIdentity: "sess-worker-b",
  });
  const second = await waitForOutcome({
    mailboxDir,
    requestId,
    requesterIdentity: "sess-requester-a",
    timeoutMs: 5_000,
    pollMs: 20,
  });
  assert.equal(second.status, "outcome");
  assert.equal(second.reply.report, "late but delivered");
});

test("wait consumes exactly once: repeated waits on the same delivered outcome are a mailbox no-op", async () => {
  const { mailboxDir, requestId } = await setup();
  await replyOutcome({
    mailboxDir,
    requestId,
    status: "FAILED",
    report: "boom",
    workerIdentity: "sess-worker-b",
  });

  const first = await waitForOutcome({
    mailboxDir,
    requestId,
    requesterIdentity: "sess-requester-a",
    timeoutMs: 5_000,
  });
  assert.equal(first.reply.status, "FAILED");

  const second = await waitForOutcome({
    mailboxDir,
    requestId,
    requesterIdentity: "sess-requester-a",
    timeoutMs: 5_000,
  });
  assert.equal(second.reply.status, "FAILED");
  assert.equal(second.delivered, true);

  const show = await runMailbox({ mailboxDir, args: ["show", "--id", requestId] });
  const record = JSON.parse(show.stdout);
  const deliveries = record.deliveryAttempts.filter((a) => a.result === "delivered");
  assert.equal(deliveries.length, 1); // exactly-once delivery, no duplicates
});

test("wait on an unknown requestId surfaces the mailbox not-found rejection", async () => {
  const mailboxDir = await mkdtemp(join(tmpdir(), "agent-mailbox-wait-"));
  await assert.rejects(
    waitForOutcome({
      mailboxDir,
      requestId: "req-unknown",
      requesterIdentity: "sess-requester-a",
      timeoutMs: 100,
    }),
    (err) => err instanceof WaitError && err.kind === "not-found",
  );
});

// R1.F2: anonymous fail-fast — no pane name, or a pane without a bound
// session identity, rejects instead of proceeding as "anonymous".
test("resolveRequesterIdentity fails fast for unbound panes", async () => {
  const mailboxDir = await mkdtemp(join(tmpdir(), "agent-mailbox-wait-"));
  await assert.rejects(
    resolveRequesterIdentity({ mailboxDir, paneName: null }),
    (err) => err instanceof WaitError && /no pane name/.test(err.message),
  );
  await assert.rejects(
    resolveRequesterIdentity({ mailboxDir, paneName: "nobody" }),
    (err) =>
      err instanceof WaitError &&
      /pane "nobody" has no bound session identity/.test(err.message),
  );
  await bindPane({ mailboxDir, paneName: "pane-a", sessionId: "sess-a" });
  assert.equal(
    await resolveRequesterIdentity({ mailboxDir, paneName: "pane-a" }),
    "sess-a",
  );
});
