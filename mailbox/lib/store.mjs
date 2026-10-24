// Persistent store for the mailbox service (issue #41).
//
// One JSON file per request under the store directory. Same host, same OS
// user: the default location is $MAILBOX_DIR or ~/.local/share/mailbox.
// Writes are atomic (tmp file + rename) so a crash never leaves a torn file.

import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export class StoreError extends Error {}

export function storeDir() {
  return process.env.MAILBOX_DIR || path.join(os.homedir(), ".local", "share", "mailbox");
}

function recordPath(dir, requestId) {
  if (!/^[A-Za-z0-9._-]+$/.test(requestId)) {
    throw new StoreError(`invalid requestId: ${JSON.stringify(requestId)}`);
  }
  return path.join(dir, `${requestId}.json`);
}

export async function load(dir, requestId) {
  let raw;
  try {
    raw = await fs.promises.readFile(recordPath(dir, requestId), "utf8");
  } catch (err) {
    if (err.code === "ENOENT") return null;
    throw err;
  }
  return JSON.parse(raw);
}

export async function save(dir, record) {
  await fs.promises.mkdir(dir, { recursive: true });
  const target = recordPath(dir, record.requestId);
  const tmp = `${target}.tmp.${process.pid}.${Date.now()}`;
  const data = JSON.stringify(record, null, 2) + "\n";
  const fh = await fs.promises.open(tmp, "w");
  try {
    await fh.writeFile(data);
    await fh.sync();
  } finally {
    await fh.close();
  }
  await fs.promises.rename(tmp, target);
}

export async function exists(dir, requestId) {
  try {
    await fs.promises.access(recordPath(dir, requestId));
    return true;
  } catch {
    return false;
  }
}

export async function list(dir, { pendingOnly = false } = {}) {
  let names;
  try {
    names = await fs.promises.readdir(dir);
  } catch (err) {
    if (err.code === "ENOENT") return [];
    throw err;
  }
  const records = [];
  for (const name of names) {
    if (!name.endsWith(".json")) continue;
    const record = JSON.parse(await fs.promises.readFile(path.join(dir, name), "utf8"));
    if (pendingOnly && !isPending(record)) continue;
    records.push(record);
  }
  records.sort((a, b) => a.requestId.localeCompare(b.requestId));
  return records;
}

// Pending = a live reply expectation: registered (dispatched or not), no
// reply bound, and not cancelled. Matches the feature file's "discoverable
// as pending".
export function isPending(record) {
  return (record.reply === null || record.reply === undefined) && record.state !== "cancelled";
}
