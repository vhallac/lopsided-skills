#!/usr/bin/env python3
"""Materialize a benchmark task as a hermetic local review target (option a).

Given a `review-task/1` manifest (see `task-manifest.md`), clone the task's
source repository, check out the pinned head commit on the pinned branch, and
write a file-backed work item naming the branch and commit. The result is a
local repository plus a work item that `review-change` can resolve offline —
no forge contact, no tracker issue, no skill change. The clone is the only
network use.

Usage:
  python materialize.py --manifest task.json --out DIR [--force]

Prints a JSON summary (repo path, work-item path, resolved base/head, branch).
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tasklib import load_manifest  # noqa: E402

WORK_ITEM_TEMPLATE = """# {title}

- **tracker:** {tracker}
- **id:** {id}
- **source:** {source}
- **branch:** {branch}
- **base:** {base}
- **head:** {head}

## Description

{body}

## Acceptance criteria

- The change under review is the commit range `{base}...{head}` on branch `{branch}`.
- The reviewed revision is the head commit `{head}`.
"""


def _run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True, text=True, capture_output=True)


def _rev_parse(repo: Path, rev: str) -> str | None:
    p = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}"],
        text=True, capture_output=True,
    )
    return p.stdout.strip() if p.returncode == 0 else None


def _ensure_commit(repo: Path, rev: str) -> str:
    """Resolve a pinned commit, fetching it explicitly if the clone missed it."""
    resolved = _rev_parse(repo, rev)
    if resolved:
        return resolved
    _run(["git", "-C", str(repo), "fetch", "--quiet", "origin", rev])
    resolved = _rev_parse(repo, rev)
    if not resolved:
        raise SystemExit(f"error: pinned commit {rev!r} not found in {repo}")
    return resolved


def materialize(manifest: dict, out_dir: str | Path, force: bool = False) -> dict:
    out = Path(out_dir).resolve()
    if out.exists() and any(out.iterdir()):
        if not force:
            raise SystemExit(f"error: {out} exists and is not empty (use --force)")
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    repo = out / "repo"
    _run(["git", "clone", "--quiet", str(manifest["source"]), str(repo)])
    head = _ensure_commit(repo, str(manifest["head"]))
    base = _ensure_commit(repo, str(manifest["base"]))
    branch = manifest.get("branch") or f"review/{manifest['id']}"
    _run(["git", "-C", str(repo), "checkout", "--quiet", "-B", branch, head])

    wi = manifest.get("work_item") or {}
    text = WORK_ITEM_TEMPLATE.format(
        title=wi.get("title") or manifest["id"],
        tracker=wi.get("tracker") or "local-file",
        id=manifest["id"],
        source=manifest["source"],
        branch=branch,
        base=base,
        head=head,
        body=(wi.get("body") or "").strip(),
    )
    work_item = out / "work-item.md"
    work_item.write_text(text, encoding="utf-8")
    (out / "task.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return {
        "id": manifest["id"],
        "repo": str(repo),
        "work_item": str(work_item),
        "branch": branch,
        "base": base,
        "head": head,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Materialize a benchmark task as a local review target.")
    ap.add_argument("--manifest", required=True, help="review-task/1 JSON manifest")
    ap.add_argument("--out", required=True, help="output task directory")
    ap.add_argument("--force", action="store_true", help="replace an existing non-empty output dir")
    args = ap.parse_args()

    manifest = load_manifest(args.manifest)
    print(json.dumps(materialize(manifest, args.out, force=args.force), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
