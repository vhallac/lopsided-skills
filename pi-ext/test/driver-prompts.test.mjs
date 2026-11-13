// Prompt-contract tests for the driver surface (issue #70, issue #71).
//
// These tests read the shipped prompt text and pin the claims that the
// field-run verification (unit-004) depends on: manager-neutral steps, the
// hc identity-at-spawn binding, the absence of a manager blocking wait or a
// sleep loop, and the drive-to-completion default.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const promptsDir = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "prompts");
const PROMPT_FILES = ["plan-kick.md", "plan-drive.md"];

function readPrompt(name) {
  return readFileSync(join(promptsDir, name), "utf8");
}

function linesOf(name) {
  return readPrompt(name).split("\n");
}

function resolutionBlock(name) {
  const lines = linesOf(name);
  const start = lines.findIndex((line) => line.startsWith("## Manager resolution"));
  assert.notEqual(start, -1, `${name} carries a manager-resolution block`);
  const end = lines.findIndex((line, index) => index > start && line.startsWith("## "));
  return lines.slice(start, end === -1 ? lines.length : end);
}

const MANAGER_COMMAND =
  /\b(?:hc\s+(?:run|send|read|ls|get|wait)\b|herdr(?:-plan-agent|-drive)\b|herdr\s+(?:agent|tab)\b)/;
const BLOCKING_OR_SLEEP = /--wait\b|\bhc\s+wait\b|\bsleep\s+(?:\d+|N)\b/;

/**
 * claim: driver-prompts-BR-1/BVR-1/test_manager_commands_only_in_resolution_block
 * claim text: no prompt step names a manager-specific command; a concrete
 *   command occurs only in the manager-resolution block
 * scenario: Scenario: manager-agnostic prompts — Given prompts/plan-kick.md
 *   and prompts/plan-drive.md When every line outside the manager-resolution
 *   block is inspected Then no hc or herdr command occurs there And each
 *   manager-specific command occurs only in the resolution table
 */
test("C1: manager-specific commands occur only in the manager-resolution block", () => {
  for (const name of PROMPT_FILES) {
    const lines = linesOf(name);
    const start = lines.findIndex((line) => line.startsWith("## Manager resolution"));
    assert.notEqual(start, -1, `${name} carries a manager-resolution block`);
    const end = lines.findIndex((line, index) => index > start && line.startsWith("## "));
    const outside = [
      ...lines.slice(0, start),
      ...lines.slice(end === -1 ? lines.length : end),
    ];

    for (const line of outside) {
      assert.doesNotMatch(
        line,
        MANAGER_COMMAND,
        `${name} names a manager-specific command outside the resolution block: ${line}`
      );
    }
  }
});

/**
 * claim: driver-prompts-SC-1/1/test_hc_worker_identity_at_spawn
 * claim text: the hc start/reuse operation binds the mailbox identity at
 *   spawn (--name <pane-name>, AGENT_PANE=<pane-name> and
 *   MAILBOX_DIR=<mailbox-store>), so agent_request to the pane name reaches
 *   a bound session
 * scenario: Scenario: hc worker binds mailbox identity at a literal spawn —
 *   Given the hc rows of the manager-resolution table Then the start/reuse
 *   cell spawns with --name <pane-name> and env AGENT_PANE=<pane-name>
 *   MAILBOX_DIR=<mailbox-store> pi And the address-map cell resolves
 *   <pane-name> as the mailbox identity
 */
test("C2: the hc worker gets its mailbox identity at spawn", () => {
  const block = resolutionBlock("plan-kick.md");
  const startRow = block.find((line) => line.startsWith("| start/reuse worker |"));
  assert.ok(startRow, "plan-kick.md has an hc start/reuse row");
  const hcStart = startRow.split("|")[2]?.trim() ?? "";
  assert.match(hcStart, /\bhc run\b/);
  assert.match(hcStart, /--name <pane-name>/);
  assert.match(hcStart, /env AGENT_PANE=<pane-name> MAILBOX_DIR=<mailbox-store> pi/);

  const addressRow = block.find((line) => line.startsWith("| address map"));
  assert.ok(addressRow, "plan-kick.md has an address-map row");
  const hcAddress = addressRow.split("|")[2]?.trim() ?? "";
  assert.match(hcAddress, /\bhc ls --json\b/);
  assert.match(hcAddress, /<pane-name>/);
  assert.match(hcAddress, /mailbox identity/);
});

/**
 * claim: driver-prompts-BR-2/BVR-2/test_no_blocking_wait_or_sleep_loop
 * claim text: neither prompt uses a manager blocking wait or a sleep-based
 *   completion loop; the only wait is agent_wait on a concrete requestId
 * scenario: Scenario: request-correlated waits only — Given
 *   prompts/plan-kick.md and prompts/plan-drive.md Then no line invokes
 *   hc wait, sleep N, or --wait as a wait And every mention of those forms
 *   is a prohibition
 */
test("C3: neither prompt carries a manager blocking wait or sleep loop", () => {
  for (const name of PROMPT_FILES) {
    const offending = linesOf(name).filter((line) => BLOCKING_OR_SLEEP.test(line));
    for (const line of offending) {
      assert.match(
        line,
        /\bnever\b|\bnot\b|\bno\b/i,
        `${name} uses a blocking wait or sleep loop without prohibiting it: ${line}`
      );
    }
  }

  const drive = readPrompt("plan-drive.md");
  assert.match(drive, /agent_wait` on a concrete `requestId`/);
  assert.match(drive, /no `sleep N;` \+ read-tail cycles/);
});

/**
 * claim: driver-prompts-SC-2/4/test_drive_to_completion_by_default
 * claim text: plan-drive makes drive-to-completion the default with its stop
 *   conditions in the same session, and scopes the worker's one-unit rule to
 *   the worker's turn
 * scenario: Scenario: drive a plan to completion without an operator
 *   directive — Given prompts/plan-drive.md Then it states the default is
 *   drive to completion with its stop conditions And a clean DONE
 *   immediately dispatches the next unit in the same session And the
 *   worker's one-unit stop rule bounds only the worker's turn
 */
test("C4: plan-drive drives to completion by default", () => {
  const drive = readPrompt("plan-drive.md");

  assert.match(drive, /\*\*Default: drive to completion\.\*\*/);
  assert.match(drive, /gate status requires it\s+\(`NEEDS_INPUT`, `BLOCKED`, `FAILED`, or a reported open issue\)/);
  assert.match(drive, /plan's unit list is exhausted/);
  assert.match(drive, /immediately dispatch the next unit in the same session/);
  assert.match(drive, /a clean DONE is not an operator handback/);
  assert.match(
    drive,
    /one-unit-per-round stop\s+rule bounds only the agent's turn/
  );
  assert.match(drive, /A worker `DONE` on unit U<n> means you\n  dispatch U<n\+1> immediately/);
});
