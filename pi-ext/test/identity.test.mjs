// Session identity module unit tests (scaffold contract, unit-001).
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  bindingsPath,
  loadBindings,
  bindPane,
  resolvePane,
  resolvePaneName,
} from "../agent-mailbox/identity.mjs";

test("bindings live under <mailboxDir>/ext, not in the store root", async () => {
  const dir = await mkdtemp(join(tmpdir(), "agent-mailbox-"));
  await bindPane({ mailboxDir: dir, paneName: "p1", sessionId: "s1" });
  const p = bindingsPath(dir);
  assert.match(p, /ext[\\/]session-identities\.json$/);
  const { readdir } = await import("node:fs/promises");
  const entries = await readdir(dir);
  assert.deepEqual(entries, ["ext"]); // store root untouched
});

test("bind then resolve returns the same session identity", async () => {
  const dir = await mkdtemp(join(tmpdir(), "agent-mailbox-"));
  const stored = await bindPane({ mailboxDir: dir, paneName: "driver", sessionId: "abc" });
  assert.equal(stored.sessionId, "abc");
  assert.ok(stored.boundAt);
  assert.deepEqual(await resolvePane({ mailboxDir: dir, paneName: "driver" }), stored);
});

test("unbound pane resolves to null; empty dir loads empty table", async () => {
  const dir = await mkdtemp(join(tmpdir(), "agent-mailbox-"));
  assert.deepEqual(await loadBindings(dir), {});
  assert.equal(await resolvePane({ mailboxDir: dir, paneName: "nope" }), null);
});

test("rebinding a pane replaces the session identity (base binding semantics)", async () => {
  const dir = await mkdtemp(join(tmpdir(), "agent-mailbox-"));
  await bindPane({ mailboxDir: dir, paneName: "w", sessionId: "old", now: "2026-01-01T00:00:00Z" });
  await bindPane({ mailboxDir: dir, paneName: "w", sessionId: "new", now: "2026-01-02T00:00:00Z" });
  assert.deepEqual(await resolvePane({ mailboxDir: dir, paneName: "w" }), {
    sessionId: "new",
    boundAt: "2026-01-02T00:00:00Z",
  });
});

test("bindPane rejects empty pane name or session id", async () => {
  const dir = await mkdtemp(join(tmpdir(), "agent-mailbox-"));
  await assert.rejects(() => bindPane({ mailboxDir: dir, paneName: "", sessionId: "s" }));
  await assert.rejects(() => bindPane({ mailboxDir: dir, paneName: "p", sessionId: "" }));
});

test("resolvePaneName reads AGENT_PANE from env", () => {
  assert.equal(resolvePaneName({ env: { AGENT_PANE: "worker-2" } }), "worker-2");
  assert.equal(resolvePaneName({ env: {} }), null);
});

// ---- unit-007: session identity, pane-name reuse, and explicit rebind ----

import { recordReplacement, rebindRequester, rebindPaneRequests, latestReplacement } from "../agent-mailbox/rebind.mjs";
import { dispatchRequest, runMailbox } from "../agent-mailbox/request.mjs";
import { replyOutcome } from "../agent-mailbox/reply.mjs";
import { probeDeliveries } from "../agent-mailbox/delivery.mjs";
import agentMailboxExtension from "../agent-mailbox/index.mjs";

function fakePi() {
  const registered = [];
  const handlers = {};
  return {
    registered,
    handlers,
    registerTool(tool) { registered.push(tool); },
    on(event, handler) { handlers[event] = handler; },
    sendMessage() {},
  };
}

async function replacedPaneSetup() {
  // Pane "driver-a" ran as sess-1, dispatched a request, and the worker
  // replied; then the pane's session ended and a NEW session (sess-2)
  // reused the pane name.
  const mailboxDir = await mkdtemp(join(tmpdir(), "agent-mailbox-rebind-"));
  await bindPane({ mailboxDir, paneName: "driver-a", sessionId: "sess-1" });
  await bindPane({ mailboxDir, paneName: "worker-b", sessionId: "sess-worker-b" });
  const { requestId } = await dispatchRequest({
    mailboxDir,
    worker: "worker-b",
    instruction: "do the thing",
    requesterIdentity: "sess-1",
  });
  await replyOutcome({
    mailboxDir,
    requestId,
    status: "DONE",
    report: "all checks green",
    workerPane: "worker-b",
  });
  return { mailboxDir, requestId };
}

/**
 * Claim block (unit-007):
 *   claim id: mailbox-ext-EXT-4/EXT-4d
 *   claim: pane name reuse never delivers old replies to the new session (EXT-4d)
 *   scenario: Given a session with pending replies ended and a new session
 *     reused the same pane name
 *     Then old replies are never delivered to the new session
 *     And delivery requires an explicit rebind
 */
test("EXT-4/EXT-4d: new session reusing a pane name never receives the old session's replies", async () => {
  const { mailboxDir, requestId } = await replacedPaneSetup();

  // The replacement session starts: session_start records the replacement
  // and rebinds the pane to sess-2 (bookkeeping only — no request rebind).
  const pi = fakePi();
  agentMailboxExtension(pi, { mailboxDir, paneName: "driver-a", sessionId: "sess-2" });
  await pi.handlers.session_start({}, {});

  // The replacement's identity resolves to sess-2; the pending reply is
  // addressed to sess-1, so the delivery probe delivers NOTHING.
  const probe = await probeDeliveries({ mailboxDir, requesterIdentity: "sess-2" });
  assert.deepEqual(probe.delivered, []);

  // A consume attempt under the replacement identity is refused by the
  // mailbox itself: identity change requires an explicit rebind.
  const consumed = await runMailbox({
    mailboxDir,
    args: ["consume", "--id", requestId, "--requester", "sess-2"],
  });
  assert.notEqual(consumed.code, 0);
  assert.match(consumed.stderr, /explicit rebind required/);

  // Even agent_wait under the replacement identity cannot take the reply.
  const { waitForOutcome, WaitError } = await import("../agent-mailbox/wait.mjs");
  await assert.rejects(
    () =>
      waitForOutcome({
        mailboxDir,
        requestId,
        requesterIdentity: "sess-2",
        timeoutMs: 1_000,
        pollMs: 20,
      }),
    (err) => err instanceof WaitError && /explicit rebind required/.test(err.message)
  );

  // The replacement was recorded for the pane (bookkeeping present, delivery
  // still blocked).
  const replacement = await latestReplacement(mailboxDir, "driver-a");
  assert.ok(replacement);
  assert.equal(replacement.from, "sess-1");
  assert.equal(replacement.to, "sess-2");
});

/**
 * Claim block (unit-007):
 *   claim id: mailbox-ext-RC-4/RC-4
 *   claim: explicit rebind delivers pending replies to the replacement (RC-4)
 *   scenario: When the operator rebinds a request's requester identity to
 *     the replacement session
 *     Then pending replies deliver to the replacement
 */
test("RC-4/RC-4: agent_rebind delivers pending replies to the replacement session", async () => {
  const { mailboxDir, requestId } = await replacedPaneSetup();

  // Replacement session starts (records the replacement, binds sess-2).
  const pi = fakePi();
  agentMailboxExtension(pi, { mailboxDir, paneName: "driver-a", sessionId: "sess-2" });
  await pi.handlers.session_start({}, {});

  // The operator (or the replacement session) calls agent_rebind explicitly.
  const tool = pi.registered.find((t) => t.name === "agent_rebind");
  const result = await tool.execute("tc-rebind", { pane: "driver-a" });
  assert.equal(result.details.error, undefined);
  assert.deepEqual(result.details.rebound, [requestId]);

  // Now the pending reply delivers to the replacement — exactly once.
  const sent = [];
  const probe = await probeDeliveries({
    mailboxDir,
    requesterIdentity: "sess-2",
    sendMessage: (message, opts) => sent.push({ message, opts }),
  });
  assert.deepEqual(
    probe.delivered.map((d) => d.requestId),
    [requestId]
  );
  assert.equal(sent.length, 1);
  assert.equal(sent[0].opts.triggerTurn, true);
  assert.match(sent[0].message.content, /worker sess-worker-b/);

  // A second probe is a no-op (exactly-once preserved after rebind).
  const again = await probeDeliveries({ mailboxDir, requesterIdentity: "sess-2" });
  assert.deepEqual(again.delivered, []);
});

test("agent_rebind without a recorded replacement reports nothing to rebind", async () => {
  const mailboxDir = await mkdtemp(join(tmpdir(), "agent-mailbox-rebind-"));
  const pi = fakePi();
  agentMailboxExtension(pi, { mailboxDir, paneName: "solo", sessionId: "sess-1" });
  await pi.handlers.session_start({}, {});
  const tool = pi.registered.find((t) => t.name === "agent_rebind");
  const result = await tool.execute("tc-1", {});
  assert.equal(result.details.error, undefined);
  assert.match(result.content[0].text, /no session replacement recorded/);
});

test("rebindRequester rebinds every undelivered request of the old identity and leaves delivered ones alone", async () => {
  const mailboxDir = await mkdtemp(join(tmpdir(), "agent-mailbox-rebind-"));
  await bindPane({ mailboxDir, paneName: "w", sessionId: "sess-w" });
  const { requestId: r1 } = await dispatchRequest({
    mailboxDir, worker: "w", instruction: "a", requesterIdentity: "old",
  });
  const { requestId: r2 } = await dispatchRequest({
    mailboxDir, worker: "w", instruction: "b", requesterIdentity: "old",
  });
  const { requestId: other } = await dispatchRequest({
    mailboxDir, worker: "w", instruction: "c", requesterIdentity: "someone-else",
  });
  await replyOutcome({ mailboxDir, requestId: r1, status: "DONE", report: "x", workerPane: "w" });
  // Deliver r1 exactly once under the old identity, so it is no longer pending.
  await runMailbox({ mailboxDir, args: ["consume", "--id", r1, "--requester", "old"] });

  const { rebound } = await rebindRequester({ mailboxDir, fromIdentity: "old", toIdentity: "new" });
  assert.deepEqual(rebound.sort(), [r2].sort());
  assert.deepEqual((await rebindRequester({ mailboxDir, fromIdentity: "old", toIdentity: "new" })).rebound, []);

  // The untouched request keeps its own requester.
  const shown = await runMailbox({ mailboxDir, args: ["show", "--id", other] });
  assert.equal(JSON.parse(shown.stdout).requester, "someone-else");
});

test("recordReplacement appends and latestReplacement returns the newest entry per pane", async () => {
  const mailboxDir = await mkdtemp(join(tmpdir(), "agent-mailbox-rebind-"));
  await recordReplacement({ mailboxDir, paneName: "p", fromSessionId: "s1", toSessionId: "s2", now: "t1" });
  await recordReplacement({ mailboxDir, paneName: "q", fromSessionId: "s3", toSessionId: "s4", now: "t2" });
  await recordReplacement({ mailboxDir, paneName: "p", fromSessionId: "s2", toSessionId: "s5", now: "t3" });
  assert.equal((await latestReplacement(mailboxDir, "p")).to, "s5");
  assert.equal((await latestReplacement(mailboxDir, "q")).from, "s3");
  assert.equal(await latestReplacement(mailboxDir, "nope"), null);
});

// R1.F4 regression: two concurrent bindPane calls (real child processes) must
// not lose each other's write. Sequential tests cannot exercise the
// interleaving (decision 013: verify concurrency only with real concurrent
// processes).
test("concurrent bindPane processes both survive (no lost write)", async () => {
  const mailboxDir = await mkdtemp(join(tmpdir(), "agent-mailbox-lock-"));
  const mod = new URL("../agent-mailbox/identity.mjs", import.meta.url).pathname;
  const script = (pane, session) => `
    import { bindPane } from ${JSON.stringify(mod)};
    await bindPane({ mailboxDir: ${JSON.stringify(mailboxDir)}, paneName: ${JSON.stringify(pane)}, sessionId: ${JSON.stringify(session)} });
  `;
  const { spawn } = await import("node:child_process");
  const { promisify } = await import("node:util");
  const run = (code) => {
    const child = spawn(process.execPath, ["-e", code]);
    let err = "";
    child.stderr.on("data", (d) => (err += d));
    return promisify((cb) => child.on("exit", (c) => cb(null, c)))().then((c) => {
      if (c !== 0) throw new Error(`child exited ${c}: ${err}`);
    });
  };
  // 20 concurrent binders across distinct panes, all racing on one file.
  await Promise.all(
    Array.from({ length: 20 }, (_, i) => run(script(`pane-${i}`, `session-${i}`)))
  );
  const bindings = await loadBindings(mailboxDir);
  for (let i = 0; i < 20; i++) {
    assert.equal(bindings[`pane-${i}`]?.sessionId, `session-${i}`, `pane-${i} binding lost`);
  }
  assert.equal(Object.keys(bindings).length, 20);
});

// R1.F4 regression: concurrent recordReplacement processes must append every
// journal entry — no lost appends, no clobbered file.
test("concurrent recordReplacement processes all append (no lost entry)", async () => {
  const mailboxDir = await mkdtemp(join(tmpdir(), "agent-mailbox-rlock-"));
  const mod = new URL("../agent-mailbox/rebind.mjs", import.meta.url).pathname;
  const { spawn } = await import("node:child_process");
  const { promisify } = await import("node:util");
  const run = (i) => {
    const child = spawn(process.execPath, ["-e", `
      import { recordReplacement } from ${JSON.stringify(mod)};
      await recordReplacement({ mailboxDir: ${JSON.stringify(mailboxDir)}, paneName: "p", fromSessionId: "s${i}", toSessionId: "t${i}" });
    `]);
    let err = "";
    child.stderr.on("data", (d) => (err += d));
    return promisify((cb) => child.on("exit", (c) => cb(null, c)))().then((c) => {
      if (c !== 0) throw new Error(`child exited ${c}: ${err}`);
    });
  };
  await Promise.all(Array.from({ length: 20 }, (_, i) => run(i)));
  const { loadReplacements } = await import("../agent-mailbox/rebind.mjs");
  const entries = await loadReplacements(mailboxDir);
  const froms = new Set(entries.map((e) => e.from));
  for (let i = 0; i < 20; i++) assert.ok(froms.has(`s${i}`), `replacement s${i} lost`);
  assert.equal(entries.length, 20);
});
