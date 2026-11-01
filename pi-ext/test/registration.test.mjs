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

test("registers exactly the agent tools (request/wait/reply/rebind)", () => {
  const pi = fakePi();
  agentMailboxExtension(pi, {});
  assert.deepEqual(
    pi.registered.map((t) => t.name),
    TOOL_NAMES
  );
  assert.deepEqual(TOOL_NAMES, ["agent_request", "agent_wait", "agent_reply", "agent_rebind"]);
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

test("anonymous pane (no AGENT_PANE) skips identity binding", async () => {
  const mailboxDir = await mkdtemp(join(tmpdir(), "agent-mailbox-"));
  const pi = fakePi();
  agentMailboxExtension(pi, { mailboxDir, env: {} });
  await pi.handlers.session_start({}, {});
  const { resolvePane } = await import("../agent-mailbox/identity.mjs");
  assert.equal(await resolvePane({ mailboxDir, paneName: "anything" }), null);
});
