// Behavioral tests for mailbox unit-001 (pending discoverability),
// unit-002 (duplicate/worker-identity), and unit-003 (exactly-once
// consumption, unreachable redelivery, pause hold, requester-identity
// rebind guard). Claim-to-test tracing is by scenario title in the test
// name (decision 010); numeric prefixes were dropped (issue #49) because
// they drifted as scenarios were added or removed.

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { test } from "node:test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const CLI = new URL("../mailbox.mjs", import.meta.url).pathname;

import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execFileP = promisify(execFile);

function run(dir, ...args) {
  return execFileSync(process.execPath, [CLI, ...args], {
    env: { ...process.env, MAILBOX_DIR: dir },
    encoding: "utf8",
  });
}

// Spawn several CLI invocations as real concurrent child processes (R2.F1's
// interleavings cannot be exercised with sequential calls).
async function runConcurrent(dir, ...cmds) {
  return Promise.all(
    cmds.map((args) =>
      execFileP(process.execPath, [CLI, ...args], {
        env: { ...process.env, MAILBOX_DIR: dir },
        encoding: "utf8",
        maxBuffer: 1024 * 1024,
      })
        .then(({ stdout }) => ({ code: 0, stdout }))
        .catch((err) => ({ code: err.code ?? 1, stdout: err.stdout ?? "", stderr: err.stderr ?? "" }))
    )
  );
}

function assertWithinVocabulary(code, context) {
  assert.ok([0, 2, 3, 4].includes(code), `${context}: exit ${code} outside 0/2/3/4`);
}

test("R3.F1 regression: dispatch on a cancelled record is an explicit no-op, never a resurrection", () => {
  // variant 1 (the review's probe): reply → cancel → dispatch → consume delivers?
  const dir = makeDir();
  run(dir, "register", "--id", "r1", "--requester", "q1", "--worker", "w1", "--instruction", "i");
  run(dir, "dispatch", "--id", "r1");
  run(dir, "reply", "--id", "r1", "--worker", "w1", "--status", "DONE", "--report", "x");
  run(dir, "cancel", "--id", "r1");

  const out = run(dir, "dispatch", "--id", "r1");
  assert.match(out, /ignored: request is cancelled \(no-op\)/);
  let record = JSON.parse(run(dir, "show", "--id", "r1"));
  assert.equal(record.state, "cancelled");

  // the reply cannot deliver past the cancel
  const err = runExpectFailure(dir, "consume", "--id", "r1", "--requester", "q1");
  assert.match(err.stderr, /is cancelled; no delivery/);
  assert.equal(JSON.parse(run(dir, "show", "--id", "r1")).delivered, false);

  // variant 2: cancel → dispatch → reply — a fresh outcome must not bind
  const dir2 = makeDir();
  run(dir2, "register", "--id", "r2", "--requester", "q1", "--worker", "w1", "--instruction", "i");
  run(dir2, "cancel", "--id", "r2");
  assert.match(run(dir2, "dispatch", "--id", "r2"), /ignored: request is cancelled/);
  const err2 = runExpectFailure(dir2, "reply", "--id", "r2", "--worker", "w1", "--status", "DONE");
  assert.match(err2.stderr, /the request is cancelled; no outcome can bind/);
  record = JSON.parse(run(dir2, "show", "--id", "r2"));
  assert.equal(record.state, "cancelled");
  assert.equal(record.reply, null);
});

test("R3.F2 regression: unknown option names are usage rejections; values still verbatim", () => {
  const dir = makeDir();
  // typo'd option name: usage exit 2, nothing persisted
  const err = runExpectFailure(dir, "register", "--id", "c2", "--requester", "q1", "--worker", "w1", "--instruction", "i", "--reqestor", "typo");
  assert.match(err.stderr, /unknown option --reqestor for command "register"/);
  assert.equal(err.status, 2);
  assert.equal(run(dir, "list"), ""); // nothing persisted

  // --opt=value form with an unknown name: same rejection
  const err2 = runExpectFailure(dir, "reply", "--id", "ghost", "--worker=w1", "--status=DONE", "--bogus=x");
  assert.match(err2.stderr, /unknown option --bogus for command "reply"/);
  assert.equal(err2.status, 2);

  // R1.F4 contract intact: values beginning with -- are consumed verbatim
  run(dir, "register", "--id", "r1", "--requester", "q1", "--worker", "w1", "--instruction", "--weird flag-like text");
  assert.equal(JSON.parse(run(dir, "show", "--id", "r1")).instruction, "--weird flag-like text");
});

test("R3.F3 regression: unreadable store directory exits within the vocabulary", () => {
  if (process.getuid() === 0) return; // chmod 000 cannot block root
  const dir = makeDir();
  run(dir, "register", "--id", "r1", "--requester", "q1", "--worker", "w1", "--instruction", "i");
  fs.chmodSync(dir, 0o000);
  let err;
  try { run(dir, "list"); err = null; }
  catch (e) { err = e; }
  fs.chmodSync(dir, 0o700);
  assert.ok(err, "expected list to fail on an unreadable store dir");
  assert.equal(err.status, 3);
  assert.match(err.stderr, /cannot read store directory/);
  assert.ok(!/\n    at /.test(err.stderr), "raw stack trace leaked");
  // recovery: readable again, everything works
  assert.match(run(dir, "list"), /^r1\t/);
});

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

// --- R2.F1: concurrency (real concurrent processes) ---
// Standing coverage requirement (issue #50, decision 013): any future
// store-level or locking change extends this real-concurrent-process
// section (lock wait-timeout / stale-steal paths included) instead of
// regressing to sequential-only tests.

async function concurrencyProbes(dir) {
  const results = {};
  for (const [name, setup, cmds] of [
    ["consume-vs-reply",
      (d) => {
        run(d, "register", "--id", "r1", "--requester", "q1", "--worker", "w1", "--instruction", "i");
        run(d, "dispatch", "--id", "r1");
      },
      () => [
        ["consume", "--id", "r1", "--requester", "q1"],
        ["reply", "--id", "r1", "--worker", "w1", "--status", "DONE", "--report", "x"],
        ["consume", "--id", "r1", "--requester", "q1"],
        ["consume", "--id", "r1", "--requester", "q1"],
      ]],
    ["consume-race",
      (d) => {
        run(d, "register", "--id", "r1", "--requester", "q1", "--worker", "w1", "--instruction", "i");
        run(d, "dispatch", "--id", "r1");
        run(d, "reply", "--id", "r1", "--worker", "w1", "--status", "DONE");
      },
      () => [
        ["consume", "--id", "r1", "--requester", "q1"],
        ["consume", "--id", "r1", "--requester", "q1"],
        ["consume", "--id", "r1", "--requester", "q1"],
        ["consume", "--id", "r1", "--requester", "q1"],
      ]],
    ["register-race",
      () => {},
      () => [
        ["register", "--id", "r1", "--requester", "q1", "--worker", "w1", "--instruction", "one"],
        ["register", "--id", "r1", "--requester", "q2", "--worker", "w2", "--instruction", "two"],
        ["register", "--id", "r1", "--requester", "q3", "--worker", "w3", "--instruction", "three"],
      ]],
    ["reply-vs-cancel",
      (d) => {
        run(d, "register", "--id", "r1", "--requester", "q1", "--worker", "w1", "--instruction", "i");
        run(d, "dispatch", "--id", "r1");
      },
      () => [
        ["reply", "--id", "r1", "--worker", "w1", "--status", "DONE"],
        ["cancel", "--id", "r1"],
      ]],
  ]) {
    const d = makeDir();
    setup(d);
    results[name] = { outcomes: await runConcurrent(d, ...cmds()), dir: d };
  }
  return results;
}

test("R2.F1 regression: concurrent consume polling cannot erase a reply", async () => {
  const { outcomes, dir } = (await concurrencyProbes(makeDir()))["consume-vs-reply"];
  for (const o of outcomes) assertWithinVocabulary(o.code, "consume-vs-reply");
  // the reply, if acknowledged, is never erased — and survives in the store
  const record = JSON.parse(run(dir, "show", "--id", "r1"));
  const acknowledged = outcomes.some((o) => /reply recorded/.test(o.stdout));
  assert.ok(record.reply !== null || !acknowledged, "an acknowledged reply was erased");
  // record reflects a serialized state, not a partial overwrite
  assert.ok(record.reply === null || record.reply.status === "DONE");
});

test("R2.F1 regression: concurrent consumes — at most one delivery acknowledged", async () => {
  const { outcomes, dir } = (await concurrencyProbes(makeDir()))["consume-race"];
  for (const o of outcomes) assertWithinVocabulary(o.code, "consume-race");
  const delivered = outcomes.filter((o) => /delivered reply for r1/.test(o.stdout)).length;
  assert.ok(delivered >= 1, "the settled reply was never delivered");
  const record = JSON.parse(run(dir, "show", "--id", "r1"));
  assert.equal(record.delivered, true);
  assert.equal(record.reply.status, "DONE");
  // the delivered mark is set exactly once in the persisted attempt log
  assert.equal(record.deliveryAttempts.filter((a) => a.result === "delivered").length, 1);
});

test("R2.F1 regression: concurrent registrations — at most one live expectation", async () => {
  const { outcomes, dir } = (await concurrencyProbes(makeDir()))["register-race"];
  for (const o of outcomes) assertWithinVocabulary(o.code, "register-race");
  const registered = outcomes.filter((o) => /registered r1/.test(o.stdout));
  assert.ok(registered.length <= 1, `expected at most one successful registration, got ${registered.length}`);
  const record = JSON.parse(run(dir, "show", "--id", "r1"));
  // the stored record matches exactly one of the attempted registrations
  assert.ok(["q1", "q2", "q3"].includes(record.requester));
  assert.equal(registered.length, 1); // someone must win; none silently overwritten
});

test("R2.F1 regression: concurrent reply and cancel — no acknowledged effect lost", async () => {
  const { outcomes, dir } = (await concurrencyProbes(makeDir()))["reply-vs-cancel"];
  for (const o of outcomes) assertWithinVocabulary(o.code, "reply-vs-cancel");
  const record = JSON.parse(run(dir, "show", "--id", "r1"));
  // each acknowledged command's effect is present in the store
  if (outcomes.some((o) => /reply recorded/.test(o.stdout))) {
    assert.ok(record.reply !== null, "an acknowledged reply vanished");
  }
  if (outcomes.some((o) => /cancelled r1/.test(o.stdout))) {
    assert.equal(record.state, "cancelled");
  }
});

test("register creates a reply expectation before exposure", () => {
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

test("re-registration with a live expectation is rejected, original unchanged", () => {
  const dir = makeDir();
  run(dir, "register", "--id", "r1", "--requester", "q1", "--worker", "w1", "--instruction", "first instruction");

  const err = runExpectFailure(dir, "register", "--id", "r1", "--requester", "q2", "--worker", "w2", "--instruction", "second instruction");
  assert.match(err.stderr, /already has a live expectation/);

  // original unchanged — no silent overwrite
  const record = JSON.parse(run(dir, "show", "--id", "r1"));
  assert.equal(record.instruction, "first instruction");
  assert.equal(record.requester, "q1");
});

test("reply is persisted against the original request", () => {
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

test("duplicate reply keeps the first — one logical delivery", () => {
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

test("replaced worker identity cannot bind a reply; attempt stays inspectable", () => {
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

test("R1.F2 regression: reply to a cancelled request is rejected, attempt inspectable", () => {
  const dir = makeDir();
  run(dir, "register", "--id", "r1", "--requester", "q1", "--worker", "w1", "--instruction", "i");
  run(dir, "cancel", "--id", "r1");

  const err = runExpectFailure(dir, "reply", "--id", "r1", "--worker", "w1", "--status", "DONE", "--report", "late reply");
  assert.match(err.stderr, /the request is cancelled; no outcome can bind/);

  const record = JSON.parse(run(dir, "show", "--id", "r1"));
  // no outcome bound on the cancelled expectation; attempt stays inspectable
  assert.equal(record.reply, null);
  assert.equal(record.rejectedReplies.length, 1);
  assert.equal(record.rejectedReplies[0].worker, "w1");
  assert.equal(record.rejectedReplies[0].status, "DONE");
  assert.equal(record.rejectedReplies[0].report, "late reply");
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

test("exactly-once consumption — late re-delivery is a no-op", () => {
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

test("reply survives an unreachable requester — redelivered later", () => {
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

test("paused requester holds the reply as inspectable state", () => {
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

test("requester identity change refuses delivery until explicit rebind", () => {
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

test("R1.F1 regression: registration after cancel supersedes the cancelled record", () => {
  const dir = makeDir();
  run(dir, "register", "--id", "r1", "--requester", "q1", "--worker", "w1", "--instruction", "first");
  run(dir, "cancel", "--id", "r1");

  // re-registration after cancel succeeds with the new parameters
  const out = run(dir, "register", "--id", "r1", "--requester", "q2", "--worker", "w2", "--instruction", "second");
  assert.match(out, /registered r1 \(pending\)/);

  const record = JSON.parse(run(dir, "show", "--id", "r1"));
  assert.equal(record.requester, "q2");
  assert.equal(record.worker, "w2");
  assert.equal(record.instruction, "second");
  assert.equal(record.state, "pending");
  assert.equal(record.reply, null);
  // fresh record: cancelled history does not leak into the new expectation
  assert.equal(record.paused, false);
  assert.equal(record.delivered, false);

  // a live (non-cancelled) expectation is still rejected, original unchanged
  const err = runExpectFailure(dir, "register", "--id", "r1", "--requester", "q3", "--worker", "w3", "--instruction", "third");
  assert.match(err.stderr, /already has a live expectation/);
  assert.equal(JSON.parse(run(dir, "show", "--id", "r1")).instruction, "second");
});

test("R3.F4 regression: re-registration archives the cancelled record with its history", () => {
  const dir = makeDir();
  run(dir, "register", "--id", "r1", "--requester", "q1", "--worker", "w1", "--instruction", "i");
  run(dir, "cancel", "--id", "r1");
  // a late reply is rejected and recorded on the cancelled record
  runExpectFailure(dir, "reply", "--id", "r1", "--worker", "w1", "--status", "DONE", "--report", "late");

  run(dir, "register", "--id", "r1", "--requester", "q2", "--worker", "w2", "--instruction", "fresh");

  // fresh record has no inherited history
  const record = JSON.parse(run(dir, "show", "--id", "r1"));
  assert.equal(record.rejectedReplies.length, 0);
  assert.equal(record.state, "pending");

  // the superseded cancelled record is archived, inspectable, history intact
  const archives = fs.readdirSync(dir).filter((n) => /^r1\.cancelled\..+\.json$/.test(n));
  assert.equal(archives.length, 1);
  const archived = JSON.parse(fs.readFileSync(path.join(dir, archives[0]), "utf8"));
  assert.equal(archived.state, "cancelled");
  assert.equal(archived.rejectedReplies.length, 1);
  assert.equal(archived.rejectedReplies[0].report, "late");

  // archives are not live expectations: not listed, not showable by id
  assert.equal(JSON.parse(run(dir, "show", "--id", "r1")).requestId, "r1");
  assert.equal(run(dir, "list").split("\n").filter(Boolean).length, 1);
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

test("consume before a reply settles is not an error and does not write the record", () => {
  const dir = makeDir();
  run(dir, "register", "--id", "r1", "--requester", "q1", "--worker", "w1", "--instruction", "i");
  assert.match(run(dir, "consume", "--id", "r1", "--requester", "q1"), /no settled reply for r1/);
  const record = JSON.parse(run(dir, "show", "--id", "r1"));
  // R2.F1: this path no longer persists the attempt — the write that made the
  // erase race possible; the outcome is reported on stdout only.
  assert.equal(record.deliveryAttempts.length, 0);
  assert.equal(record.delivered, false);
  assert.equal(record.reply, null);
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

test("R1.F4 regression: option values may start with --; missing value still usage", () => {
  const dir = makeDir();
  // space-separated form consumes the next token positionally, even if it
  // starts with '--'
  run(dir, "register", "--id", "r1", "--requester", "q1", "--worker", "w1", "--instruction", "--weird flag-like text");
  let record = JSON.parse(run(dir, "show", "--id", "r1"));
  assert.equal(record.instruction, "--weird flag-like text");

  // --opt=value form as the unambiguous alternative
  run(dir, "register", "--id=r2", "--requester=q1", "--worker=w1", "--instruction=--second --text");
  record = JSON.parse(run(dir, "show", "--id", "r2"));
  assert.equal(record.instruction, "--second --text");

  // a bare flag at the end of argv is still a usage error (exit 2)
  const err = runExpectFailure(dir, "register", "--id", "r3", "--requester", "q1", "--worker", "w1", "--instruction");
  assert.match(err.stderr, /--instruction requires a value/);
  assert.equal(err.status, 2);
});

test("R2.F3 regression: consume acknowledges the reply before marking delivered", () => {
  const dir = makeDir();
  run(dir, "register", "--id", "r1", "--requester", "q1", "--worker", "w1", "--instruction", "i");
  run(dir, "dispatch", "--id", "r1");
  run(dir, "reply", "--id", "r1", "--worker", "w1", "--status", "DONE", "--report", "all done");

  // Simulate the crash window between print and mark: the save that would
  // set the delivered mark fails (test hook in save(), after the print).
  process.env.MAILBOX_FAIL_SAVE = "1";
  let code = 0, stdout = "", stderr = "";
  try { stdout = run(dir, "consume", "--id", "r1", "--requester", "q1"); }
  catch (e) { code = e.status; stdout = e.stdout; stderr = e.stderr; }
  delete process.env.MAILBOX_FAIL_SAVE;
  // the requester received the reply BEFORE the mark failed to land
  assert.match(stdout, /delivered reply for r1: DONE — all done/);
  assert.ok(code > 0, "expected the simulated save failure to surface");
  const record = JSON.parse(run(dir, "show", "--id", "r1"));
  assert.equal(record.delivered, false);
  // the next consume re-delivers — the reply is never lost
  assert.match(run(dir, "consume", "--id", "r1", "--requester", "q1"), /delivered reply for r1: DONE — all done/);
  assert.equal(JSON.parse(run(dir, "show", "--id", "r1")).delivered, true);
});

test("R2.F2 regression: non-parse read errors stay within the exit-code vocabulary", () => {
  const dir = makeDir();
  run(dir, "register", "--id", "r1", "--requester", "q1", "--worker", "w1", "--instruction", "i");
  // a directory at a record path: EISDIR on read
  fs.mkdirSync(path.join(dir, "x.json"));

  let err = runExpectFailure(dir, "show", "--id", "x");
  assert.match(err.stderr, /cannot read record "x"/);
  assert.equal(err.status, 3);
  assert.ok(!/\n    at /.test(err.stderr), "raw stack trace leaked");

  // unreadable file in the store dir: list warns and skips, exit 0
  const locked = path.join(dir, "locked.json");
  fs.writeFileSync(locked, "{\"requestId\":\"locked\"}");
  if (process.getuid() !== 0) fs.chmodSync(locked, 0o000);
  let code = 0, out = "", stderr = "";
  try { out = run(dir, "list"); } catch (e) { code = e.status; out = e.stdout; stderr = e.stderr; }
  assert.equal(code, 0, `list exit ${code}: ${stderr}`);
  assert.match(out, /^r1\t/);
  assert.doesNotMatch(out, /locked/);
  // list exit stays in the vocabulary even if chmod was ineffective (root)
  assert.ok([0, 2, 3, 4].includes(code));
});

test("R1.F3 regression: corrupt store file does not wedge discovery or crash the CLI", () => {
  const dir = makeDir();
  run(dir, "register", "--id", "r1", "--requester", "q1", "--worker", "w1", "--instruction", "i");
  fs.writeFileSync(path.join(dir, "bad.json"), "garbage{");

  // list skips the damaged file with a warning; valid records survive
  let out, exit = 0;
  try { out = run(dir, "list"); } catch (err) { exit = err.status; out = err.stdout; }
  assert.equal(exit, 0);
  assert.match(out, /^r1\t/);

  // show of the specifically addressed corrupt record: clean rejection, exit 3
  const err = runExpectFailure(dir, "show", "--id", "bad");
  assert.match(err.stderr, /corrupt \(unparseable store file\)/);
  assert.equal(err.status, 3);

  // valid records remain fully usable
  assert.equal(JSON.parse(run(dir, "show", "--id", "r1")).requestId, "r1");
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
