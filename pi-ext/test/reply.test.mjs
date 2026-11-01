// Behavioral tests for pi-extension unit-003 (agent_reply), mapped to
// .todo/specs/issue-42.feature. The mailbox CLI is exercised as a real
// subprocess against a temp store, matching the extension's integration
// boundary (decision 011). Worker identity follows issue#41 EXT-3b: the
// submitting identity must match record.worker exactly.

import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { bindPane } from "../agent-mailbox/identity.mjs";
import { dispatchRequest, runMailbox } from "../agent-mailbox/request.mjs";
import { replyOutcome, ReplyError } from "../agent-mailbox/reply.mjs";

async function setup() {
  const mailboxDir = await mkdtemp(join(tmpdir(), "agent-mailbox-reply-"));
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
 * Claim block (unit-003):
 *   claim id: mailbox-ext-SC-3/3
 *   claim: Reply is persisted with a structured status (MS-3)
 *   scenario: When B calls agent_reply(requestId, status, report) with
 *     status in DONE|NEEDS_INPUT|BLOCKED|FAILED
 *     Then the outcome is persisted via the mailbox service
 *     And A observes the structured outcome with that exact status
 */
test("SC-3/3: worker reply persists a structured outcome matched to record.worker identity", async () => {
  const { mailboxDir, requestId } = await setup();

  const result = await replyOutcome({
    mailboxDir,
    requestId,
    status: "DONE",
    report: "checks pass, 17/17",
    workerPane: "worker-b",
  });

  assert.equal(result.requestId, requestId);
  assert.equal(result.status, "DONE");
  assert.equal(result.workerIdentity, "sess-worker-b");

  const show = await runMailbox({ mailboxDir, args: ["show", "--id", requestId] });
  assert.equal(show.code, 0);
  assert.match(show.stdout, /DONE/);
  assert.match(show.stdout, /checks pass, 17\/17/);

  // Full vocabulary round-trips: each status persists exactly as submitted.
  for (const [i, status] of ["NEEDS_INPUT", "BLOCKED", "FAILED"].entries()) {
    const { requestId: rid } = await dispatchRequest({
      mailboxDir,
      worker: "worker-b",
      instruction: `vocab-${i}`,
      requesterIdentity: "sess-requester-a",
    });
    await replyOutcome({ mailboxDir, requestId: rid, status, workerPane: "worker-b" });
    const show2 = await runMailbox({ mailboxDir, args: ["show", "--id", rid] });
    assert.match(show2.stdout, new RegExp(`\\b${status}\\b`));
  }
});

/**
 * Claim block (unit-003):
 *   claim id: mailbox-ext-EXT-3/EXT-3b
 *   claim: Wrong submitting identity is rejected by the mailbox (EXT-3b)
 *   scenario: When a pane whose session identity differs from
 *     record.worker submits agent_reply for the requestId
 *     Then the mailbox rejects the reply and the extension surfaces the
 *     rejection; the persisted outcome is unchanged
 */
test("EXT-3b: reply from a mismatched worker identity surfaces the mailbox rejection", async () => {
  const { mailboxDir, requestId } = await setup();

  // A different pane with a different session identity tries to answer.
  await bindPane({ mailboxDir, paneName: "impostor-c", sessionId: "sess-impostor-c" });
  await assert.rejects(
    replyOutcome({
      mailboxDir,
      requestId,
      status: "DONE",
      report: "forged",
      workerPane: "impostor-c",
    }),
    (err) => err instanceof ReplyError && err.kind === "rejected" && /does not match/.test(err.message),
  );

  // No outcome bound: reply stays null; the mailbox records the rejection
  // as an attempt (its own semantics), not as an outcome.
  const show = await runMailbox({ mailboxDir, args: ["show", "--id", requestId] });
  assert.equal(show.code, 0);
  assert.match(show.stdout, /"reply": null/);
  assert.match(show.stdout, /sess-impostor-c/);
});

/**
 * Claim block (unit-003):
 *   claim id: mailbox-ext-EXT-3-status
 *   claim: Status outside the vocabulary is rejected (MS-3 vocabulary)
 *   scenario: When B calls agent_reply(requestId, "done") (lowercase, not
 *     in the vocabulary) Then the reply is rejected with the vocabulary
 *     named, and nothing is persisted.
 */
test("status outside the vocabulary is rejected with the vocabulary named", async () => {
  const { mailboxDir, requestId } = await setup();

  await assert.rejects(
    replyOutcome({ mailboxDir, requestId, status: "done", workerPane: "worker-b" }),
    (err) => err instanceof ReplyError && /vocabulary/.test(err.message),
  );

  // No outcome bound: the record's reply stays null and nothing attempted.
  const show = await runMailbox({ mailboxDir, args: ["show", "--id", requestId] });
  assert.match(show.stdout, /"reply": null/);
  assert.doesNotMatch(show.stdout, /"rejectedReplies": \[\s*\{/);
});

/**
 * Claim block (unit-003):
 *   claim id: mailbox-ext-EXT-3-unknown
 *   claim: Reply for an unknown requestId is rejected (not-found)
 *   scenario: When B calls agent_reply(req-does-not-exist, DONE)
 *     Then the call fails with the mailbox's not-found reason.
 */
test("reply for an unknown requestId surfaces the mailbox not-found reason", async () => {
  const { mailboxDir } = await setup();

  await assert.rejects(
    replyOutcome({ mailboxDir, requestId: "req-does-not-exist", status: "DONE", workerPane: "worker-b" }),
    (err) => err instanceof ReplyError && err.kind === "not-found",
  );
});

/**
 * Claim block (unit-003):
 *   claim id: mailbox-ext-EXT-3-unbound
 *   claim: Reply from a pane without a bound identity fails before any
 *     mailbox call (EXT-1a analog: fail fast, nothing mutated)
 *   scenario: When an unbound pane submits agent_reply
 *     Then the call fails with the unbound-pane reason.
 */
test("reply from an unbound pane fails fast with the unbound-pane reason", async () => {
  const { mailboxDir, requestId } = await setup();

  await assert.rejects(
    replyOutcome({ mailboxDir, requestId, status: "DONE", workerPane: "never-started" }),
    (err) => err instanceof ReplyError && /no session identity is bound/.test(err.message),
  );
});
