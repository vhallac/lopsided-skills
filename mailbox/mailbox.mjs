#!/usr/bin/env node
// Mailbox service CLI (issue #41): persists and correlates request-reply
// pairs. Surface: register, dispatch, list, show, reply, consume, pause,
// resume, rebind, cancel. Delivery is exactly-once to the registered
// requester identity, guarded by pause and explicit rebind.

import { StoreError, exists, isPending, list, load, save, storeDir } from "./lib/store.mjs";

export const STATUS_VOCABULARY = ["DONE", "NEEDS_INPUT", "BLOCKED", "FAILED"];

const STATUS_EXIT = { usage: 2, rejected: 3, notFound: 4 };

function usage() {
  return `mailbox — persist and correlate request-reply pairs (same host, same OS user)

Usage:
  mailbox register --id <requestId> --requester <identity> --worker <identity> --instruction <text>
  mailbox dispatch --id <requestId>
  mailbox list [--pending]
  mailbox show --id <requestId>
  mailbox reply --id <requestId> --worker <identity> --status <STATUS> [--report <text>]
  mailbox consume --id <requestId> --requester <identity>
  mailbox pause --id <requestId>
  mailbox resume --id <requestId>
  mailbox rebind --id <requestId> --requester <new-identity>
  mailbox cancel --id <requestId>

Environment:
  MAILBOX_DIR   store directory (default: ~/.local/share/mailbox)

Status vocabulary: DONE, NEEDS_INPUT, BLOCKED, FAILED`;
}

function fail(code, message) {
  console.error(`mailbox: ${message}`);
  process.exit(code);
}

function parseArgs(argv) {
  const opts = {};
  const positional = [];
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (!arg.startsWith("--")) {
      positional.push(arg);
      continue;
    }
    if (arg === "--pending") { opts.pending = true; continue; }
    const value = argv[++i];
    if (value === undefined || value.startsWith("--")) fail(STATUS_EXIT.usage, `${arg} requires a value`);
    opts[arg.slice(2)] = value;
  }
  return { opts, positional };
}

function requireOpts(opts, names) {
  for (const name of names) {
    if (!opts[name]) fail(STATUS_EXIT.usage, `--${name} is required`);
  }
}

async function main(argv) {
  const [command, ...rest] = argv;
  const dir = storeDir();
  const { opts, positional } = parseArgs(rest);
  if (positional.length) fail(STATUS_EXIT.usage, `unexpected argument: ${positional[0]}`);

  switch (command) {
    case "register": {
      requireOpts(opts, ["id", "requester", "worker", "instruction"]);
      const requestId = opts.id;
      if (await exists(dir, requestId)) {
        // Re-registration with a live expectation is rejected; the original
        // request is left unchanged (feature scenario 2).
        fail(STATUS_EXIT.rejected, `request "${requestId}" already has a live expectation; registration rejected, original unchanged`);
      }
      const record = {
        requestId,
        requester: opts.requester,
        worker: opts.worker,
        instruction: opts.instruction,
        state: "pending", // pending | dispatched
        registeredAt: new Date().toISOString(),
        dispatchedAt: null,
        reply: null,
        rejectedReplies: [],
        delivered: false,
        deliveredAt: null,
        paused: false,
        deliveryAttempts: [],
      };
      await save(dir, record);
      console.log(`registered ${requestId} (pending)`);
      break;
    }
    case "dispatch": {
      requireOpts(opts, ["id"]);
      const record = await load(dir, opts.id);
      if (!record) fail(STATUS_EXIT.notFound, `no request "${opts.id}"`);
      if (record.state === "dispatched") {
        console.log(`dispatched ${opts.id} (already dispatched; no-op)`);
        break;
      }
      record.state = "dispatched";
      record.dispatchedAt = new Date().toISOString();
      await save(dir, record);
      console.log(`dispatched ${opts.id}`);
      break;
    }
    case "reply": {
      requireOpts(opts, ["id", "worker", "status"]);
      const requestId = opts.id;
      const record = await load(dir, requestId);
      if (!record) fail(STATUS_EXIT.notFound, `no request "${requestId}"`);
      if (!STATUS_VOCABULARY.includes(opts.status)) {
        // Reply must use the status vocabulary; non-vocabulary statuses are
        // rejected before any correlation.
        fail(STATUS_EXIT.rejected, `status "${opts.status}" is outside the vocabulary (${STATUS_VOCABULARY.join(", ")}); reply rejected`);
      }
      if (record.worker !== opts.worker) {
        // Replaced worker identity cannot bind a reply (feature scenario 5):
        // the attempt is rejected and kept inspectable on the record; the
        // request keeps no outcome bound to the new session.
        record.rejectedReplies.push({
          worker: opts.worker,
          status: opts.status,
          report: opts.report ?? null,
          rejectedAt: new Date().toISOString(),
        });
        await save(dir, record);
        fail(STATUS_EXIT.rejected, `reply for "${requestId}" rejected: submitting worker "${opts.worker}" does not match the dispatched worker identity "${record.worker}"; attempt recorded`);
      }
      if (record.reply) {
        // Duplicate reply keeps the first — one logical delivery (scenario 4).
        console.log(`reply for ${requestId} ignored: first reply (${record.reply.status}) already persisted`);
        break;
      }
      // Reply persists against the original requestId only (scenario 3).
      record.reply = {
        status: opts.status,
        report: opts.report ?? null,
        worker: opts.worker,
        submittedAt: new Date().toISOString(),
      };
      await save(dir, record);
      console.log(`reply recorded for ${requestId} (${opts.status})`);
      break;
    }
    case "consume": {
      requireOpts(opts, ["id", "requester"]);
      const requestId = opts.id;
      const record = await load(dir, requestId);
      if (!record) fail(STATUS_EXIT.notFound, `no request "${requestId}"`);
      if (record.state === "cancelled") {
        fail(STATUS_EXIT.rejected, `request "${requestId}" is cancelled; no delivery`);
      }
      const note = (result) => {
        record.deliveryAttempts.push({ requester: opts.requester, result, at: new Date().toISOString() });
        return save(dir, record);
      };
      if (record.requester !== opts.requester) {
        // Requester identity change refuses delivery until an explicit rebind
        // (feature scenario 10); the refusal stays inspectable.
        await note("refused-identity-change");
        fail(STATUS_EXIT.rejected, `delivery for "${requestId}" refused: consuming identity "${opts.requester}" does not match the registered requester "${record.requester}"; explicit rebind required`);
      }
      if (!record.reply) {
        await note("no-settled-reply");
        console.log(`no settled reply for ${requestId}; nothing to consume`);
        break;
      }
      if (record.paused) {
        // Paused requester holds the reply as inspectable state; no delivery
        // is attempted while paused (feature scenario 9).
        await note("held-paused");
        console.log(`delivery for ${requestId} held: requester is paused (reply stays persisted)`);
        break;
      }
      if (record.delivered) {
        // Exactly-once consumption: a late re-delivery attempt after
        // consumption is a no-op (feature scenario 6).
        console.log(`reply for ${requestId} already delivered; re-delivery is a no-op`);
        break;
      }
      // Delivery to the registered requester identity (feature scenarios 6
      // and 8): an unreachable requester simply has not consumed yet — the
      // reply stays persisted and a later consume delivers it.
      record.delivered = true;
      record.deliveredAt = new Date().toISOString();
      await note("delivered");
      console.log(`delivered reply for ${requestId}: ${record.reply.status}${record.reply.report ? ` — ${record.reply.report}` : ""}`);
      break;
    }
    case "pause": {
      requireOpts(opts, ["id"]);
      const record = await load(dir, opts.id);
      if (!record) fail(STATUS_EXIT.notFound, `no request "${opts.id}"`);
      if (record.paused) {
        console.log(`request ${opts.id} already paused (no-op)`);
        break;
      }
      record.paused = true;
      await save(dir, record);
      console.log(`paused ${opts.id} (delivery held while paused)`);
      break;
    }
    case "resume": {
      requireOpts(opts, ["id"]);
      const record = await load(dir, opts.id);
      if (!record) fail(STATUS_EXIT.notFound, `no request "${opts.id}"`);
      if (!record.paused) {
        console.log(`request ${opts.id} not paused (no-op)`);
        break;
      }
      record.paused = false;
      await save(dir, record);
      console.log(`resumed ${opts.id} (delivery may proceed)`);
      break;
    }
    case "rebind": {
      requireOpts(opts, ["id", "requester"]);
      const record = await load(dir, opts.id);
      if (!record) fail(STATUS_EXIT.notFound, `no request "${opts.id}"`);
      if (record.requester === opts.requester) {
        console.log(`request ${opts.id} already bound to requester "${opts.requester}" (no-op)`);
        break;
      }
      // Explicit rebind is the only path past the identity-change refusal.
      record.rebinds ??= [];
      record.rebinds.push({ from: record.requester, to: opts.requester, at: new Date().toISOString() });
      record.requester = opts.requester;
      await save(dir, record);
      console.log(`rebound ${opts.id} to requester "${opts.requester}"`);
      break;
    }
    case "cancel": {
      requireOpts(opts, ["id"]);
      const record = await load(dir, opts.id);
      if (!record) fail(STATUS_EXIT.notFound, `no request "${opts.id}"`);
      if (record.state === "cancelled") {
        console.log(`request ${opts.id} already cancelled (no-op)`);
        break;
      }
      record.state = "cancelled";
      await save(dir, record);
      console.log(`cancelled ${opts.id} (no further delivery)`);
      break;
    }
    case "list": {
      const records = await list(dir, { pendingOnly: Boolean(opts.pending) });
      for (const record of records) {
        console.log(`${record.requestId}\t${record.state}\t${isPending(record) ? "no-outcome" : "has-outcome"}`);
      }
      break;
    }
    case "show": {
      requireOpts(opts, ["id"]);
      const record = await load(dir, opts.id);
      if (!record) fail(STATUS_EXIT.notFound, `no request "${opts.id}"`);
      console.log(JSON.stringify(record, null, 2));
      break;
    }
    default:
      fail(STATUS_EXIT.usage, `unknown command: ${command ?? "(none)"}\n\n${usage()}`);
  }
}

main(process.argv.slice(2)).catch((err) => {
  if (err instanceof StoreError) {
    console.error(`mailbox: ${err.message}`);
    process.exit(STATUS_EXIT.usage);
  }
  throw err;
});
