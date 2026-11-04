#!/usr/bin/env python3
"""Adapter: review-change `review-report/1` markdown -> ReviewBench judging input.

Usage:
  uv run --with pyyaml python to_reviewbench.py REPORT.md \
      --repo https://github.com/owner/repo --pr 123 \
      --base <sha> --head <sha> --agent review-change --out findings.json

A finding with no parsable file/line anchor is emitted with file="" and
line=1, and warned about, because ReviewBench requires an integer line.
"""
from __future__ import annotations

import argparse
import json
import sys

from reportlib import parse_report

# ReviewBench validates the PR identity against the golden entry, so the
# candidate must carry the exact repo/pr/base/head of the benchmark task.


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("report")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--pr", type=int, required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", required=True)
    ap.add_argument("--agent", default="review-change")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    _fm, findings = parse_report(args.report)
    out_findings = []
    for f in findings:
        if not f.file:
            print(f"WARN: {f.id} has no file anchor; emitting file=\"\" line=1", file=sys.stderr)
        out_findings.append(
            {
                "producer": args.agent,
                "file": f.file or "",
                "start_line": f.start_line or 1,
                "end_line": f.end_line or f.start_line or 1,
                "message": f.message,
            }
        )

    doc = {
        "pr": {
            "repo": args.repo,
            "pr_number": args.pr,
            "base": args.base,
            "head": args.head,
        },
        "agent": args.agent,
        "findings": out_findings,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
    print(f"wrote {args.out}: {len(out_findings)} findings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
