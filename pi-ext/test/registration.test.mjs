// Tool registration unit tests (scaffold contract, unit-001).
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import agentMailboxExtension, { TOOL_NAMES, createTools } from "../agent-mailbox/index.mjs";

function fakePi() {
  const registered = [];
  const handlers = {};
  return {
    registered,
    handlers,
    registerTool(tool) {
      registered.push(tool);
    },
    on(event, handler) {
      handlers[event] = handler;
    },
  };
}

test("registers exactly the agent tools (request/wait/reply/rebind/recovery)", () => {
  const pi = fakePi();
  agentMailboxExtension(pi, {});
  assert.deepEqual(
    pi.registered.map((t) => t.name),
    TOOL_NAMES
  );
  assert.deepEqual(TOOL_NAMES, [
    "agent_request",
    "agent_wait",
    "agent_reply",
    "agent_rebind",
    "agent_list",
    "agent_pause",
    "agent_resume",
    "agent_cancel",
  ]);
});

test("each tool declares parameters and an execute function", () => {
  for (const tool of createTools()) {
    assert.equal(typeof tool.execute, "function", `${tool.name}.execute`);
    assert.equal(tool.parameters.type, "object", `${tool.name}.parameters`);
    assert.ok(tool.description, `${tool.name}.description`);
  }
});

test("no scaffold stubs remain once all three tools are implemented (unit-004)", () => {
  const scaffolded = createTools().filter((t) => t.details?.scaffold || t.execute?.name === "stubExecute");
  assert.deepEqual(scaffolded, []);
});

test("agent_request execute surfaces an error result when the mailbox dir is missing", async () => {
  // mailboxDir: "" pins the missing-dir condition instead of falling through
  // to storeDir() (R5.F1); env: {} keeps the runner's pane env out of it.
  const tool = createTools({ mailboxDir: "", env: {} }).find((t) => t.name === "agent_request");
  const result = await tool.execute("tc-2", { worker: "w", instruction: "i" });
  assert.equal(result.details.error, true);
  assert.match(result.content[0].text, /^agent_request failed: mailboxDir required/);
});

// R1.F2: anonymous requester fail-fast — agent_request and agent_wait both
// reject an unbound pane instead of proceeding as "anonymous".
test("agent_request execute fails fast for a pane with no bound identity", async () => {
  const mailboxDir = await mkdtemp(join(tmpdir(), "agent-mailbox-reg-"));
  const tool = createTools({ mailboxDir, paneName: "unbound-pane" }).find(
    (t) => t.name === "agent_request",
  );
  const result = await tool.execute("tc-r1f2a", { worker: "w", instruction: "i" });
  assert.equal(result.details.error, true);
  assert.match(
    result.content[0].text,
    /pane "unbound-pane" has no bound session identity/,
  );
  // R2.F5: the remediation tail names both identity variables.
  assert.match(
    result.content[0].text,
    /\(AGENT_PANE, HERDR_PANE_ID, or HC_TERMINAL_ID set\) before it can request/,
  );
});

test("agent_request execute fails fast when no pane name is set", async () => {
  const mailboxDir = await mkdtemp(join(tmpdir(), "agent-mailbox-reg-"));
  // env: {} isolates the test from the runner's own pane environment (this
  // suite itself can run inside a herdr pane where HERDR_PANE_ID is set).
  const tool = createTools({ mailboxDir, env: {} }).find((t) => t.name === "agent_request");
  const result = await tool.execute("tc-r1f2b", { worker: "w", instruction: "i" });
  assert.equal(result.details.error, true);
  assert.match(result.content[0].text, /no pane name \(AGENT_PANE, HERDR_PANE_ID, or HC_TERMINAL_ID\) is set/);
});

test("agent_wait execute fails fast for a pane with no bound identity", async () => {
  const mailboxDir = await mkdtemp(join(tmpdir(), "agent-mailbox-reg-"));
  const tool = createTools({ mailboxDir, paneName: "unbound-pane" }).find(
    (t) => t.name === "agent_wait",
  );
  const result = await tool.execute("tc-r1f2c", { requestId: "req-1" });
  assert.equal(result.details.error, true);
  assert.match(
    result.content[0].text,
    /pane "unbound-pane" has no bound session identity/,
  );
});

test("agent_wait execute surfaces an error result when the mailbox dir is missing", async () => {
  const tool = createTools({ mailboxDir: "", env: {} }).find((t) => t.name === "agent_wait");
  const result = await tool.execute("tc-3", { requestId: "req-1" });
  assert.equal(result.details.error, true);
  assert.match(result.content[0].text, /^agent_wait failed: mailboxDir required/);
});

test("session_start binds the pane identity under the mailbox dir namespace", async () => {
  const mailboxDir = await mkdtemp(join(tmpdir(), "agent-mailbox-"));
  const pi = fakePi();
  agentMailboxExtension(pi, { mailboxDir, paneName: "worker-a", sessionId: "sess-1" });
  await pi.handlers.session_start({}, {});
  const { resolvePane } = await import("../agent-mailbox/identity.mjs");
  const binding = await resolvePane({ mailboxDir, paneName: "worker-a" });
  assert.equal(binding.sessionId, "sess-1");
});

test("session_start binds under the default store path when MAILBOX_DIR is unset (R5.F1)", async () => {
  const tempHome = await mkdtemp(join(tmpdir(), "agent-mailbox-home-"));
  const prevHome = process.env.HOME;
  const prevMailboxDir = process.env.MAILBOX_DIR;
  delete process.env.MAILBOX_DIR;
  process.env.HOME = tempHome;
  try {
    const pi = fakePi();
    // No mailboxDir option: the extension must fall back to storeDir(),
    // which resolves under the (temporary) HOME.
    agentMailboxExtension(pi, { paneName: "worker-a", sessionId: "sess-default" });
    await pi.handlers.session_start({}, {});
    const expectedPath = join(tempHome, ".local", "share", "mailbox", "ext", "session-identities.json");
    const raw = JSON.parse(await readFile(expectedPath, "utf8"));
    assert.equal(raw["worker-a"].sessionId, "sess-default");
  } finally {
    if (prevHome === undefined) delete process.env.HOME;
    else process.env.HOME = prevHome;
    if (prevMailboxDir === undefined) delete process.env.MAILBOX_DIR;
    else process.env.MAILBOX_DIR = prevMailboxDir;
  }
});

test("session_start without an obtainable session id refuses to bind (R1.F5)", async () => {
  const mailboxDir = await mkdtemp(join(tmpdir(), "agent-mailbox-"));
  const pi = fakePi();
  agentMailboxExtension(pi, { mailboxDir, paneName: "worker-a" });
  await assert.rejects(
    () => pi.handlers.session_start({}, {}),
    /refusing to fall back to the pane name/,
  );
  const { resolvePane } = await import("../agent-mailbox/identity.mjs");
  assert.equal(await resolvePane({ mailboxDir, paneName: "worker-a" }), null);
});

test("anonymous pane (no AGENT_PANE) skips identity binding", async () => {
  const mailboxDir = await mkdtemp(join(tmpdir(), "agent-mailbox-"));
  const pi = fakePi();
  agentMailboxExtension(pi, { mailboxDir, env: {} });
  await pi.handlers.session_start({}, {});
  const { resolvePane } = await import("../agent-mailbox/identity.mjs");
  assert.equal(await resolvePane({ mailboxDir, paneName: "anything" }), null);
});

// #77 acceptance: a root pane (no explicit paneName, no AGENT_PANE) must
// self-bind from its manager's per-pane variable — HC_TERMINAL_ID for the
// herdr-app / hc desktop client and HERDR_PANE_ID for the herdr TUI.
/**
 * Claim block (issue#77):
 *   claim id: agent-mailbox-77/root-pane-self-bind
 *   claim: a root pane self-binds from its manager's per-pane variable
 *     (HC_TERMINAL_ID for herdr-app/hc, HERDR_PANE_ID for the herdr TUI)
 *     even without AGENT_PANE, and can dispatch and wait as a requester
 *   scenario: Given a root pane whose env sets only its per-pane variable
 *     Then session_start binds the per-pane name
 *     And two distinct per-pane values bind distinct identities
 *     And agent_request dispatches from that binding and agent_wait returns
 *     the worker's outcome
 */
test("#77: root pane binds from HC_TERMINAL_ID and dispatches/waits as requester", async () => {
  const mailboxDir = await mkdtemp(join(tmpdir(), "agent-mailbox-hc-"));
  const { bindPane, resolvePane } = await import("../agent-mailbox/identity.mjs");
  await bindPane({ mailboxDir, paneName: "worker-b", sessionId: "sess-worker-b" });

  const env = { HC_TERMINAL_ID: "t1c" };
  const pi = fakePi();
  agentMailboxExtension(pi, { mailboxDir, env, sessionId: "sess-hc" });
  await pi.handlers.session_start({}, {});
  assert.equal((await resolvePane({ mailboxDir, paneName: "t1c" })).sessionId, "sess-hc");

  const request = pi.registered.find((t) => t.name === "agent_request");
  const dispatched = await request.execute("tc-hc-req", { worker: "worker-b", instruction: "i" });
  assert.equal(dispatched.details.error, undefined);
  const { requestId } = dispatched.details;

  const { replyOutcome } = await import("../agent-mailbox/reply.mjs");
  await replyOutcome({ mailboxDir, requestId, status: "DONE", report: "ok", workerPane: "worker-b" });

  const wait = pi.registered.find((t) => t.name === "agent_wait");
  const waited = await wait.execute("tc-hc-wait", { requestId, timeoutMs: 1000 });
  assert.equal(waited.details.status, "outcome");
  assert.equal(waited.details.reply.status, "DONE");
});

test("#77: root pane binds from HERDR_PANE_ID at session_start", async () => {
  const mailboxDir = await mkdtemp(join(tmpdir(), "agent-mailbox-herdr-"));
  const env = { HERDR_PANE_ID: "pane-tui" };
  const pi = fakePi();
  agentMailboxExtension(pi, { mailboxDir, env, sessionId: "sess-tui" });
  await pi.handlers.session_start({}, {});
  const { resolvePane } = await import("../agent-mailbox/identity.mjs");
  assert.equal((await resolvePane({ mailboxDir, paneName: "pane-tui" })).sessionId, "sess-tui");
});

test("#77: distinct per-pane terminal ids bind distinct identities", async () => {
  const mailboxDir = await mkdtemp(join(tmpdir(), "agent-mailbox-hc2-"));
  const pi1 = fakePi();
  agentMailboxExtension(pi1, { mailboxDir, env: { HC_TERMINAL_ID: "t1c" }, sessionId: "sess-1" });
  await pi1.handlers.session_start({}, {});
  const pi2 = fakePi();
  agentMailboxExtension(pi2, { mailboxDir, env: { HC_TERMINAL_ID: "t2d" }, sessionId: "sess-2" });
  await pi2.handlers.session_start({}, {});
  const { resolvePane } = await import("../agent-mailbox/identity.mjs");
  assert.equal((await resolvePane({ mailboxDir, paneName: "t1c" })).sessionId, "sess-1");
  assert.equal((await resolvePane({ mailboxDir, paneName: "t2d" })).sessionId, "sess-2");
});

// R2.F5/#77: remediation strings name every identity variable — every
// no-identity error message tells the agent that AGENT_PANE, HERDR_PANE_ID,
// or HC_TERMINAL_ID (not just AGENT_PANE) provides the pane name.
/**
 * Claim block (unit-004):
 *   claim id: mailbox-ext-R2F5/1
 *   claim: all no-identity error messages name AGENT_PANE, HERDR_PANE_ID,
 *     and HC_TERMINAL_ID, and agent_rebind's message names `pane`,
 *     AGENT_PANE, HERDR_PANE_ID, or HC_TERMINAL_ID
 *   scenario: Given a tool invocation that hits a no-identity/unknown-pane
 *     remediation path
 *     Then the error text names all three identity variables (or the
 *     rebind parameter alternatives)
 */
test("request to an unbound worker pane names all identity variables (R2.F5)", async () => {
  const mailboxDir = await mkdtemp(join(tmpdir(), "agent-mailbox-reg-"));
  // Bind the requester so the failure lands on the worker-unknown path.
  const pi = fakePi();
  agentMailboxExtension(pi, { mailboxDir, paneName: "requester-a", sessionId: "sess-req" });
  await pi.handlers.session_start({}, {});
  const tool = createTools({ mailboxDir, paneName: "requester-a" }).find(
    (t) => t.name === "agent_request",
  );
  const result = await tool.execute("tc-r2f5a", { worker: "ghost-pane", instruction: "i" });
  assert.equal(result.details.error, true);
  assert.match(
    result.content[0].text,
    /unknown worker pane "ghost-pane".*\(AGENT_PANE, HERDR_PANE_ID, or HC_TERMINAL_ID set\) before it can be addressed/,
  );
});

test("reply from an unbound worker pane names all identity variables (R2.F5)", async () => {
  const mailboxDir = await mkdtemp(join(tmpdir(), "agent-mailbox-reg-"));
  const tool = createTools({ mailboxDir, paneName: "unbound-worker" }).find(
    (t) => t.name === "agent_reply",
  );
  const result = await tool.execute("tc-r2f5b", { requestId: "req-1", status: "DONE" });
  assert.equal(result.details.error, true);
  assert.match(
    result.content[0].text,
    /unknown worker pane "unbound-worker".*\(AGENT_PANE, HERDR_PANE_ID, or HC_TERMINAL_ID set\) before it can reply/,
  );
});

test("wait from an unbound pane names all identity variables (R2.F5)", async () => {
  const mailboxDir = await mkdtemp(join(tmpdir(), "agent-mailbox-reg-"));
  const tool = createTools({ mailboxDir, paneName: "unbound-waiter" }).find(
    (t) => t.name === "agent_wait",
  );
  const result = await tool.execute("tc-r2f5c", { requestId: "req-1" });
  assert.equal(result.details.error, true);
  assert.match(
    result.content[0].text,
    /pane "unbound-waiter" has no bound session identity.*\(AGENT_PANE, HERDR_PANE_ID, or HC_TERMINAL_ID set\) before it can wait/,
  );
});

test("agent_rebind without a pane name names pane, AGENT_PANE, HERDR_PANE_ID, or HC_TERMINAL_ID (R2.F5)", async () => {
  const mailboxDir = await mkdtemp(join(tmpdir(), "agent-mailbox-reg-"));
  const tool = createTools({ mailboxDir, env: {} }).find((t) => t.name === "agent_rebind");
  const result = await tool.execute("tc-r2f5d", {});
  assert.equal(result.details.error, true);
  assert.match(
    result.content[0].text,
    /pane name required \(param `pane`, AGENT_PANE, HERDR_PANE_ID, or HC_TERMINAL_ID\)/,
  );
});
