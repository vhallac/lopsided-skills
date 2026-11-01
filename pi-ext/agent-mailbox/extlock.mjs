// Exclusive lock for ext/ state files (R1.F4, decision 013's lock pattern
// applied outside the mailbox store): any load-mutate-write of a shared
// ext/ state file (session-identities.json, session-replacements.json)
// runs inside a per-file exclusive lock so two concurrent extension
// instances cannot lose each other's write.
//
// Same pattern as mailbox/lib/store.mjs withLock: exclusive create
// (open "wx") with backoff, staleness steal (a holder older than
// STALE_MS means a crashed process), busy failure on wait timeout, and
// release in finally — including when the body exits via a thrown error.
// The body MUST re-read the state under the lock (guards see committed
// state, never a stale copy); the helpers here receive only the lock.
import { rm, mkdir, open, stat } from "node:fs/promises";
import { dirname } from "node:path";

const LOCK_POLL_MS = 25;
const LOCK_WAIT_MS = 5000;
const LOCK_STALE_MS = 10000; // operations are ms-scale; a holder that lives
// longer than this (crash) lets the next contender steal the lock.

export class LockBusyError extends Error {
  constructor(target, err) {
    super(`ext state "${target}" is busy (lock held); retry later: ${err?.message ?? err}`);
    this.name = "LockBusyError";
  }
}

/** Run body() while holding an exclusive lock on <filePath>.lock. */
export async function withStateLock(filePath, body) {
  const lockPath = `${filePath}.lock`;
  await mkdir(dirname(filePath), { recursive: true });
  const deadline = Date.now() + LOCK_WAIT_MS;
  for (;;) {
    let handle;
    try {
      handle = await open(lockPath, "wx");
    } catch (err) {
      if (err.code !== "EEXIST") throw err;
      try {
        const st = await stat(lockPath);
        if (Date.now() - st.mtimeMs > LOCK_STALE_MS) {
          await rm(lockPath).catch(() => {});
          continue;
        }
      } catch { /* lock vanished between EEXIST and stat — retry */ }
      if (Date.now() > deadline) throw new LockBusyError(filePath, err);
      await new Promise((r) => setTimeout(r, LOCK_POLL_MS));
      continue;
    }
    try {
      return await body();
    } finally {
      await handle.close().catch(() => {});
      await rm(lockPath).catch(() => {});
    }
  }
}
