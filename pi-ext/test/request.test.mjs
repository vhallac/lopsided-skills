// Behavioral tests for pi-extension unit-002 (agent_request dispatch),
// mapped to .todo/specs/issue-42.feature. The mailbox CLI is exercised as a
// real subprocess against a temp store, matching the extension's integration
// boundary (decision 011).

import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { bindPane } from "../agent-mailbox/identity.mjs";
import {
  dispatchRequest,
  runMailbox,
  MAILBOX_CLI,
  RequestError,
  MAILBOX_CHILD_TIMEOUT_MS,
} from "../agent-mailbox/request.mjs";

/**
 * Claim block (unit-002):
 *   claim id: mailbox-ext-SC-1/1
 *   claim: Request dispatch returns a requestId immediately (MS-1)
 *   scenario: When pane A calls agent_request(to=B, instruction=instr)
 *     Then the extension registers the reply route, dispatches the
 *     instruction to B with its reply obligation attached
 *     And agent_request returns a requestId immediately
 */
test("SC-1/1: dispatch to a bound worker pane registers + dispatches and returns the requestId immediately", async () => {
  const mailboxDir = await mkdtemp(join(tmpdir(), "agent-mailbox-req-"));
  await bindPane({ mailboxDir, paneName: "worker-b", sessionId: "sess-worker-b" });

  const { requestId, worker } = await dispatchRequest({
    mailboxDir,
    worker: "worker-b",
    instruction: "run the acceptance checks",
    requesterIdentity: "sess-requester-a",
  });

  assert.match(requestId, /^req-/);
  assert.equal(worker, "sess-worker-b");

  // The store record exists, is dispatched, and carries the reply obligation
  // (worker identity + requester identity + instruction).
  const show = await runMailbox({ mailboxDir, args: ["show", "--id", requestId] });
  assert.equal(show.code, 0);
  assert.match(show.stdout, /dispatched/);
  assert.match(show.stdout, /sess-worker-b/);
  assert.match(show.stdout, /sess-requester-a/);
  assert.match(show.stdout, /run the acceptance checks/);

  // Dispatch is idempotent-safe: a second dispatch is a no-op, not a new record.
  const again = await runMailbox({ mailboxDir, args: ["dispatch", "--id", requestId] });
  assert.equal(again.code, 0);
});

/**
 * Claim block (unit-002):
 *   claim id: mailbox-ext-EXT-1/EXT-1a
 *   claim: Unknown worker fails immediately, nothing half-dispatched (EXT-1a)
 *   scenario: When A calls agent_request(to=unknown, instruction=instr)
 *     Then the call fails immediately with the reason
 *     And no request is registered or dispatched
 */
test("EXT-1a: dispatch to an unknown pane fails immediately with the reason and leaves the store empty", async () => {
  const mailboxDir = await mkdtemp(join(tmpdir(), "agent-mailbox-req-"));

  await assert.rejects(
    dispatchRequest({
      mailboxDir,
      worker: "never-bound-pane",
      instruction: "anything",
      requesterIdentity: "sess-requester-a",
    }),
    /unknown worker pane "never-bound-pane"/
  );

  const list = await runMailbox({ mailboxDir, args: ["list"] });
  assert.equal(list.code, 0);
  assert.doesNotMatch(list.stdout, /req-/);
});

test("EXT-1a (no half-dispatch): a failed dispatch cancels the register so no orphan expectation survives", async () => {
  const mailboxDir = await mkdtemp(join(tmpdir(), "agent-mailbox-req-"));
  await bindPane({ mailboxDir, paneName: "worker-b", sessionId: "sess-worker-b" });

  // Inject a runner whose dispatch step fails after register succeeded.
  const calls = [];
  const failingRunner = async ({ args }) => {
    calls.push(args[0]);
    if (args[0] === "dispatch") {
      return { code: 3, stdout: "", stderr: "store refused" };
    }
    return { code: 0, stdout: "ok", stderr: "" };
  };

  await assert.rejects(
    dispatchRequest({
      mailboxDir,
      worker: "worker-b",
      instruction: "x",
      requesterIdentity: "sess-a",
      runMailbox: failingRunner,
    }),
    /mailbox dispatch failed/
  );
  assert.deepEqual(calls, ["register", "dispatch", "cancel"]);

  const list = await runMailbox({ mailboxDir, args: ["list"] });
  assert.doesNotMatch(list.stdout, /req-/);
});

test("requesterIdentity is required: anonymous requester must pass an explicit fallback", async () => {
  const mailboxDir = await mkdtemp(join(tmpdir(), "agent-mailbox-req-"));
  await assert.rejects(
    dispatchRequest({ mailboxDir, worker: "w", instruction: "i" }),
    /requesterIdentity required/
  );
});

test("runMailbox maps CLI failures to the documented exit vocabulary without throwing", async () => {
  const mailboxDir = await mkdtemp(join(tmpdir(), "agent-mailbox-req-"));
  const missing = await runMailbox({ mailboxDir, args: ["show", "--id", "req-nope"] });
  assert.equal(missing.code, 4); // notFound
  assert.match(missing.stderr, /no request "req-nope"/);
  assert.equal(await readFile(MAILBOX_CLI, "utf8").then(() => true, () => false), true);
});

/**
 * Claim block (unit-007, R1.F7):
 *   claim id: mailbox-ext-R1.F7/1
 *   claim: A hung mailbox child aborts the invocation with a typed timeout
 *     error after the per-invocation timeout instead of blocking indefinitely
 *   scenario: When the mailbox child process never exits
 *     Then runMailbox kills the child after timeoutMs
 *     And rejects with a RequestError tagged .timedOut
 *     And waitForOutcome surfaces the same timeout as a WaitError
 */
test("R1.F7: hung mailbox child is killed and runMailbox rejects with a typed timeout error", async () => {
  const mailboxDir = await mkdtemp(join(tmpdir(), "agent-mailbox-req-"));
  const start = Date.now();
  await assert.rejects(
    // node -e "<hang>" — args[0] becomes the -e script body: a child that
    // never exits on its own (mailboxDir/env are irrelevant to it).
    runMailbox({
      mailboxDir,
      args: ["setInterval(() => {}, 1e9)"],
      cliPath: "-e",
      timeoutMs: 200,
    }),
    (err) => err instanceof RequestError && err.timedOut === true && /timed out/.test(err.message),
  );
  assert.ok(Date.now() - start < 5000, "timeout must fire promptly, not block indefinitely");
});

test("R1.F7: default child timeout is 30s and a fast child resolves without the timer firing", async () => {
  assert.equal(MAILBOX_CHILD_TIMEOUT_MS, 30_000);
  const mailboxDir = await mkdtemp(join(tmpdir(), "agent-mailbox-req-"));
  const shown = await runMailbox({ mailboxDir, args: ["show", "--id", "req-nope"] });
  assert.equal(shown.code, 4); // completes normally; timer cleared on close
});
