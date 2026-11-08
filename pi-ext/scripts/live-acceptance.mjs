// Herdr-driven live acceptance orchestrator for unit-009 (issue#42).
// Creates two panes in the current herdr session, runs the worker harness in
// one and the requester harness in the other (real processes, real herdr
// panes, real mailbox CLI subprocesses, shared MAILBOX_DIR), then polls the
// logs until the requester reports all six ACC checks passed.
//
// Usage: node pi-ext/scripts/live-acceptance.mjs [--keep-panes]
// Exits 0 iff LIVE-ALL-PASS is observed.
//
// Claim-block key (R1.F3): the six #40 acceptance checks this orchestrator
// gates on are the six claim blocks in pi-ext/scripts/live-requester.mjs,
// one per check id. LIVE-ACCEPTANCE-PASS is emitted only when every id below
// printed ACC-PASS in the requester log:
//   claim id: mailbox-ext-ACC/reply-before-wait
//   claim id: mailbox-ext-ACC/reply-during-tool-rounds
//   claim id: mailbox-ext-ACC/blocked-wait-released
//   claim id: mailbox-ext-ACC/duplicate-notification
//   claim id: mailbox-ext-ACC/worker-stops-without-replying
//   claim id: mailbox-ext-ACC/session-restart-replacement
import { execFile } from "node:child_process";
import { mkdir, readFile, rm } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { promisify } from "node:util";

const run = promisify(execFile);
const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(here, "..", "..");
const workDir = "/tmp/issue-42-live";
const mailboxDir = join(workDir, "mailbox");
const logsDir = join(workDir, "logs");

const keepPanes = process.argv.includes("--keep-panes");

async function herdr(args) {
  const { stdout } = await run("herdr", args, { cwd: repoRoot, timeout: 60000 });
  return stdout;
}
function paneIdFrom(json) {
  const line = json.split("\n").find((l) => l.trim().startsWith("{"));
  const parsed = JSON.parse(line);
  return parsed?.result?.pane?.pane_id ?? null;
}

await rm(workDir, { recursive: true, force: true });
await mkdir(logsDir, { recursive: true });
await mkdir(mailboxDir, { recursive: true });

const panes = [];
try {
  // Two sibling panes, same cwd as this process (the worktree root).
  const a = paneIdFrom(await herdr(["pane", "split", "--current", "--direction", "down", "--cwd", repoRoot, "--no-focus"]));
  const b = paneIdFrom(await herdr(["pane", "split", "--current", "--direction", "down", "--cwd", repoRoot, "--no-focus"]));
  if (!a || !b) throw new Error(`pane split failed: a=${a} b=${b}`);
  panes.push(a, b);
  console.log(`LIVE-PANES requester=${a} worker=${b}`);

  // HERDR_PANE_ID is what a real herdr pane inherits (#67); injecting it
  // exercises the extension's fallback instead of the AGENT_PANE override.
  const env = (pane) => `MAILBOX_DIR=${mailboxDir} HERDR_PANE_ID=${pane}`;
  await herdr([
    "pane", "run", b,
    `cd ${repoRoot} && ${env(b)} LIVE_WORKER_PANE=${a} node pi-ext/scripts/live-worker.mjs > ${logsDir}/worker.log 2>&1`,
  ]);
  await herdr([
    "pane", "run", a,
    `cd ${repoRoot} && ${env(a)} LIVE_WORKER_PANE=${b} node pi-ext/scripts/live-requester.mjs > ${logsDir}/requester.log 2>&1`,
  ]);

  const deadline = Date.now() + 120_000;
  let outcome = null;
  for (;;) {
    const requesterLog = await readFile(join(logsDir, "requester.log"), "utf8").catch(() => "");
    if (requesterLog.includes("LIVE-ALL-PASS")) { outcome = "pass"; break; }
    if (requesterLog.includes("LIVE-ALL-FAIL") || requesterLog.includes("FATAL")) { outcome = "fail"; break; }
    if (Date.now() >= deadline) { outcome = "timeout"; break; }
    await new Promise((r) => setTimeout(r, 500));
  }

  const requesterLog = await readFile(join(logsDir, "requester.log"), "utf8").catch(() => "");
  const workerLog = await readFile(join(logsDir, "worker.log"), "utf8").catch(() => "");
  console.log("--- requester.log ---");
  console.log(requesterLog.trim() || "(empty)");
  console.log("--- worker.log ---");
  console.log(workerLog.trim() || "(empty)");

  if (outcome === "pass") {
    console.log("LIVE-ACCEPTANCE-PASS");
    process.exitCode = 0;
  } else {
    console.log(`LIVE-ACCEPTANCE-FAIL outcome=${outcome}`);
    process.exitCode = 1;
  }
} finally {
  if (!keepPanes) {
    for (const p of panes) {
      await herdr(["pane", "close", p]).catch(() => {});
    }
  }
}
