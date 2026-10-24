// Behavioral tests for mailbox unit-001 (scenarios 1–2, pending
// discoverability), unit-002 (scenarios 3–5, duplicate/worker-identity), and
// unit-003 (scenarios 6–10: exactly-once consumption, unreachable
// redelivery, pause hold, requester-identity rebind guard), mapped to
// .todo/specs/mailbox-service.feature.

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { test } from "node:test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const CLI = new URL("../mailbox.mjs", import.meta.url).pathname;

function run(dir, ...args) {
  return execFileSync(process.execPath, [CLI, ...args], {
    env: { ...process.env, MAILBOX_DIR: dir },
    encoding: "utf8",
  });
}

function runExpectFailure(dir, ...args) {
  try {
    run(dir, ...args);
    assert.fail(`expected non-zero exit for: ${args.join(" ")}`);
  } catch (err) {
    assert.ok(err.status > 0, `non-zero exit expected, got ${err.status}`);
    return err;
  }
}

function makeDir() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "mailbox-test-"));
}

test("scenario 1: register creates a reply expectation before exposure", () => {
  const dir = makeDir();
  const out = run(dir, "register", "--id", "r1", "--requester", "q1", "--worker", "w1", "--instruction", "do the thing");
  assert.match(out, /registered r1 \(pending\)/);

  // discoverable as pending, no outcome
  const list = run(dir, "list", "--pending");
  assert.match(list, /^r1\t/);
  const record = JSON.parse(run(dir, "show", "--id", "r1"));
  assert.equal(record.state, "pending");
  assert.equal(record.reply, null);
  assert.equal(record.delivered, false);
  assert.equal(record.requester, "q1");
  assert.equal(record.worker, "w1");
  assert.equal(record.instruction, "do the thing");
});

test("scenario 2: re-registration with a live expectation is rejected, original unchanged", () => {
  const dir = makeDir();
  run(dir, "register", "--id", "r1", "--requester", "q1", "--worker", "w1", "--instruction", "first instruction");

  const err = runExpectFailure(dir, "register", "--id", "r1", "--requester", "q2", "--worker", "w2", "--instruction", "second instruction");
  assert.match(err.stderr, /already has a live expectation/);

  // original unchanged — no silent overwrite
  const record = JSON.parse(run(dir, "show", "--id", "r1"));
  assert.equal(record.instruction, "first instruction");
  assert.equal(record.requester, "q1");
});

test("scenario 3: reply is persisted against the original request", () => {
  const dir = makeDir();
  run(dir, "register", "--id", "r1", "--requester", "q1", "--worker", "w1", "--instruction", "i");
  run(dir, "dispatch", "--id", "r1");
  const out = run(dir, "reply", "--id", "r1", "--worker", "w1", "--status", "DONE", "--report", "all done");
  assert.match(out, /reply recorded for r1 \(DONE\)/);

  const record = JSON.parse(run(dir, "show", "--id", "r1"));
  assert.equal(record.reply.status, "DONE");
  assert.equal(record.reply.report, "all done");
  assert.equal(record.reply.worker, "w1");
  assert.ok(record.reply.submittedAt);
  // no longer pending
  assert.equal(run(dir, "list", "--pending"), "");
});

test("scenario 4: duplicate reply keeps the first — one logical delivery", () => {
  const dir = makeDir();
  run(dir, "register", "--id", "r1", "--requester", "q1", "--worker", "w1", "--instruction", "i");
  run(dir, "dispatch", "--id", "r1");
  run(dir, "reply", "--id", "r1", "--worker", "w1", "--status", "DONE", "--report", "first");
  const out = run(dir, "reply", "--id", "r1", "--worker", "w1", "--status", "FAILED", "--report", "second");
  assert.match(out, /ignored: first reply \(DONE\) already persisted/);

  const record = JSON.parse(run(dir, "show", "--id", "r1"));
  assert.equal(record.reply.status, "DONE");
  assert.equal(record.reply.report, "first");
});

test("scenario 5: replaced worker identity cannot bind a reply; attempt stays inspectable", () => {
  const dir = makeDir();
  run(dir, "register", "--id", "r1", "--requester", "q1", "--worker", "w1", "--instruction", "i");
  run(dir, "dispatch", "--id", "r1");
  const err = runExpectFailure(dir, "reply", "--id", "r1", "--worker", "w2", "--status", "DONE", "--report", "from impostor");
  assert.match(err.stderr, /does not match the dispatched worker identity "w1"/);

  const record = JSON.parse(run(dir, "show", "--id", "r1"));
  // no outcome bound to the new session; rejected reply inspectable
  assert.equal(record.reply, null);
  assert.equal(record.rejectedReplies.length, 1);
  assert.equal(record.rejectedReplies[0].worker, "w2");
  assert.equal(record.rejectedReplies[0].status, "DONE");
  assert.equal(record.rejectedReplies[0].report, "from impostor");
  assert.ok(record.rejectedReplies[0].rejectedAt);
});

test("non-vocabulary status is rejected", () => {
  const dir = makeDir();
  run(dir, "register", "--id", "r1", "--requester", "q1", "--worker", "w1", "--instruction", "i");
  run(dir, "dispatch", "--id", "r1");
  for (const status of ["PENDING", "done", "OK"]) {
    const err = runExpectFailure(dir, "reply", "--id", "r1", "--worker", "w1", "--status", status);
    assert.match(err.stderr, /outside the vocabulary/);
  }
  // nothing bound
  const record = JSON.parse(run(dir, "show", "--id", "r1"));
  assert.equal(record.reply, null);
});

// --- unit-003: delivery ---

test("scenario 6: exactly-once consumption — late re-delivery is a no-op", () => {
  const dir = makeDir();
  run(dir, "register", "--id", "r1", "--requester", "q1", "--worker", "w1", "--instruction", "i");
  run(dir, "dispatch", "--id", "r1");
  run(dir, "reply", "--id", "r1", "--worker", "w1", "--status", "DONE", "--report", "all done");

  const out = run(dir, "consume", "--id", "r1", "--requester", "q1");
  assert.match(out, /delivered reply for r1: DONE — all done/);

  const record = JSON.parse(run(dir, "show", "--id", "r1"));
  assert.equal(record.delivered, true);
  assert.ok(record.deliveredAt);

  // late re-delivery attempt after consumption is a no-op
  const again = run(dir, "consume", "--id", "r1", "--requester", "q1");
  assert.match(again, /already delivered; re-delivery is a no-op/);
  const after = JSON.parse(run(dir, "show", "--id", "r1"));
  assert.equal(after.deliveredAt, record.deliveredAt);
});

test("scenario 8: reply survives an unreachable requester — redelivered later", () => {
  const dir = makeDir();
  run(dir, "register", "--id", "r1", "--requester", "q1", "--worker", "w1", "--instruction", "i");
  run(dir, "dispatch", "--id", "r1");
  run(dir, "reply", "--id", "r1", "--worker", "w1", "--status", "NEEDS_INPUT", "--report", "question");

  // requester unreachable: no consume happens; the reply stays persisted
  let record = JSON.parse(run(dir, "show", "--id", "r1"));
  assert.equal(record.reply.status, "NEEDS_INPUT");
  assert.equal(record.delivered, false);

  // later re-attempt delivers; nothing was lost
  const out = run(dir, "consume", "--id", "r1", "--requester", "q1");
  assert.match(out, /delivered reply for r1: NEEDS_INPUT/);
  record = JSON.parse(run(dir, "show", "--id", "r1"));
  assert.equal(record.delivered, true);
});

test("scenario 9: paused requester holds the reply as inspectable state", () => {
  const dir = makeDir();
  run(dir, "register", "--id", "r1", "--requester", "q1", "--worker", "w1", "--instruction", "i");
  run(dir, "dispatch", "--id", "r1");
  run(dir, "reply", "--id", "r1", "--worker", "w1", "--status", "DONE");

  const paused = run(dir, "pause", "--id", "r1");
  assert.match(paused, /paused r1/);

  const held = run(dir, "consume", "--id", "r1", "--requester", "q1");
  assert.match(held, /held: requester is paused/);
  const record = JSON.parse(run(dir, "show", "--id", "r1"));
  // no delivery while paused; reply remains held and inspectable
  assert.equal(record.delivered, false);
  assert.equal(record.reply.status, "DONE");
  assert.equal(record.paused, true);

  // resume, then delivery proceeds
  run(dir, "resume", "--id", "r1");
  assert.match(run(dir, "consume", "--id", "r1", "--requester", "q1"), /delivered reply for r1: DONE/);
});

test("scenario 10: requester identity change refuses delivery until explicit rebind", () => {
  const dir = makeDir();
  run(dir, "register", "--id", "r1", "--requester", "q1", "--worker", "w1", "--instruction", "i");
  run(dir, "dispatch", "--id", "r1");
  run(dir, "reply", "--id", "r1", "--worker", "w1", "--status", "DONE");

  // requester session restarted under a new identity
  const err = runExpectFailure(dir, "consume", "--id", "r1", "--requester", "q2");
  assert.match(err.stderr, /does not match the registered requester "q1"; explicit rebind required/);
  let record = JSON.parse(run(dir, "show", "--id", "r1"));
  assert.equal(record.delivered, false);
  assert.equal(record.deliveryAttempts.at(-1).result, "refused-identity-change");

  // explicit rebind, then delivery proceeds
  assert.match(run(dir, "rebind", "--id", "r1", "--requester", "q2"), /rebound r1 to requester "q2"/);
  assert.match(run(dir, "consume", "--id", "r1", "--requester", "q2"), /delivered reply for r1: DONE/);
  record = JSON.parse(run(dir, "show", "--id", "r1"));
  assert.equal(record.requester, "q2");
  assert.equal(record.delivered, true);
  assert.equal(record.rebinds.length, 1);
  assert.equal(record.rebinds[0].from, "q1");
});

test("cancel stops delivery and removes the request from pending", () => {
  const dir = makeDir();
  run(dir, "register", "--id", "r1", "--requester", "q1", "--worker", "w1", "--instruction", "i");
  assert.match(run(dir, "cancel", "--id", "r1"), /cancelled r1/);
  assert.equal(run(dir, "list", "--pending"), "");
  const err = runExpectFailure(dir, "consume", "--id", "r1", "--requester", "q1");
  assert.match(err.stderr, /cancelled; no delivery/);
});

test("pause is settable by any client and is idempotent", () => {
  const dir = makeDir();
  run(dir, "register", "--id", "r1", "--requester", "q1", "--worker", "w1", "--instruction", "i");
  // no identity check: any client may pause
  assert.match(run(dir, "pause", "--id", "r1"), /paused r1/);
  assert.match(run(dir, "pause", "--id", "r1"), /already paused \(no-op\)/);
});

test("consume before a reply settles is not an error and records the attempt", () => {
  const dir = makeDir();
  run(dir, "register", "--id", "r1", "--requester", "q1", "--worker", "w1", "--instruction", "i");
  assert.match(run(dir, "consume", "--id", "r1", "--requester", "q1"), /no settled reply for r1/);
  const record = JSON.parse(run(dir, "show", "--id", "r1"));
  assert.equal(record.deliveryAttempts.at(-1).result, "no-settled-reply");
});

test("rebind to the same identity is a no-op; consume of unknown id is not-found", () => {
  const dir = makeDir();
  run(dir, "register", "--id", "r1", "--requester", "q1", "--worker", "w1", "--instruction", "i");
  assert.match(run(dir, "rebind", "--id", "r1", "--requester", "q1"), /already bound/);
  const err = runExpectFailure(dir, "consume", "--id", "ghost", "--requester", "q1");
  assert.match(err.stderr, /no request "ghost"/);
});

// --- store-level pending semantics ---

test("reply to an unknown requestId is not correlated (original requestId only)", () => {
  const dir = makeDir();
  const err = runExpectFailure(dir, "reply", "--id", "ghost", "--worker", "w1", "--status", "DONE");
  assert.match(err.stderr, /no request "ghost"/);
});

test("dispatch marks the request dispatched; it remains discoverable as pending until a reply", () => {
  const dir = makeDir();
  run(dir, "register", "--id", "r1", "--requester", "q1", "--worker", "w1", "--instruction", "i");
  run(dir, "dispatch", "--id", "r1");
  const record = JSON.parse(run(dir, "show", "--id", "r1"));
  assert.equal(record.state, "dispatched");
  assert.ok(record.dispatchedAt);
  // no reply bound → still pending per the feature file
  const list = run(dir, "list", "--pending");
  assert.match(list, /^r1\t/);
});

test("dispatch of an unknown request fails with not-found", () => {
  const dir = makeDir();
  const err = runExpectFailure(dir, "dispatch", "--id", "missing");
  assert.match(err.stderr, /no request "missing"/);
});

test("store persists across CLI invocations (same store, fresh process)", () => {
  const dir = makeDir();
  run(dir, "register", "--id", "r1", "--requester", "q1", "--worker", "w1", "--instruction", "i");
  // fresh process reads the same on-disk store
  const record = JSON.parse(run(dir, "show", "--id", "r1"));
  assert.equal(record.requestId, "r1");
});

test("list is empty before any registration and filters by pending", () => {
  const dir = makeDir();
  assert.equal(run(dir, "list"), "");
  assert.equal(run(dir, "list", "--pending"), "");
  run(dir, "register", "--id", "r1", "--requester", "q1", "--worker", "w1", "--instruction", "i");
  assert.equal(run(dir, "list").split("\n").filter(Boolean).length, 1);
});
