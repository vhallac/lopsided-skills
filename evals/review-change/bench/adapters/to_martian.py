#!/usr/bin/env python3
"""Adapter: review-change `review-report/1` markdown -> martian candidate files.

The martian offline pipeline reads candidates from
`results/<model>/candidates.json`, keyed [golden_url][tool] = [{ "text": ... }],
and reviews from `results/benchmark_data.json`. This writes both: a candidate
entry for one PR, and a minimal benchmark_data.json that references it so
step3_judge_comments can run without downloading anything from GitHub.

Usage:
  uv run --with pyyaml python to_martian.py REPORT.md \
      --pr-url https://github.com/owner/repo/pull/123 \
      --tool review-change --model-dir OUTDIR --out-data OUTDIR/benchmark_data.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from reportlib import parse_report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("report")
    ap.add_argument("--pr-url", required=True, help="golden key (the PR url)")
    ap.add_argument("--repo-name", default="")
    ap.add_argument("--tool", default="review-change")
    ap.add_argument("--model-dir", required=True, help="results/<model> dir")
    ap.add_argument("--out-data", required=True, help="benchmark_data.json path")
    ap.add_argument("--golden-comments", required=True,
                    help="path to the golden_comments json containing this PR url")
    args = ap.parse_args()

    _fm, findings = parse_report(args.report)
    candidates = [{"text": f.message, "file": f.file, "start_line": f.start_line} for f in findings]

    os.makedirs(args.model_dir, exist_ok=True)
    cand_path = os.path.join(args.model_dir, "candidates.json")
    existing: dict = {}
    if os.path.exists(cand_path):
        existing = json.load(open(cand_path, encoding="utf-8"))
    existing.setdefault(args.pr_url, {})[args.tool] = candidates
    with open(cand_path, "w", encoding="utf-8") as fh:
        json.dump(existing, fh, indent=2)

    golden = json.load(open(args.golden_comments, encoding="utf-8"))
    entry = next((p for p in golden if p.get("url") == args.pr_url), None)
    if entry is None:
        print(f"ERROR: {args.pr_url} not found in {args.golden_comments}", file=sys.stderr)
        return 1
    golden_comments = [{"comment": c["comment"], "severity": c["severity"], "category": c["category"]}
                       for c in entry["comments"]]

    data = {
        args.pr_url: {
            "repo_name": args.repo_name,
            "golden_comments": golden_comments,
            "reviews": [
                {
                    "tool": args.tool,
                    "repo_name": args.repo_name,
                    "pr_url": args.pr_url,
                    # raw comments intentionally absent; candidates.json supplies the text
                    "review_comments": [],
                }
            ],
        }
    }
    with open(args.out_data, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)

    print(f"wrote {cand_path}: {len(candidates)} candidates")
    print(f"wrote {args.out_data}: 1 PR, {len(golden_comments)} golden comments")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
