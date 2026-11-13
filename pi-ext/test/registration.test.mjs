// Tool registration unit tests (scaffold contract, unit-001).
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
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
  const tool = createTools().find((t) => t.name === "agent_request");
  const result = await tool.execute("tc-2", { worker: "w", instruction: "i" });
  assert.equal(result.details.error, true);
  assert.match(result.content[0].text, /^agent_request failed:/);
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
    /\(AGENT_PANE\/HERDR_PANE_ID set\) before it can request/,
  );
});

test("agent_request execute fails fast when no pane name is set", async () => {
  const mailboxDir = await mkdtemp(join(tmpdir(), "agent-mailbox-reg-"));
  // env: {} isolates the test from the runner's own pane environment (this
  // suite itself can run inside a herdr pane where HERDR_PANE_ID is set).
  const tool = createTools({ mailboxDir, env: {} }).find((t) => t.name === "agent_request");
  const result = await tool.execute("tc-r1f2b", { worker: "w", instruction: "i" });
  assert.equal(result.details.error, true);
  assert.match(result.content[0].text, /no pane name \(AGENT_PANE\/HERDR_PANE_ID\) is set/);
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
  const tool = createTools().find((t) => t.name === "agent_wait");
  const result = await tool.execute("tc-3", { requestId: "req-1" });
  assert.equal(result.details.error, true);
  assert.match(result.content[0].text, /^agent_wait failed:/);
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

// R2.F5: remediation strings name both identity variables — every
// no-identity error message tells the agent that AGENT_PANE or
// HERDR_PANE_ID (not just AGENT_PANE) provides the pane name.
/**
 * Claim block (unit-004):
 *   claim id: mailbox-ext-R2F5/1
 *   claim: all no-identity error messages name AGENT_PANE/HERDR_PANE_ID,
 *     and agent_rebind's message names `pane`, AGENT_PANE, or HERDR_PANE_ID
 *   scenario: Given a tool invocation that hits a no-identity/unknown-pane
 *     remediation path
 *     Then the error text names both AGENT_PANE and HERDR_PANE_ID (or the
 *     rebind parameter alternatives)
 */
test("request to an unbound worker pane names AGENT_PANE/HERDR_PANE_ID (R2.F5)", async () => {
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
    /unknown worker pane "ghost-pane".*\(AGENT_PANE\/HERDR_PANE_ID set\) before it can be addressed/,
  );
});

test("reply from an unbound worker pane names AGENT_PANE/HERDR_PANE_ID (R2.F5)", async () => {
  const mailboxDir = await mkdtemp(join(tmpdir(), "agent-mailbox-reg-"));
  const tool = createTools({ mailboxDir, paneName: "unbound-worker" }).find(
    (t) => t.name === "agent_reply",
  );
  const result = await tool.execute("tc-r2f5b", { requestId: "req-1", status: "DONE" });
  assert.equal(result.details.error, true);
  assert.match(
    result.content[0].text,
    /unknown worker pane "unbound-worker".*\(AGENT_PANE\/HERDR_PANE_ID set\) before it can reply/,
  );
});

test("wait from an unbound pane names AGENT_PANE/HERDR_PANE_ID (R2.F5)", async () => {
  const mailboxDir = await mkdtemp(join(tmpdir(), "agent-mailbox-reg-"));
  const tool = createTools({ mailboxDir, paneName: "unbound-waiter" }).find(
    (t) => t.name === "agent_wait",
  );
  const result = await tool.execute("tc-r2f5c", { requestId: "req-1" });
  assert.equal(result.details.error, true);
  assert.match(
    result.content[0].text,
    /pane "unbound-waiter" has no bound session identity.*\(AGENT_PANE\/HERDR_PANE_ID set\) before it can wait/,
  );
});

test("agent_rebind without a pane name names pane, AGENT_PANE, or HERDR_PANE_ID (R2.F5)", async () => {
  const mailboxDir = await mkdtemp(join(tmpdir(), "agent-mailbox-reg-"));
  const tool = createTools({ mailboxDir, env: {} }).find((t) => t.name === "agent_rebind");
  const result = await tool.execute("tc-r2f5d", {});
  assert.equal(result.details.error, true);
  assert.match(
    result.content[0].text,
    /pane name required \(param `pane`, AGENT_PANE, or HERDR_PANE_ID\)/,
  );
});
