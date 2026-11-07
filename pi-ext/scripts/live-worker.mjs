// Live worker harness for unit-009 (issue#42 live acceptance, two herdr panes).
// Runs in the worker pane B with AGENT_PANE (or HERDR_PANE_ID) and MAILBOX_DIR
// set. Binds the pane name to a fresh session identity (exactly what the
// extension's session_start handler does), then reacts to dispatched requests
// through the real mailbox CLI subprocess:
//   - ordinary request  -> agent_reply semantics: DONE + "live-ok" report
//   - LIVE-SETTLE tag   -> settlePendingOnShutdown (EXT-3a path), then exit
// Every reply/settle is mirrored to a sync file so the requester pane can
// order its assertions without polling the mailbox store itself.
import { randomUUID } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";

import { bindPane } from "../agent-mailbox/identity.mjs";
import { replyOutcome } from "../agent-mailbox/reply.mjs";
import { runMailbox } from "../agent-mailbox/request.mjs";
import { settlePendingOnShutdown } from "../agent-mailbox/settle.mjs";

const mailboxDir = process.env.MAILBOX_DIR;
const paneName = process.env.AGENT_PANE ?? process.env.HERDR_PANE_ID ?? null;
if (!mailboxDir || !paneName) {
  console.error("LIVE-WORKER-FATAL: MAILBOX_DIR and AGENT_PANE/HERDR_PANE_ID are required");
  process.exit(2);
}
const syncDir = join(mailboxDir, "ext", "acc-sync");
const sessionId = process.env.LIVE_SESSION_ID ?? `worker-${randomUUID()}`;

await bindPane({ mailboxDir, paneName, sessionId });
console.log(`LIVE-WORKER-UP pane=${paneName} session=${sessionId}`);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

for (;;) {
  const listed = await runMailbox({ mailboxDir, args: ["list"] });
  if (listed.code !== 0) {
    await sleep(200);
    continue;
  }
  const ids = listed.stdout
    .split("\n")
    .map((l) => l.split("\t")[0].trim())
    .filter(Boolean);
  let acted = false;
  for (const requestId of ids) {
    const shown = await runMailbox({ mailboxDir, args: ["show", "--id", requestId] });
    if (shown.code !== 0) continue;
    let record;
    try {
      record = JSON.parse(shown.stdout);
    } catch {
      continue;
    }
    if (record.worker !== sessionId || record.reply) continue;
    if ((record.instruction ?? "").includes("LIVE-SETTLE")) {
      // EXT-3a live path: the worker settles without agent_reply — the same
      // sweep the extension's session_shutdown handler performs. The harness
      // models the shutdown handler (the observable behavior is the persisted
      // FAILED outcome) but keeps serving so the same live run can continue
      // with later checks; a second sweep of the same request is a no-op.
      const { settled } = await settlePendingOnShutdown({ mailboxDir, workerIdentity: sessionId });
      await mkdir(syncDir, { recursive: true });
      await writeFile(join(syncDir, `settled-${requestId}`), new Date().toISOString());
      console.log(`LIVE-WORKER-SETTLED ${settled.join(",")}`);
      continue;
    }
    await replyOutcome({
      mailboxDir,
      requestId,
      status: "DONE",
      report: `live-ok: ${record.instruction ?? ""}`.trim(),
      workerIdentity: sessionId,
    });
    await mkdir(syncDir, { recursive: true });
    await writeFile(join(syncDir, `replied-${requestId}`), new Date().toISOString());
    console.log(`LIVE-WORKER-REPLIED ${requestId}`);
    acted = true;
  }
  if (!acted) await sleep(150);
}
